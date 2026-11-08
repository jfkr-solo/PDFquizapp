"""PDFを使わず、問題のJSONLから問題集を作る（cli import）のテスト。"""
from __future__ import annotations

import json

import pytest

from pipeline import cli

ROWS = [
    {"chapter": "第1章 基礎", "number": 1, "category": "しくみ", "difficulty": 1, "question": "生成AIの説明として正しいものはどれですか。",
     "options": ["検索結果を返す", "次の語を予測する", "テンプレートを選ぶ", "常にWebを見る"], "answers": ["B"], "explanation": "正解はB。"},
    {"chapter": "第1章 基礎", "number": 2, "question": "正しいものを2つ選びなさい。",
     "options": ["ア", "イ", "ウ", "エ"], "answers": ["A", "C"], "explanation": "正解はAとC。"},
    {"chapter": "第2章 プロンプト", "number": 1, "question": "4要素に含まれるものはどれですか。",
     "options": ["目的", "予算"], "answers": ["A"], "explanation": "正解はA。"},
]


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "DATA", tmp_path / "data")
    src = tmp_path / "q.jsonl"
    src.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in ROWS) + "\n", encoding="utf-8")
    return tmp_path, src


def load(tmp):
    return json.loads((tmp / "data" / "books" / "T1" / "book.json").read_text(encoding="utf-8"))


def test_import_builds_pending_book(data):
    tmp, src = data
    assert cli.main(["import", str(src), "--book-id", "T1", "--title", "テスト"]) == 0
    book = load(tmp)
    qs = book["questions"]
    assert [q["id"] for q in qs] == ["T1-Q1001", "T1-Q1002", "T1-Q2001"]
    assert [q["question_type"] for q in qs] == ["single_choice", "multiple_choice", "single_choice"]
    assert qs[1]["correct_answers"] == ["A", "C"]
    assert "source_pdf" not in book
    # 独自作成の問題は人が確認するまで出題しない
    assert all(q["validation_status"] == "pending" for q in qs)
    assert all(any(i["code"] == "AUTHORED" for i in q["validation_issues"]) for q in qs)
    assert (tmp / "data" / "raw" / "T1" / "authored.jsonl").exists()


def test_reimport_keeps_verified_unless_changed(data):
    tmp, src = data
    cli.main(["import", str(src), "--book-id", "T1", "--title", "テスト"])
    assert cli.main(["verify", "T1", "T1-Q1001", "T1-Q2001", "--by", "koki"]) == 0
    rows = [dict(r) for r in ROWS]
    rows[2]["explanation"] = "正解はA。目的が含まれます。"
    src.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    cli.main(["import", str(src), "--book-id", "T1", "--title", "テスト"])
    st = {q["id"]: q["validation_status"] for q in load(tmp)["questions"]}
    assert st == {"T1-Q1001": "verified", "T1-Q1002": "pending", "T1-Q2001": "pending"}


def test_import_rejects_bad_rows(data, capsys):
    tmp, src = data
    src.write_text('{"chapter": "第1章", "number": 1, "question": "?", "options": ["only"], "answers": ["A"]}\n', encoding="utf-8")
    assert cli.main(["import", str(src), "--book-id", "T1", "--title", "テスト"]) == 2
    assert "選択肢" in capsys.readouterr().err
