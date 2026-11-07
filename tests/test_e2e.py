"""STEP 10: 通しテスト。実際のコマンドを順に実行し、PDF → 教材JSON → 検証 → 人の確認 → 音声 → アプリ用データ まで確かめる。

  python -m pytest tests/test_e2e.py -q

データは一時フォルダ（環境変数 PDFQUIZ_DATA）に作るので、data/ やアプリのサンプルは変わらない。
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from pipeline.extract import find_tessdata
from tests.make_sample_pdf import make_large_pdf, make_scan_pdf, make_text_pdf

ROOT = Path(__file__).resolve().parent.parent


def cli(data: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PDFQUIZ_DATA": str(data), "SUPABASE_URL": "", "SUPABASE_SERVICE_ROLE_KEY": ""}
    return subprocess.run([sys.executable, "-m", "pipeline.cli", *args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)


def book(data: Path, book_id: str) -> dict:
    return json.loads((data / "books" / book_id / "book.json").read_text(encoding="utf-8"))


def statuses(b: dict) -> dict:
    return {q["id"]: q["validation_status"] for q in b["questions"]}


def test_full_flow_text_pdf(tmp_path):
    data, pdf = tmp_path / "data", tmp_path / "in" / "text.pdf"
    pdf.parent.mkdir()
    make_text_pdf(pdf)

    r = cli(data, "convert", str(pdf), "--book-id", "E2E01", "--title", "通しテスト", "--expected", "6")
    assert r.returncode == 0, r.stderr
    assert "自動検証OK 6" in r.stdout and "JSON Schema: OK" in r.stdout
    assert (data / "raw" / "E2E01" / "source.pdf").exists()                 # 原本は raw に分けて保管
    for f in ("pages.json", "parsed.json", "book.json", "validation_report.md", "validation_report.json"):
        assert (data / "books" / "E2E01" / f).exists(), f

    # 人の確認：1問を除外、1問を確認済みに
    assert cli(data, "reject", "E2E01", "E2E01-Q0006", "--note", "通しテスト").returncode == 0
    assert cli(data, "verify", "E2E01", "E2E01-Q0001", "--note", "原本p.1と照合").returncode == 0
    s = statuses(book(data, "E2E01"))
    assert s["E2E01-Q0001"] == "verified" and s["E2E01-Q0006"] == "rejected"

    # 再検証しても人の判断は残る
    assert cli(data, "validate", "E2E01").returncode == 0
    assert statuses(book(data, "E2E01")) == s

    # 音声（ffmpeg があるとき）：除外した問題は読まない
    if shutil.which("ffmpeg"):
        r = cli(data, "audio", "E2E01", "--engine", "dummy", "--pause", "1")
        assert r.returncode == 0, r.stderr
        assert "5問（読み上げ対象外 1問）" in r.stdout
        b = book(data, "E2E01")
        assert "audio" not in b["questions"][5] and (data / "books" / "E2E01" / b["questions"][0]["audio"]["full"]).exists()

    # アプリ用データ（node があるとき）
    if shutil.which("node"):
        out = tmp_path / "public_books"
        env = {**os.environ, "PDFQUIZ_DATA": str(data), "PDFQUIZ_PUBLIC_BOOKS": str(out)}
        r = subprocess.run(["node", "scripts/sync-books.mjs"], cwd=ROOT / "web", env=env, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        index = json.loads((out / "index.json").read_text(encoding="utf-8"))
        assert index == [{"book_id": "E2E01", "book_title": "通しテスト", "version": "1.0", "question_count": 6, "ready_count": 5}]
        assert (out / "E2E01" / "images").is_dir()
        if shutil.which("ffmpeg"):
            assert (out / "E2E01" / "audio" / "manifest.json").exists()
            assert not (out / "E2E01" / "audio" / ".cache").exists()      # キャッシュは配信しない


@pytest.mark.skipif(not find_tessdata(), reason="Tesseract（日本語）がありません")
def test_full_flow_scan_pdf_needs_review(tmp_path):
    data = tmp_path / "data"
    make_text_pdf(tmp_path / "t.pdf")
    make_scan_pdf(tmp_path / "t.pdf", tmp_path / "scan.pdf")
    r = cli(data, "convert", str(tmp_path / "scan.pdf"), "--book-id", "E2E02", "--title", "スキャン", "--expected", "6")
    assert r.returncode == 0, r.stderr
    b = book(data, "E2E02")
    assert b["questions"] and all(q["validation_status"] == "pending" for q in b["questions"])   # OCR由来は必ず要確認
    if shutil.which("ffmpeg"):
        r = cli(data, "audio", "E2E02", "--engine", "dummy")
        assert "0問" in r.stdout                                                  # 要確認は読み上げない


def test_large_book_1000_questions(tmp_path):
    data = tmp_path / "data"
    make_large_pdf(tmp_path / "large.pdf", n=1000, chapters=10)
    t = time.time()
    r = cli(data, "convert", str(tmp_path / "large.pdf"), "--book-id", "E2E1000", "--title", "1000問", "--expected", "1000")
    elapsed = time.time() - t
    assert r.returncode == 0, r.stderr
    b = book(data, "E2E1000")
    assert len(b["questions"]) == 1000 and all(q["validation_status"] == "auto_ok" for q in b["questions"])
    assert len({q["chapter"] for q in b["questions"]}) == 10
    q = b["questions"][9]
    assert q["source"]["question_number"] == 10 and q["correct_answers"] == ["C"]     # 問10 → 10%4=2 → ウ
    assert elapsed < 120, f"1000問の変換に {elapsed:.0f}秒かかりました"


def test_count_mismatch_is_reported(tmp_path):
    data = tmp_path / "data"
    make_text_pdf(tmp_path / "t.pdf")
    r = cli(data, "convert", str(tmp_path / "t.pdf"), "--book-id", "E2E03", "--title", "件数違い", "--expected", "8")
    report = (data / "books" / "E2E03" / "validation_report.md").read_text(encoding="utf-8")
    assert "COUNT_MISMATCH" in report


def test_errors_are_explained(tmp_path):
    data = tmp_path / "data"
    r = cli(data, "convert", str(tmp_path / "nothing.pdf"), "--book-id", "E2E04", "--title", "x")
    assert r.returncode == 2 and "エラー" in r.stderr
    bad = tmp_path / "bad.pdf"
    bad.write_text("これはPDFではありません", encoding="utf-8")
    r = cli(data, "convert", str(bad), "--book-id", "E2E05", "--title", "x")
    assert r.returncode == 2 and "エラー" in r.stderr and "Traceback" not in r.stderr
    r = cli(data, "validate", "NOBOOK")
    assert r.returncode == 2 and "エラー" in r.stderr
    make_text_pdf(tmp_path / "t.pdf")
    cli(data, "convert", str(tmp_path / "t.pdf"), "--book-id", "E2E06", "--title", "x")
    r = cli(data, "publish", "E2E06")
    assert r.returncode == 2 and "SUPABASE_URL" in r.stderr                       # 環境変数が無ければ送らない
    r = cli(data, "audio", "E2E06", "--engine", "dummy", "--speed", "5")
    assert r.returncode == 2 and "0.5〜2.0" in r.stderr
