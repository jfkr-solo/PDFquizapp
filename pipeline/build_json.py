"""STEP 4: parsed.json から教材JSON（book.json）を生成する。

入力 : parsed.json（STEP 3）、原本PDF（図の切り出し用）、書籍設定
出力 : book.json

- 問題IDは <book_id>-Q0001 形式。--chapter-pages を使った本は 章×1000＋問番号（第2章第5問 → Q2005）。
- 正解は原本の記号を A,B,C… に変換するだけで、内容は変えない。
- 図表を参照する問題で画像が無い場合、問題の範囲をページから切り出して添付し「要確認」にする。
- 読み上げ用の audio_text（問題＋選択肢）と audio_answer_text（正解＋解説）を作る。
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pymupdf

from .parse import FAMILIES, OCR_CONFUSION, TF_HINT, TF_FALSE, TF_TRUE

FIGURE_HINT = re.compile(r"図\s*\d*|表\s*\d+|グラフ|下の図|次の図|次の表")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _token_to_id(tok: str, family: str | None) -> str | None:
    tok = OCR_CONFUSION.get(tok, tok)
    fams = [family] if family else list(FAMILIES)
    for fam in fams:
        if tok in FAMILIES[fam]:
            return chr(ord("A") + FAMILIES[fam].index(tok))
    return None


def _question_type(q: dict) -> str:
    if q["options"]:
        return "multiple_choice" if len(q["answer_tokens"]) > 1 else "single_choice"
    if q["numeric_answer"] is not None:
        return "numeric"
    if TF_HINT.search(q["question"]) or (q["answer_tokens"] and all(t in TF_TRUE | TF_FALSE for t in q["answer_tokens"])):
        return "true_false"
    return "single_choice"  # 選択肢が取れていない → 検証で「選択肢の欠落」になる


def content_hash(q: dict) -> str:
    """人の確認後に内容が変わったかを判定するためのハッシュ。"""
    key = json.dumps({k: q.get(k) for k in ("question", "options", "correct_answers", "numeric_answer", "explanation", "images")},
                     ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _speakable(s: str) -> str:
    s = s.replace("\n", "")
    return re.sub(r"\s+", " ", s).strip()


def make_audio_texts(q: dict) -> tuple[str, str]:
    no = q["source"]["question_number"]
    parts = [f"問題{no}。{_speakable(q['question'])}"]
    if q["question_type"] in ("single_choice", "multiple_choice") and q["options"]:
        if q["question_type"] == "multiple_choice":
            parts.append("当てはまるものをすべて選んでください。")
        parts.append("選択肢。" + "。".join(f"{o['label']}、{_speakable(o['text'])}" for o in q["options"]) + "。")
    elif q["question_type"] == "true_false":
        parts.append("マルかバツで答えてください。")
    question_audio = " ".join(parts)

    if q["question_type"] == "numeric" and q["numeric_answer"]:
        na = q["numeric_answer"]
        v = int(na["value"]) if float(na["value"]).is_integer() else na["value"]
        ans = f"正解は、{v}{na.get('unit') or ''}です。"
    elif q["question_type"] == "true_false":
        ans = "正解は、" + ("マル" if q["correct_answers"] == ["T"] else "バツ") + "です。"
    else:
        labels = {o["id"]: o for o in q["options"]}
        ans = "正解は、" + "と、".join(f"{labels[c]['label']}、{_speakable(labels[c]['text'])}" for c in q["correct_answers"] if c in labels) + "です。"
    if q["explanation"]:
        ans += f" 解説。{_speakable(q['explanation'])}"
    return question_audio, ans


def _crop_region(pdf: pymupdf.Document, q: dict, next_q: dict | None, out_dir: Path, qid: str) -> dict | None:
    """図が画像として取れない（スキャン等）場合、問題の範囲をページから切り出す。"""
    page = pdf[q["page"] - 1]
    y1 = next_q["y"] if next_q and next_q["page"] == q["page"] else page.rect.height - 30
    clip = pymupdf.Rect(0, max(0, q["y"] - 6), page.rect.width, y1)
    if clip.height < 20:
        return None
    name = f"{qid}_region.png"
    (out_dir / "images").mkdir(parents=True, exist_ok=True)
    page.get_pixmap(dpi=150, clip=clip).save(out_dir / "images" / name)
    return {"path": f"images/{name}", "page": q["page"], "required": True, "kind": "page_region"}


def build_book(parsed: dict, *, book_id: str, title: str, version: str = "1.0",
               pdf_path: str | Path | None = None, out_dir: str | Path = ".",
               ocr_requires_review: bool = True, previous: dict | None = None,
               expected_question_count: int | None = None) -> dict:
    out_dir = Path(out_dir)
    pdf = pymupdf.open(pdf_path) if pdf_path else None
    prev_by_id = {q["id"]: q for q in (previous or {}).get("questions", [])}
    questions = []
    pq = parsed["questions"]
    for i, q in enumerate(pq):
        # 章ごとに番号を振る本（--chapter-pages）は「章×1000＋問番号」にして、取りこぼしが後で見つかってもIDがずれないようにする
        qid = f"{book_id}-Q{q['chapter_no'] * 1000 + q['number']:04d}" if q.get("chapter_no") else f"{book_id}-Q{i + 1:04d}"
        issues = list(q["issues"])
        qtype = _question_type(q)
        options = [{"id": o["id"], "label": o["label"], "text": o["text"]} for o in q["options"]]
        correct: list[str] = []
        if qtype == "true_false":
            options = [{"id": "T", "label": "○", "text": "正しい"}, {"id": "F", "label": "×", "text": "誤り"}]
            for t in q["answer_tokens"]:
                correct.append("T" if t in TF_TRUE else "F" if t in TF_FALSE else t)
        else:
            for t in q["answer_tokens"]:
                cid = _token_to_id(t, q["option_family"])
                if cid is None:
                    issues.append({"code": "ANSWER_UNMAPPED", "level": "error", "message": f"解答記号「{t}」を選択肢に対応付けられません"})
                else:
                    correct.append(cid)
        if q["answer_raw"] is not None and not correct and q["numeric_answer"] is None:
            issues.append({"code": "ANSWER_UNREADABLE", "level": "error", "message": f"解答「{q['answer_raw']}」を読み取れません"})

        images = [{"path": im["path"], "page": im["page"], "required": True, "kind": "embedded"} for im in q["images"]]
        if not images and FIGURE_HINT.search(q["question"]) and pdf is not None:
            nxt = pq[i + 1] if i + 1 < len(pq) else None
            reg = _crop_region(pdf, q, nxt, out_dir, qid)
            if reg:
                images.append(reg)
                issues.append({"code": "FIGURE_AUTO_CROPPED", "level": "warning",
                               "message": "図を画像として取得できなかったため、ページの該当範囲を切り出しました"})
        if q["ocr"] and ocr_requires_review:
            issues.append({"code": "OCR_SOURCE", "level": "review", "message": "OCRで読み取った問題のため、原本との照合が必要です"})

        if q.get("ai"):
            issues.append({"code": "AI_ASSISTED", "level": "review", "message": "生成AIで問題文・選択肢を整形したため、原本との照合が必要です"})

        item = {
            "id": qid,
            "chapter": q["chapter"],
            "category": q["category"],
            "difficulty": None,
            "question_type": qtype,
            "question": q["question"],
            "options": options,
            "correct_answers": correct,
            "numeric_answer": q["numeric_answer"],
            "explanation": "\n".join(q["explanation_lines"]).strip(),
            "images": images,
            "source": {
                "page": q["page"],
                "question_number": q["number"],
                "answer_page": q["answer_page"],
                "answer_source": q.get("answer_source", "answer_page"),
                "raw_text": "\n".join(q["raw_lines"]),
                "extraction": "ai_assisted" if q.get("ai") else "ocr" if q["ocr"] else "text",
            },
            "tags": [t for t in [q["category"]] if t],
            "validation_status": "pending",
            "validation_issues": issues,
            "validation_history": [],
        }
        item["audio_text"], item["audio_answer_text"] = make_audio_texts(item)
        item["content_hash"] = content_hash(item)
        prev = prev_by_id.get(qid)
        if prev:  # 人の確認状態と履歴を引き継ぐ（内容が変わっていれば validate で pending に戻る）
            item["validation_history"] = prev.get("validation_history", [])
            if prev.get("validation_status") in ("verified", "rejected"):
                item["validation_status"] = prev["validation_status"]
                item["verified_hash"] = prev.get("verified_hash")
        questions.append(item)

    return {
        "book_id": book_id,
        "book_title": title,
        "version": version,
        "source_pdf": parsed["source_pdf"],
        "generated_at": _now(),
        "expected_question_count": expected_question_count,
        "answers_count": parsed.get("answers_count"),
        "exam_policy": {"allowed_statuses": ["verified", "auto_ok"]},
        "book_issues": parsed["issues"],
        "questions": questions,
    }


def build_file(parsed_path, out_path, **kw) -> dict:
    parsed = json.loads(Path(parsed_path).read_text(encoding="utf-8"))
    out_path = Path(out_path)
    previous = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else None
    book = build_book(parsed, out_dir=out_path.parent, previous=previous, **kw)
    out_path.write_text(json.dumps(book, ensure_ascii=False, indent=1), encoding="utf-8")
    return book
