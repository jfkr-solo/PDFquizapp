"""STEP 5: 教材JSONを JSON Schema と10項目の自動チェックで検証し、レポートを出す。

入力 : book.json（STEP 4）、pages.json（任意：ページ照合用）
出力 : book.json（validation_status / validation_issues を更新）、validation_report.md、validation_report.json

状態の決め方
- error または review レベルの指摘がある問題 → pending（通常の模擬試験には出さない）
- warning だけの問題 → auto_ok（自動検証は合格）
- 人が原本と照合済み（verified）で、内容が確認時から変わっていない → verified のまま
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator

from .build_json import FIGURE_HINT, content_hash

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "question_book.schema.json"
AUTO_CODES_PREFIX = "V_"  # このモジュールが付ける指摘コードの接頭辞（再実行時に付け直す）

GARBLED_CHARS = re.compile(r"[�〓-\x00-\x08\x0b\x0c\x0e-\x1f]")
OCR_SPACED_DIGITS = re.compile(r"\d \d")
MIXED_SHORT_LINE = re.compile(r"^(?=.*[A-Za-z]{2})(?=.*[一-鿿])[^\s。、,.]{2,12}$")
EXPL_ANSWER = re.compile(r"(?:正解|答え)は\s*([アイウエオカキクA-H①-⑧○×])")


def _issue(code: str, level: str, msg: str) -> dict:
    return {"code": AUTO_CODES_PREFIX + code, "level": level, "message": msg}


def _norm_text(s: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s))


def schema_errors(book: dict) -> list[str]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    v = Draft202012Validator(schema)
    out = []
    for e in sorted(v.iter_errors(book), key=lambda e: list(e.absolute_path)):
        path = "/".join(str(p) for p in e.absolute_path)
        out.append(f"{path or '(root)'}: {e.message}")
    return out


def check_question(q: dict, ctx: dict) -> list[dict]:
    iss: list[dict] = []
    qt = q["question_type"]
    opt_ids = [o["id"] for o in q["options"]]

    # 3. 選択肢の欠落
    if qt in ("single_choice", "multiple_choice"):
        if len(q["options"]) < 2:
            iss.append(_issue("OPTIONS_MISSING", "error", f"選択肢が{len(q['options'])}個しかありません"))
        expected = [chr(ord("A") + i) for i in range(len(opt_ids))]
        if opt_ids != expected:
            iss.append(_issue("OPTIONS_GAP", "error", f"選択肢の並びが不連続です: {','.join(opt_ids)}"))
        for o in q["options"]:
            if not o["text"].strip():
                iss.append(_issue("OPTION_EMPTY", "error", f"選択肢{o.get('label', o['id'])}の本文が空です"))
    if not q["question"].strip():
        iss.append(_issue("QUESTION_EMPTY", "error", "問題文が空です"))

    # 4. 正解の欠落 / 5. 正解が選択肢に存在するか
    if qt == "numeric":
        if not q.get("numeric_answer"):
            iss.append(_issue("NO_ANSWER", "error", "数値の正解がありません"))
    else:
        if not q["correct_answers"]:
            iss.append(_issue("NO_ANSWER", "error", "正解がありません"))
        for c in q["correct_answers"]:
            if c not in opt_ids:
                iss.append(_issue("ANSWER_NOT_IN_OPTIONS", "error", f"正解「{c}」が選択肢にありません"))
        if qt == "single_choice" and len(q["correct_answers"]) > 1:
            iss.append(_issue("MULTI_ANSWER_SINGLE", "error", "単一選択なのに正解が複数あります"))

    # 6. 解説と正解の整合性
    expl = q["explanation"]
    if not expl:
        iss.append(_issue("NO_EXPLANATION", "warning", "解説がありません（空欄として扱います）"))
    else:
        labels = {o["id"]: o.get("label", o["id"]) for o in q["options"]}
        correct_labels = {labels.get(c, c) for c in q["correct_answers"]}
        for m in EXPL_ANSWER.finditer(expl):
            if correct_labels and m.group(1) not in correct_labels:
                iss.append(_issue("EXPLANATION_CONFLICT", "error",
                                  f"解説は「正解は{m.group(1)}」としていますが、解答は{'・'.join(sorted(correct_labels))}です"))
        na = q.get("numeric_answer")
        if qt == "numeric" and na:
            v = na["value"]
            vs = str(int(v)) if float(v).is_integer() else str(v)
            if vs not in _norm_text(expl):
                iss.append(_issue("EXPLANATION_NUMBER_MISMATCH", "warning", f"解説に正解の数値「{vs}」が見当たりません"))

    # 7. 文字化け・判読不能
    texts = [q["question"], expl] + [o["text"] for o in q["options"]]
    if any(GARBLED_CHARS.search(t) for t in texts):
        iss.append(_issue("GARBLED", "error", "文字化け・判読不能な文字（〓、�など）を含みます"))
    if q["source"].get("extraction") == "ocr":
        if any(OCR_SPACED_DIGITS.search(t) for t in texts):
            iss.append(_issue("OCR_SPACING", "review", "OCRで数字の間に空白が入っています（例: 5 0）"))
        if any(MIXED_SHORT_LINE.match(line) for line in q["question"].splitlines()):
            iss.append(_issue("OCR_NOISE", "review", "図などをOCRした意味のない行が問題文に混入している可能性があります"))

    # 9. ページ番号の対応
    pages = ctx["pages_total"]
    src = q["source"]
    if pages and not (1 <= src["page"] <= pages):
        iss.append(_issue("PAGE_OUT_OF_RANGE", "error", f"ページ番号{src['page']}が原本の範囲（1〜{pages}）外です"))
    elif ctx["page_texts"] and src.get("raw_text") and src.get("extraction") != "manual" \
            and not any(i["code"] == "FROM_RESCAN" for i in q.get("validation_issues", [])):
        # 書き起こしや撮り直しの文は原本ページのOCRと一致しないので照らさない（どちらも要確認になる）
        head = _norm_text(src["raw_text"].splitlines()[0])[:15]
        if head and head not in ctx["page_texts"].get(src["page"], ""):
            iss.append(_issue("PAGE_MISMATCH", "error", f"問題の書き出しが{src['page']}ページに見当たりません"))

    # 10. 画像参照の存在
    for im in q.get("images", []):
        if not (ctx["book_dir"] / im["path"]).is_file():
            iss.append(_issue("IMAGE_NOT_FOUND", "error", f"画像ファイルがありません: {im['path']}"))
    if FIGURE_HINT.search(q["question"]) and not q.get("images"):
        iss.append(_issue("FIGURE_MISSING", "error", "図表を参照していますが画像がありません"))
    return iss


def check_book(book: dict) -> tuple[list[dict], dict[str, list[dict]]]:
    """問題をまたぐチェック：1. 番号の連続性 2. 件数 8. 重複"""
    book_iss: list[dict] = []
    per_q: dict[str, list[dict]] = defaultdict(list)
    qs = book["questions"]

    # 1. 問題番号の連続性（章ごとに振り直す本にも対応）
    prev_num, prev_ch = None, None
    nums_by_ch: dict[str, Counter] = defaultdict(Counter)
    for q in qs:
        n, ch = q["source"]["question_number"], q.get("chapter", "")
        nums_by_ch[ch][n] += 1
        if prev_num is not None:
            restart = ch != prev_ch and n == 1
            if not restart and n != prev_num + 1:
                kind = "重複" if n <= prev_num else "欠番"
                per_q[q["id"]].append(_issue("NUMBER_SEQUENCE", "error", f"問{prev_num}の次が問{n}です（{kind}の可能性）"))
        prev_num, prev_ch = n, ch

    # 2. 問題数と抽出件数の一致
    exp = book.get("expected_question_count")
    if exp and exp != len(qs):
        book_iss.append(_issue("COUNT_MISMATCH", "error", f"想定{exp}問に対して{len(qs)}問を抽出しました"))
    ac = book.get("answers_count")
    from_key = qs and all(q["source"].get("answer_source") == "answer_key" for q in qs)  # 正解を別紙の一覧から取った本は解答ページの数を問わない
    if ac is not None and ac != len(qs) and not from_key:
        book_iss.append(_issue("ANSWER_COUNT_MISMATCH", "error", f"問題{len(qs)}問に対して解答が{ac}件です"))

    # 8. 重複問題
    seen: dict[str, str] = {}
    for q in qs:
        key = _norm_text(q["question"]) + "|" + "|".join(_norm_text(o["text"]) for o in q["options"])
        if len(key) > 5 and key in seen:
            per_q[q["id"]].append(_issue("DUPLICATE", "warning", f"{seen[key]} と同じ内容の問題です"))
        else:
            seen.setdefault(key, q["id"])
    return book_iss, per_q


def validate_book(book: dict, *, book_dir: str | Path, pages_json: dict | None = None) -> dict:
    book_dir = Path(book_dir)
    ctx = {
        "book_dir": book_dir,
        "pages_total": (book.get("source_pdf") or {}).get("pages"),
        "page_texts": {p["page"]: _norm_text("".join(l["text"] for l in p["lines"])) for p in pages_json["pages"]} if pages_json else {},
    }
    book_iss, cross = check_book(book)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    for q in book["questions"]:
        base = [i for i in q.get("validation_issues", []) if not i["code"].startswith(AUTO_CODES_PREFIX)]
        q["validation_issues"] = base + check_question(q, ctx) + cross.get(q["id"], [])
        q["content_hash"] = content_hash(q)
        blocking = any(i["level"] in ("error", "review") for i in q["validation_issues"])
        old = q.get("validation_status", "pending")
        if old == "verified" and q.get("verified_hash") == q["content_hash"]:
            new = "verified"  # 人の確認を優先
        elif old == "rejected":
            new = "rejected"
        else:
            if old == "verified":
                q["validation_issues"].append(_issue("CHANGED_AFTER_VERIFY", "review", "確認済みの後で内容が変わりました"))
            new = "pending" if blocking or old == "verified" else "auto_ok"
        if new != old or not q.get("validation_history"):
            q.setdefault("validation_history", []).append({"at": now, "by": "auto", "status": new})
        q["validation_status"] = new
    book["book_issues"] = [i for i in book.get("book_issues", []) if not i["code"].startswith(AUTO_CODES_PREFIX)] + book_iss
    book.setdefault("exam_policy", {"allowed_statuses": ["verified", "auto_ok"]})
    errs = schema_errors(book)
    return {"schema_errors": errs, "book": book}


def render_report(book: dict, schema_errs: list[str]) -> str:
    qs = book["questions"]
    st = Counter(q["validation_status"] for q in qs)
    codes = Counter(i["code"] for q in qs for i in q["validation_issues"])
    L = [f"# 検証レポート：{book['book_title']}（{book['book_id']} v{book['version']}）", "",
         f"- 生成日時: {book.get('generated_at', '')}",
         f"- 原本: {book.get('source_pdf', {}).get('file', '')}（{book.get('source_pdf', {}).get('pages', '?')}ページ）",
         f"- 問題数: {len(qs)}",
         f"- 状態: 確認済み {st['verified']} / 自動検証OK {st['auto_ok']} / 要確認 {st['pending']} / 除外 {st['rejected']}",
         f"- JSON Schema: {'OK' if not schema_errs else f'エラー {len(schema_errs)}件'}", ""]
    if schema_errs:
        L += ["## JSON Schemaエラー", ""] + [f"- {e}" for e in schema_errs[:50]] + [""]
    if book.get("book_issues"):
        L += ["## 問題集全体の指摘", ""] + [f"- [{i['level']}] {i['code']}: {i['message']}" for i in book["book_issues"]] + [""]
    if codes:
        L += ["## 指摘の内訳", "", "| コード | 件数 |", "| --- | --- |"] + [f"| {c} | {n} |" for c, n in codes.most_common()] + [""]
    L += ["## 問題別の指摘（要確認のみ）", "", "| ID | 問題番号 | ページ | 状態 | 指摘 |", "| --- | --- | --- | --- | --- |"]
    for q in qs:
        if q["validation_status"] != "pending":
            continue
        msg = "<br>".join(f"[{i['level']}] {i['message']}" for i in q["validation_issues"] if i["level"] != "warning")
        L.append(f"| {q['id']} | 問{q['source']['question_number']} | p.{q['source']['page']} | {q['validation_status']} | {msg} |")
    return "\n".join(L) + "\n"


def validate_file(book_path, *, pages_path=None) -> dict:
    book_path = Path(book_path)
    book = json.loads(book_path.read_text(encoding="utf-8"))
    pages_json = json.loads(Path(pages_path).read_text(encoding="utf-8")) if pages_path and Path(pages_path).exists() else None
    res = validate_book(book, book_dir=book_path.parent, pages_json=pages_json)
    book_path.write_text(json.dumps(res["book"], ensure_ascii=False, indent=1), encoding="utf-8")
    (book_path.parent / "validation_report.md").write_text(render_report(res["book"], res["schema_errors"]), encoding="utf-8")
    summary = {
        "schema_errors": res["schema_errors"],
        "status_counts": dict(Counter(q["validation_status"] for q in res["book"]["questions"])),
        "issue_counts": dict(Counter(i["code"] for q in res["book"]["questions"] for i in q["validation_issues"])),
        "book_issues": res["book"]["book_issues"],
    }
    (book_path.parent / "validation_report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    return summary
