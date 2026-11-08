"""STEP 8: Supabase取り込みのテスト（HTTPは偽物に差し替え）"""
import json

import pytest

from pipeline.build_json import build_book
from pipeline.extract import extract_pdf
from pipeline.parse import parse_pages
from pipeline.supabase_import import PublishError, publish_book
from pipeline.validate import validate_book
from tests.make_sample_pdf import make_text_pdf


@pytest.fixture
def book_file(tmp_path):
    make_text_pdf(tmp_path / "s.pdf")
    pages = extract_pdf(tmp_path / "s.pdf", tmp_path)
    book = validate_book(build_book(parse_pages(pages), book_id="T01", title="テスト", pdf_path=tmp_path / "s.pdf", out_dir=tmp_path),
                         book_dir=tmp_path, pages_json=pages)["book"]
    p = tmp_path / "book.json"
    p.write_text(json.dumps(book, ensure_ascii=False), encoding="utf-8")
    return p


def test_publish_sends_books_versions_questions_and_backup(book_file, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co/")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    calls = []
    r = publish_book(book_file, request=lambda m, url, key, body=None, headers=None: calls.append((m, url, key, body, headers)) or b"")
    urls = [c[1] for c in calls]
    assert urls[0] == "https://example.supabase.co/storage/v1/object/book-json/T01/1.0.json"
    assert any("/rest/v1/books?on_conflict=book_id" in u for u in urls)
    assert any("/rest/v1/book_versions?on_conflict=book_id,version" in u for u in urls)
    q_call = [c for c in calls if "/rest/v1/questions" in c[1]][0]
    rows = json.loads(q_call[3])
    assert len(rows) == 6 and rows[0]["id"] == "T01-Q0001" and rows[0]["body"]["correct_answers"] == ["C"]
    assert "validation_history" not in rows[0]["body"]
    assert all(c[2] == "service-key" for c in calls)
    assert "merge-duplicates" in q_call[4]["Prefer"]
    assert r == {"book_id": "T01", "version": "1.0", "questions": 6, "ready": 6}


def test_publish_requires_env(book_file, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    with pytest.raises(PublishError, match="SUPABASE_URL"):
        publish_book(book_file, request=lambda *a, **k: b"")


def test_publish_refuses_schema_errors(book_file, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "k")
    b = json.loads(book_file.read_text(encoding="utf-8"))
    b["questions"][0]["question_type"] = "essay"
    book_file.write_text(json.dumps(b, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(PublishError, match="JSON Schema"):
        publish_book(book_file, request=lambda *a, **k: b"")


def test_publish_sql_writes_idempotent_import(book_file):
    """service_role キーを使わずに SQL Editor で取り込むためのSQL。大きければ分け、どれも何回実行しても同じ結果になる形にする。"""
    from pipeline.supabase_import import publish_sql
    book = json.loads(book_file.read_text(encoding="utf-8"))
    book["questions"][0]["explanation"] = "区切り $j$ を含む解説"
    book_file.write_text(json.dumps(book, ensure_ascii=False), encoding="utf-8")
    [sql] = publish_sql(book_file)
    assert "on conflict (book_id) do update" in sql and "on conflict (id) do update" in sql
    assert "delete from public.questions where book_id = $j$T01$j$" in sql
    assert "$jj$[" in sql  # 中身に $j$ があれば、別の区切りを使う
    rows = json.loads(sql.split("$jj$")[1])
    assert [r["id"] for r in rows] == [q["id"] for q in book["questions"]]
    assert "SERVICE_ROLE" not in sql.upper()

    parts = publish_sql(book_file, max_bytes=1)  # 1問ずつに分かれる
    assert len(parts) == len(book["questions"])
    assert "insert into public.books" in parts[0] and all("insert into public.books" not in p for p in parts[1:])
    assert "delete from public.questions" in parts[-1] and all("delete from" not in p for p in parts[:-1])
