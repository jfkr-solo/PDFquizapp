"""STEP 9: 音声教材のテスト（ダミーエンジンとffmpegで実際にMP3を作る。外部APIは偽物）"""
import base64
import io
import json
import shutil
import subprocess

import pytest

from pipeline.audio import build_audio
from pipeline.build_json import build_book
from pipeline.extract import extract_pdf
from pipeline.parse import parse_pages
from pipeline.tts import TTSError, get_engine
from pipeline.validate import validate_book
from tests.make_sample_pdf import make_text_pdf

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg がありません")


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return float(out)


@pytest.fixture
def book_file(tmp_path):
    make_text_pdf(tmp_path / "s.pdf")
    pages = extract_pdf(tmp_path / "s.pdf", tmp_path)
    book = validate_book(build_book(parse_pages(pages), book_id="T01", title="テスト", pdf_path=tmp_path / "s.pdf", out_dir=tmp_path),
                         book_dir=tmp_path, pages_json=pages)["book"]
    book["questions"][1]["validation_status"] = "pending"
    book["questions"][2]["validation_status"] = "rejected"
    p = tmp_path / "book.json"
    p.write_text(json.dumps(book, ensure_ascii=False), encoding="utf-8")
    return p


def test_audio_per_question_chapter_and_manifest(book_file):
    r = build_audio(book_file, get_engine("dummy"), pause=3)
    assert r["questions"] == 4 and r["skipped"] == 2
    book = json.loads(book_file.read_text(encoding="utf-8"))
    q1, q2, q3 = book["questions"][:3]
    assert q1["audio"] == {"question": "audio/T01-Q0001_q.mp3", "answer": "audio/T01-Q0001_a.mp3", "full": "audio/T01-Q0001.mp3"}
    assert "audio" not in q2 and "audio" not in q3          # 要確認・除外は読み上げない
    d = book_file.parent
    full = duration(d / q1["audio"]["full"])
    assert full == pytest.approx(duration(d / q1["audio"]["question"]) + 3 + duration(d / q1["audio"]["answer"]), abs=0.3)
    m = json.loads((d / "audio" / "manifest.json").read_text(encoding="utf-8"))
    assert set(m["questions"]) == {"T01-Q0001", "T01-Q0004", "T01-Q0005", "T01-Q0006"}
    assert [c["questions"] for c in m["chapters"]] == [1, 3]   # 第1章は Q1（Q2・Q3 は対象外）、第2章は Q4〜Q6
    assert all((d / c["file"]).exists() and duration(d / c["file"]) > 1 for c in m["chapters"])


def test_audio_cache_and_include_pending(book_file):
    first = build_audio(book_file, get_engine("dummy"))
    again = build_audio(book_file, get_engine("dummy"), include_pending=True)
    assert first["synthesized"] > 0
    assert again["questions"] == 5                          # 要確認を含める（除外は含めない）
    assert again["synthesized"] == 2 + 1                    # 増えた1問の問題・正解と、問題数が変わった第1章の見出しだけ
    faster = build_audio(book_file, get_engine("dummy", speed=1.5))
    assert faster["cached"] == 0                            # 速度が変われば作り直す


def test_bad_settings():
    with pytest.raises(TTSError):
        get_engine("dummy", speed=3)
    with pytest.raises(TTSError):
        get_engine("unknown")


def test_voicevox_request(monkeypatch, tmp_path):
    calls = []

    def fake_urlopen(req, timeout=0):
        calls.append(req)
        body = json.dumps({"speedScale": 1.0, "accent_phrases": []}).encode() if "audio_query" in req.full_url else b"RIFFwav"
        return io.BytesIO(body)

    monkeypatch.setenv("VOICEVOX_URL", "http://localhost:9999/")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    eng = get_engine("voicevox", speed=1.25)
    eng.synthesize("問題1。", tmp_path / "x.wav")
    assert calls[0].full_url.startswith("http://localhost:9999/audio_query?") and "speaker=3" in calls[0].full_url
    assert json.loads(calls[1].data)["speedScale"] == 1.25
    assert (tmp_path / "x.wav").read_bytes() == b"RIFFwav"


def test_google_request_keeps_key_out_of_url(monkeypatch, tmp_path):
    calls = []

    def fake_urlopen(req, timeout=0):
        calls.append(req)
        return io.BytesIO(json.dumps({"audioContent": base64.b64encode(b"ID3mp3").decode()}).encode())

    monkeypatch.delenv("GOOGLE_TTS_API_KEY", raising=False)
    with pytest.raises(TTSError):
        get_engine("google")
    monkeypatch.setenv("GOOGLE_TTS_API_KEY", "secret")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    get_engine("google", speed=0.8).synthesize("問題1。", tmp_path / "x.mp3")
    assert "secret" not in calls[0].full_url and calls[0].get_header("X-goog-api-key") == "secret"
    body = json.loads(calls[0].data)
    assert body["audioConfig"] == {"audioEncoding": "MP3", "speakingRate": 0.8} and body["voice"]["languageCode"] == "ja-JP"
    assert (tmp_path / "x.mp3").read_bytes() == b"ID3mp3"
