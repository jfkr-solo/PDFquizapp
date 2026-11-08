"""STEP 8: 検証済みの教材JSONをSupabaseに取り込む。

  python -m pipeline.cli publish IT001

環境変数（.env には書くが、Gitには入れない）
  SUPABASE_URL               例: https://xxxx.supabase.co
  SUPABASE_SERVICE_ROLE_KEY  取り込み専用。ブラウザには絶対に渡さない

- books / book_versions / questions を upsert（同じIDは上書き）する。
- 元の book.json を非公開バケット book-json に <book_id>/<version>.json として保存する（バックアップ）。
- JSON Schema エラーがある問題集は取り込まない。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

BATCH = 500


class PublishError(Exception):
    pass


def _env(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        raise PublishError(f"環境変数 {name} が設定されていません（.env.example を参照）")
    return v


def _request(method: str, url: str, key: str, body: bytes | None = None, headers: dict | None = None) -> bytes:
    h = {"apikey": key, "Authorization": f"Bearer {key}", **(headers or {})}
    req = urllib.request.Request(url, data=body, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise PublishError(f"{method} {url.split('?')[0]} が失敗しました（HTTP {e.code}）: {e.read().decode(errors='replace')[:300]}") from e
    except urllib.error.URLError as e:
        raise PublishError(f"Supabaseに接続できません: {e.reason}") from e


def _upsert(base: str, key: str, table: str, rows: list[dict], on_conflict: str, request=_request) -> None:
    for i in range(0, len(rows), BATCH):
        request("POST", f"{base}/rest/v1/{table}?on_conflict={on_conflict}", key,
                json.dumps(rows[i:i + BATCH], ensure_ascii=False).encode(),
                {"Content-Type": "application/json", "Prefer": "resolution=merge-duplicates,return=minimal"})


def question_row(book: dict, q: dict) -> dict:
    body = {k: v for k, v in q.items() if k not in ("validation_history",)}
    return {
        "id": q["id"],
        "book_id": book["book_id"],
        "version": book["version"],
        "chapter": q.get("chapter") or None,
        "category": q.get("category") or None,
        "difficulty": q.get("difficulty"),
        "question_type": q["question_type"],
        "validation_status": q["validation_status"],
        "body": body,
    }


def publish_book(book_path: str | Path, *, request=_request) -> dict:
    from .validate import schema_errors

    book = json.loads(Path(book_path).read_text(encoding="utf-8"))
    errs = schema_errors(book)
    if errs:
        raise PublishError(f"JSON Schema エラーが{len(errs)}件あるため取り込みません。先に validate を実行して直してください。")
    base, key = _env("SUPABASE_URL").rstrip("/"), _env("SUPABASE_SERVICE_ROLE_KEY")

    bid, ver = book["book_id"], book["version"]
    json_path = f"{bid}/{ver}.json"
    request("POST", f"{base}/storage/v1/object/book-json/{json_path}", key,
            json.dumps(book, ensure_ascii=False).encode(), {"Content-Type": "application/json", "x-upsert": "true"})
    _upsert(base, key, "books", [{"book_id": bid, "title": book["book_title"], "current_version": ver}], "book_id", request)
    _upsert(base, key, "book_versions", [{
        "book_id": bid, "version": ver, "json_path": json_path,
        "sha256": (book.get("source_pdf") or {}).get("sha256"), "question_count": len(book["questions"]),
    }], "book_id,version", request)
    rows = [question_row(book, q) for q in book["questions"]]
    _upsert(base, key, "questions", rows, "id", request)
    return {"book_id": bid, "version": ver, "questions": len(rows),
            "ready": sum(q["validation_status"] in ("verified", "auto_ok") for q in book["questions"])}


def _dollar(s: str) -> str:
    """SQLのドル引用。中身に区切りが現れない印を選ぶ。"""
    tag = "j"
    while f"${tag}$" in s:
        tag += "j"
    return f"${tag}${s}${tag}$"


def publish_sql(book_path: str | Path, max_bytes: int = 350_000) -> list[str]:
    """publish と同じ取り込みを、Supabase の SQL Editor に貼って実行するSQLにする。
    service_role キーをこの環境に置かずに取り込むときに使う（Storage へのバックアップは行わない）。
    SQL Editor は大きすぎるSQLを実行できないので、1つが max_bytes 程度になるよう問題を分けて、
    番号順に実行する複数のSQLを返す。どれも何回実行しても同じ結果になる。"""
    from .validate import schema_errors

    book = json.loads(Path(book_path).read_text(encoding="utf-8"))
    errs = schema_errors(book)
    if errs:
        raise PublishError(f"JSON Schema エラーが{len(errs)}件あるため取り込みません。先に validate を実行して直してください。")
    bid, ver = book["book_id"], book["version"]
    sha = (book.get("source_pdf") or {}).get("sha256")

    # 問題を max_bytes 程度ずつに分ける
    chunks: list[list[dict]] = [[]]
    size = 0
    for q in book["questions"]:
        row = question_row(book, q)
        n = len(json.dumps(row, ensure_ascii=False).encode())
        if chunks[-1] and size + n > max_bytes:
            chunks.append([])
            size = 0
        chunks[-1].append(row)
        size += n

    total = len(chunks)
    head = f"""insert into public.books (book_id, title, current_version) values ({_dollar(bid)}, {_dollar(book["book_title"])}, {_dollar(ver)})
  on conflict (book_id) do update set title = excluded.title, current_version = excluded.current_version, updated_at = now();

insert into public.book_versions (book_id, version, json_path, sha256, question_count)
  values ({_dollar(bid)}, {_dollar(ver)}, {_dollar(f"{bid}/{ver}.json")}, {_dollar(sha) if sha else "null"}, {len(book["questions"])})
  on conflict (book_id, version) do update set question_count = excluded.question_count;
"""
    ids = json.dumps([q["id"] for q in book["questions"]])
    tail = f"""
-- この版に無くなった問題は消す
delete from public.questions where book_id = {_dollar(bid)} and not (id = any (array(select jsonb_array_elements_text({_dollar(ids)}::jsonb))));
"""
    parts = []
    for k, rows in enumerate(chunks, start=1):
        body = json.dumps(rows, ensure_ascii=False)
        parts.append(f"""-- 問題集 {bid} v{ver} の取り込み {k}/{total}（{len(rows)}問）。1から順に実行してください。何回実行しても大丈夫です。
begin;
{head if k == 1 else ""}
insert into public.questions (id, book_id, version, chapter, category, difficulty, question_type, validation_status, body)
select r.id, r.book_id, r.version, r.chapter, r.category, r.difficulty, r.question_type, r.validation_status, r.body
from jsonb_populate_recordset(null::public.questions, {_dollar(body)}::jsonb) r
on conflict (id) do update set version = excluded.version, body = excluded.body, validation_status = excluded.validation_status,
  chapter = excluded.chapter, category = excluded.category, difficulty = excluded.difficulty, updated_at = now();
{tail if k == total else ""}
commit;

select '{k}/{total}' as part, count(*) as questions, count(*) filter (where validation_status in ('verified', 'auto_ok')) as ready
from public.questions where book_id = {_dollar(bid)};
""")
    return parts
