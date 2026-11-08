"""PDFを使わず、書き起こした（または独自に作成した）問題のJSONLから問題集を作る。

1行1問の形式:
  {"chapter": "第1章 …", "number": 1, "category": "…", "difficulty": 2,
   "question": "…", "options": ["…", "…", "…", "…"], "answers": ["B"], "explanation": "正解はB。…"}

- 問題IDは「章の出現順×1000＋number」（2つ目の章の第5問 → <ID>-Q2005）。
- 正解が2つ以上なら複数選択、1つなら単一選択。
- 原本との照合ができないため、すべての問題に AUTHORED（要確認）を付ける。人が内容を確認して verify するまで出題されない。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .build_json import make_audio_texts

LABELS = "ABCDEFGH"


class AuthoredError(ValueError):
    pass


def load_authored(path: str | Path) -> list[dict]:
    rows = []
    for no, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError as e:
            raise AuthoredError(f"{path} の{no}行目がJSONとして読めません: {e}") from e
        for k in ("chapter", "number", "question", "options", "answers"):
            if k not in r:
                raise AuthoredError(f"{path} の{no}行目に {k} がありません")
        if not 2 <= len(r["options"]) <= len(LABELS):
            raise AuthoredError(f"{path} の{no}行目: 選択肢は2〜{len(LABELS)}個にしてください")
        rows.append(r)
    if not rows:
        raise AuthoredError(f"{path} に問題がありません")
    return rows


def build_authored_book(rows: list[dict], *, book_id: str, title: str, version: str = "1.0",
                        note: str = "独自に作成した問題のため、内容の確認が必要です") -> dict:
    chapters: list[str] = []
    questions = []
    for r in rows:
        if r["chapter"] not in chapters:
            chapters.append(r["chapter"])
        ch_no = chapters.index(r["chapter"]) + 1
        opts = [{"id": LABELS[i], "label": LABELS[i], "text": t} for i, t in enumerate(r["options"])]
        q = {
            "id": f"{book_id}-Q{ch_no * 1000 + int(r['number']):04d}",
            "chapter": r["chapter"],
            "category": r.get("category", ""),
            "difficulty": r.get("difficulty"),
            "question_type": "multiple_choice" if len(r["answers"]) > 1 else "single_choice",
            "question": r["question"],
            "options": opts,
            "correct_answers": list(r["answers"]),
            "numeric_answer": None,
            "explanation": r.get("explanation", ""),
            "images": [],
            "source": {"page": 1, "question_number": int(r["number"]), "answer_page": None, "extraction": "manual"},
            "tags": list(r.get("tags", [])),
            "validation_status": "pending",
            "validation_issues": [{"code": "AUTHORED", "level": "review", "message": note}],
        }
        q["audio_text"], q["audio_answer_text"] = make_audio_texts(q)
        questions.append(q)
    return {
        "book_id": book_id,
        "book_title": title,
        "version": version,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "expected_question_count": len(questions),
        "answers_count": len(questions),
        "exam_policy": {"allowed_statuses": ["verified", "auto_ok"]},
        "book_issues": [],
        "questions": questions,
    }


def merge_review_state(new: dict, old: dict | None) -> dict:
    """作り直しても、内容が変わっていない問題の verified / rejected と履歴は引き継ぐ。"""
    if not old:
        return new
    prev = {q["id"]: q for q in old.get("questions", [])}
    for q in new["questions"]:
        p = prev.get(q["id"])
        if p:
            q["validation_status"] = p.get("validation_status", "pending")
            q["verified_hash"] = p.get("verified_hash")
            q["validation_history"] = p.get("validation_history", [])
    return new
