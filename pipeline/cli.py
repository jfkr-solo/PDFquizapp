"""PDF → 教材JSON の一括実行コマンド。

使い方（プロジェクト直下で実行）:
  python -m pipeline.cli convert <PDF> --book-id IT001 --title "IT基礎問題集" [--expected 6] [--ai]
  python -m pipeline.cli validate IT001
  python -m pipeline.cli verify IT001 IT001-Q0003 --note "原本と照合"
  python -m pipeline.cli reject IT001 IT001-Q0004 --note "図が判読不能"
  python -m pipeline.cli publish IT001          # Supabaseへ取り込み（STEP 8）

各工程の出力は data/books/<book_id>/ に保存されます（pages.json → parsed.json → book.json → validation_report.md）。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from .build_json import build_file
from .answer_key import AnswerKeyError, load_answer_key
from .extract import ExtractError, extract_pdf, sha256_of, summarize
from .parse import load_explanations, load_transcriptions, parse_file
from .validate import validate_file

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("PDFQUIZ_DATA") or ROOT / "data")  # テストでは一時フォルダに差し替える


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """.env の KEY=VALUE を環境変数に読み込む（既に設定済みの値は上書きしない）。"""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            if v.strip():
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def book_dir(book_id: str) -> Path:
    return DATA / "books" / book_id


def cmd_convert(a) -> int:
    pdf = Path(a.pdf)
    raw_dir = DATA / "raw" / a.book_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_pdf = raw_dir / "source.pdf"
    if pdf.resolve() != raw_pdf.resolve():
        shutil.copy2(pdf, raw_pdf)  # 原本は raw に保管し、加工データと分離する
    out = book_dir(a.book_id)
    out.mkdir(parents=True, exist_ok=True)

    # supplement コマンドで同じ条件のまま作り直せるよう、変換の条件を残す
    settings = {"title": a.title, "version": a.version, "expected": a.expected, "ocr_lang": a.ocr_lang,
                "chapter_pages": a.chapter_pages, "answer_key": bool(a.answer_key)}
    (out / "convert.json").write_text(json.dumps(settings, ensure_ascii=False, indent=1), encoding="utf-8")

    print("[1/4] PDF抽出 ...")
    pj = out / "pages.json"
    if a.reuse_pages and pj.exists() and json.loads(pj.read_text(encoding="utf-8"))["source_pdf"]["sha256"] == sha256_of(raw_pdf):
        print("      前回の抽出結果（pages.json）を使います")
    else:
        pages = extract_pdf(raw_pdf, out, ocr_lang=a.ocr_lang, force_ocr=a.force_ocr)
        print("      " + summarize(pages))

    print("[2/4] 問題・解答の構造化 ...")
    chapter_pages = [int(x) for x in a.chapter_pages.split(",")] if a.chapter_pages else None
    key = None
    if a.answer_key:
        key_src = Path(a.answer_key) if Path(a.answer_key).parent.resolve() == raw_dir.resolve() else raw_dir / ("answer_key" + Path(a.answer_key).suffix.lower())
        if Path(a.answer_key).resolve() != key_src.resolve():
            shutil.copy2(a.answer_key, key_src)  # 正解一覧も原本と一緒に保管する
        key = load_answer_key(key_src)
        print(f"      正解一覧: {len(key)}問分")
    sups = _load_supplements(raw_dir, out, a.ocr_lang)
    if sups:
        print(f"      撮り直しPDF: {len(sups)}件")
    tr_path = raw_dir / "transcriptions.jsonl"
    trs = load_transcriptions(tr_path) if tr_path.exists() else None
    if trs:
        print(f"      書き起こし: {len(trs)}問")
    ex_path = raw_dir / "explanations.jsonl"
    exs = load_explanations(ex_path) if ex_path.exists() else None
    if exs:
        print(f"      解説の書き起こし: {len(exs)}問")
    parsed = parse_file(pj, out / "parsed.json", chapter_pages=chapter_pages, answer_key=key, supplements=sups,
                        transcriptions=trs, explanations=exs)
    if a.ai:
        from .ai_assist import assist_parsed
        parsed = assist_parsed(out / "pages.json", out / "parsed.json")
    print(f"      問題 {len(parsed['questions'])}問 / 解答 {parsed['answers_count']}件 / 全体の指摘 {len(parsed['issues'])}件")

    print("[3/4] 教材JSON生成 ...")
    book = build_file(out / "parsed.json", out / "book.json", book_id=a.book_id, title=a.title,
                      version=a.version, pdf_path=raw_pdf, expected_question_count=a.expected)
    print(f"      {out / 'book.json'}（{len(book['questions'])}問）")

    print("[4/4] 検証 ...")
    return _print_validation(validate_file(out / "book.json", pages_path=out / "pages.json"), out)


def _load_supplements(raw_dir: Path, out: Path, ocr_lang: str) -> list[tuple[str, dict, int | None]]:
    """raw/<ID>/supplements/ の撮り直しPDFを読み取る（同じPDFは前回の結果を使う）。ファイル名の _ch7 は章の指定。"""
    import re as _re
    sup_dir = raw_dir / "supplements"
    res = []
    for pdf in sorted(sup_dir.glob("*.pdf")) if sup_dir.is_dir() else []:
        cache = out / "supplements" / pdf.stem
        pj = cache / "pages.json"
        if not (pj.exists() and json.loads(pj.read_text(encoding="utf-8"))["source_pdf"]["sha256"] == sha256_of(pdf)):
            extract_pdf(pdf, cache, ocr_lang=ocr_lang)
        m = _re.search(r"_ch(\d+)$", pdf.stem)
        res.append((pdf.name, json.loads(pj.read_text(encoding="utf-8")), int(m.group(1)) if m else None))
    return res


def cmd_supplement(a) -> int:
    """読み取りが崩れた問題を撮り直したPDFを追加し、前回と同じ条件で作り直す。"""
    out = book_dir(a.book_id)
    conf = out / "convert.json"
    if not conf.exists():
        print("エラー: 前回の変換条件（convert.json）がありません。先に convert をやり直してください。", file=sys.stderr)
        return 2
    st = json.loads(conf.read_text(encoding="utf-8"))
    raw_dir = DATA / "raw" / a.book_id
    sup_dir = raw_dir / "supplements"
    sup_dir.mkdir(parents=True, exist_ok=True)
    n = len(list(sup_dir.glob("*.pdf"))) + 1
    dest = sup_dir / f"{n:02d}{'_ch' + str(a.chapter) if a.chapter else ''}.pdf"
    shutil.copy2(a.pdf, dest)
    print(f"撮り直しPDFを {dest} に保存しました")
    keys = sorted(raw_dir.glob("answer_key.*"))
    args = argparse.Namespace(pdf=str(raw_dir / "source.pdf"), book_id=a.book_id, title=st["title"], version=st["version"],
                              expected=st["expected"], ocr_lang=st["ocr_lang"], force_ocr=False, ai=False,
                              chapter_pages=st["chapter_pages"], answer_key=str(keys[0]) if st["answer_key"] and keys else None,
                              reuse_pages=True)
    return cmd_convert(args)


def _print_validation(summary: dict, out: Path) -> int:
    st = summary["status_counts"]
    print(f"      自動検証OK {st.get('auto_ok', 0)} / 確認済み {st.get('verified', 0)} / 要確認 {st.get('pending', 0)} / 除外 {st.get('rejected', 0)}")
    print(f"      JSON Schema: {'OK' if not summary['schema_errors'] else 'エラーあり'}")
    print(f"      レポート: {out / 'validation_report.md'}")
    for e in summary["schema_errors"][:10]:
        print("      SCHEMA:", e, file=sys.stderr)
    return 1 if summary["schema_errors"] else 0


def cmd_validate(a) -> int:
    out = book_dir(a.book_id)
    return _print_validation(validate_file(out / "book.json", pages_path=out / "pages.json"), out)


def _set_status(a, status: str) -> int:
    out = book_dir(a.book_id)
    path = out / "book.json"
    book = json.loads(path.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    targets = set(a.question_ids)
    hit = 0
    for q in book["questions"]:
        if q["id"] in targets:
            q["validation_status"] = status
            q["verified_hash"] = q["content_hash"] if status == "verified" else None
            q.setdefault("validation_history", []).append({"at": now, "by": a.by, "status": status, "note": a.note or ""})
            hit += 1
    missing = targets - {q["id"] for q in book["questions"]}
    if missing:
        print("見つからないID:", ", ".join(sorted(missing)), file=sys.stderr)
    path.write_text(json.dumps(book, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{hit}問を {status} にしました")
    return _print_validation(validate_file(path, pages_path=out / "pages.json"), out)


def cmd_publish(a) -> int:
    from .supabase_import import PublishError, publish_book, publish_sql
    try:
        if a.sql:
            Path(a.sql).write_text(publish_sql(book_dir(a.book_id) / "book.json"), encoding="utf-8")
            print(f"SQLを書き出しました: {a.sql}（Supabase の SQL Editor に貼って実行してください）")
            return 0
        r = publish_book(book_dir(a.book_id) / "book.json")
    except PublishError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2
    print(f"Supabaseに取り込みました: {r['book_id']} v{r['version']}（{r['questions']}問、うち出題可能 {r['ready']}問）")
    return 0


def cmd_audio(a) -> int:
    from .audio import build_audio
    from .tts import TTSError, get_engine
    try:
        engine = get_engine(a.engine, a.voice, a.speed)
        r = build_audio(book_dir(a.book_id) / "book.json", engine, pause=a.pause,
                        include_pending=a.include_pending, chapters=not a.no_chapters)
    except TTSError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2
    print(f"音声を作りました: {r['questions']}問（読み上げ対象外 {r['skipped']}問）/ 章ごと {r['chapters']}本")
    print(f"      新規合成 {r['synthesized']}件 / キャッシュ利用 {r['cached']}件 → {r['dir']}")
    return 0


def main(argv=None) -> int:
    load_dotenv()
    p = argparse.ArgumentParser(prog="pipeline", description="PDF問題集 → 教材JSON 変換")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("convert", help="PDFを抽出・構造化・JSON化・検証まで一括実行")
    c.add_argument("pdf")
    c.add_argument("--book-id", required=True)
    c.add_argument("--title", required=True)
    c.add_argument("--version", default="1.0")
    c.add_argument("--expected", type=int, help="原本の問題数（件数チェック用）")
    c.add_argument("--ocr-lang", default="jpn")
    c.add_argument("--force-ocr", action="store_true", help="全ページをOCRする")
    c.add_argument("--ai", action="store_true", help="ルールで分割できなかった部分を生成AIで補助する")
    c.add_argument("--chapter-pages", help="各章が始まるPDFのページ（例 1,29,41）。章の見出しが読めない本で、章ごとに問題番号が戻るとき")
    c.add_argument("--answer-key", help="別紙の正解一覧（PDFまたはテキスト。「第1章 第1問 ②」の並び）。解答ページが読めないとき")
    c.add_argument("--reuse-pages", action="store_true", help="同じPDFなら前回のOCR結果を使い、抽出を飛ばす（解析だけやり直すとき）")
    c.set_defaults(func=cmd_convert)
    su = sub.add_parser("supplement", help="読み取りが崩れた問題を撮り直したPDFで差し替える")
    su.add_argument("book_id")
    su.add_argument("pdf")
    su.add_argument("--chapter", type=int, help="撮り直したページの章（省略すると、その番号が崩れている章を自動で選ぶ）")
    su.set_defaults(func=cmd_supplement)
    v = sub.add_parser("validate", help="book.json を再検証してレポートを更新")
    v.add_argument("book_id")
    v.set_defaults(func=cmd_validate)
    for name, status in (("verify", "verified"), ("reject", "rejected")):
        s = sub.add_parser(name, help=f"問題を {status} にする（人が原本と照合した結果）")
        s.add_argument("book_id")
        s.add_argument("question_ids", nargs="+")
        s.add_argument("--note")
        s.add_argument("--by", default="reviewer")
        s.set_defaults(func=lambda a, st=status: _set_status(a, st))
    pb = sub.add_parser("publish", help="book.json をSupabaseに取り込む（STEP 8）")
    pb.add_argument("book_id")
    pb.add_argument("--sql", metavar="FILE", help="取り込まずに、SQL Editor で実行するSQLをFILEに書き出す（service_role キー不要）")
    pb.set_defaults(func=cmd_publish)
    au = sub.add_parser("audio", help="問題ごと・章ごとのMP3を作る（STEP 9）")
    au.add_argument("book_id")
    au.add_argument("--engine", default=None, help="voicevox（ローカル）/ google（クラウド）/ dummy（テスト）。既定は環境変数 TTS_ENGINE")
    au.add_argument("--voice", default=None, help="VOICEVOXは話者ID、Googleは音声名（例 ja-JP-Neural2-B）")
    au.add_argument("--speed", type=float, default=1.0, help="読み上げ速度 0.5〜2.0")
    au.add_argument("--pause", type=float, default=5.0, help="問題と正解の間の考える時間（秒）")
    au.add_argument("--include-pending", action="store_true", help="要確認の問題も読み上げる（正解が未照合）")
    au.add_argument("--no-chapters", action="store_true", help="章ごとのMP3を作らない")
    au.set_defaults(func=cmd_audio)
    a = p.parse_args(argv)
    if a.cmd != "convert" and not (book_dir(a.book_id) / "book.json").exists():
        print(f"エラー: 問題集 {a.book_id} が見つかりません（{book_dir(a.book_id)}）。先に convert を実行してください。", file=sys.stderr)
        return 2
    try:
        return a.func(a)
    except (ExtractError, AnswerKeyError, FileNotFoundError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
