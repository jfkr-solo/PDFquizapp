"""STEP 9: 教材JSONから音声教材（MP3）を作る。

  python -m pipeline.cli audio IT001 --engine voicevox --pause 5 --speed 1.0

出力（data/books/<book_id>/audio/）
  <問題ID>_q.mp3     問題文と選択肢
  <問題ID>_a.mp3     正解と解説
  <問題ID>.mp3       問題 → 待ち時間（考える時間）→ 正解・解説
  chapter_01.mp3 …  章ごとに全問をつないだもの（通勤中の聞き流し用）
  manifest.json      どの音声がどの問題IDに対応するか
book.json の各問題にも "audio": {"question", "answer", "full"} を書き込む（アプリが使う）。

- 既定では出題できる問題（verified / auto_ok）だけ。要確認の問題は正解が未照合なので読み上げない。
- 同じ文章・同じエンジン設定の音声はキャッシュ（audio/.cache/）を使い、API料金と時間を節約する。
- ffmpeg が必要（macOS: brew install ffmpeg / Ubuntu: sudo apt install ffmpeg）。
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from .tts import TTSEngine, TTSError

READY = ("verified", "auto_ok")
RATE = 24000
BITRATE = "64k"
GAP_BETWEEN_QUESTIONS = 1.5


def _ffmpeg(*args: str) -> None:
    if not shutil.which("ffmpeg"):
        raise TTSError("ffmpeg が見つかりません（macOS: brew install ffmpeg / Ubuntu: sudo apt install ffmpeg）")
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise TTSError(f"ffmpeg が失敗しました: {r.stderr.strip()[:300]}")


def _to_mp3(src: Path, dst: Path) -> None:
    _ffmpeg("-i", str(src), "-ar", str(RATE), "-ac", "1", "-b:a", BITRATE, str(dst))


def _silence(seconds: float, dst: Path) -> None:
    _ffmpeg("-f", "lavfi", "-i", f"anullsrc=r={RATE}:cl=mono", "-t", f"{seconds:.2f}", "-b:a", BITRATE, str(dst))


def _concat(parts: list[Path], dst: Path) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        for p in parts:
            f.write(f"file '{p.resolve().as_posix()}'\n")
        lst = f.name
    try:
        _ffmpeg("-f", "concat", "-safe", "0", "-i", lst, "-ar", str(RATE), "-ac", "1", "-b:a", BITRATE, str(dst))
    finally:
        Path(lst).unlink(missing_ok=True)


class Synth:
    """文章 → MP3。結果を文章とエンジン設定のハッシュでキャッシュする。"""

    def __init__(self, engine: TTSEngine, cache_dir: Path):
        self.engine = engine
        self.cache_dir = cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.hits = 0
        self.made = 0

    def mp3(self, text: str) -> Path:
        text = text.strip()
        if not text:
            raise TTSError("読み上げる文章が空です")
        key = hashlib.sha256(f"{self.engine.cache_key()}|{text}".encode()).hexdigest()[:20]
        out = self.cache_dir / f"{key}.mp3"
        if out.exists() and out.stat().st_size > 0:
            self.hits += 1
            return out
        raw = self.cache_dir / f"{key}.raw.{self.engine.ext}"
        self.engine.synthesize(text, raw)
        if self.engine.ext == "mp3":
            raw.replace(out)
        else:
            _to_mp3(raw, out)
            raw.unlink(missing_ok=True)
        self.made += 1
        return out


def _chapter_key(q: dict) -> str:
    return q.get("chapter") or "全体"


def build_audio(book_path: str | Path, engine: TTSEngine, *, pause: float = 5.0, include_pending: bool = False,
                chapters: bool = True) -> dict:
    if not 0 <= pause <= 60:
        raise TTSError("待ち時間は 0〜60 秒で指定してください")
    book_path = Path(book_path)
    book = json.loads(book_path.read_text(encoding="utf-8"))
    out = book_path.parent / "audio"
    out.mkdir(exist_ok=True)
    synth = Synth(engine, out / ".cache")
    allowed = set((book.get("exam_policy") or {}).get("allowed_statuses") or READY)

    silence = out / ".cache" / f"silence_{pause:.2f}.mp3"
    gap = out / ".cache" / f"silence_{GAP_BETWEEN_QUESTIONS:.2f}.mp3"
    if pause > 0 and not silence.exists():
        _silence(pause, silence)
    if not gap.exists():
        _silence(GAP_BETWEEN_QUESTIONS, gap)

    manifest = {"book_id": book["book_id"], "version": book["version"], "engine": engine.cache_key(),
                "pause_seconds": pause, "questions": {}, "chapters": []}
    skipped: list[str] = []
    by_chapter: dict[str, list[Path]] = {}
    for q in book["questions"]:
        status = q["validation_status"]
        if status == "rejected" or (status not in allowed and not include_pending):
            q.pop("audio", None)
            skipped.append(q["id"])
            continue
        qa = synth.mp3(q["audio_text"])
        aa = synth.mp3(q.get("audio_answer_text") or "正解は登録されていません。")
        files = {"question": f"audio/{q['id']}_q.mp3", "answer": f"audio/{q['id']}_a.mp3", "full": f"audio/{q['id']}.mp3"}
        shutil.copyfile(qa, book_path.parent / files["question"])
        shutil.copyfile(aa, book_path.parent / files["answer"])
        _concat([qa, *([silence] if pause > 0 else []), aa], book_path.parent / files["full"])
        q["audio"] = files
        manifest["questions"][q["id"]] = {**files, "status": status}
        by_chapter.setdefault(_chapter_key(q), []).append(book_path.parent / files["full"])

    if chapters:
        for i, (name, parts) in enumerate(by_chapter.items(), 1):
            title = synth.mp3(f"{name}。{len(parts)}問です。")
            seq: list[Path] = [title, gap]
            for p in parts:
                seq += [p, gap]
            rel = f"audio/chapter_{i:02d}.mp3"
            _concat(seq, book_path.parent / rel)
            manifest["chapters"].append({"chapter": name, "file": rel, "questions": len(parts)})

    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    book_path.write_text(json.dumps(book, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"questions": len(manifest["questions"]), "skipped": len(skipped), "chapters": len(manifest["chapters"]),
            "synthesized": synth.made, "cached": synth.hits, "dir": str(out)}
