import { afterEach, describe, expect, it, vi } from "vitest";

// Supabase の問い合わせを、テーブルごとの行で置き換える簡単な偽物
const tables: Record<string, Record<string, unknown>[]> = {};
let session: object | null = null;
function query(rows: Record<string, unknown>[]) {
  let r = rows;
  const q = {
    select: () => q, order: () => q, limit: () => q,
    eq: (k: string, v: unknown) => { r = r.filter((x) => x[k] === v); return q; },
    range: (a: number, b: number) => Promise.resolve({ data: r.slice(a, b + 1), error: null }),
    maybeSingle: () => Promise.resolve({ data: r[0] ?? null, error: null }),
    then: (f: (v: unknown) => unknown) => Promise.resolve({ data: r, error: null }).then(f),
  };
  return q;
}
vi.mock("@/lib/supabase", () => ({
  supabase: () => ({ auth: { getSession: async () => ({ data: { session } }) }, from: (t: string) => query(tables[t] ?? []) }),
}));

import { loadBook, loadIndex } from "@/lib/data";

const staticIndex = [{ book_id: "SAMPLE01", book_title: "サンプル", version: "1.0", question_count: 6, ready_count: 6 }];
function serve(files: Record<string, unknown>) {
  vi.stubGlobal("fetch", async (u: string) => (u in files
    ? { ok: true, status: 200, json: async () => files[u] }
    : { ok: false, status: 404, json: async () => ({}) }));
}
tables.books = [{ book_id: "MHM", title: "メンタルヘルス", current_version: "1.0" }];
tables.questions = [
  { book_id: "MHM", version: "1.0", validation_status: "verified", body: { id: "MHM-Q1001" } },
  { book_id: "MHM", version: "1.0", validation_status: "pending", body: { id: "MHM-Q1002" } },
];

describe("問題集の読み込み", () => {
  afterEach(() => { session = null; vi.unstubAllGlobals(); });

  it("ログインしていなければ、Supabase の問題集は一覧にも出ず読めない", async () => {
    serve({ "/books/index.json": staticIndex });
    expect((await loadIndex()).map((b) => b.book_id)).toEqual(["SAMPLE01"]);
    await expect(loadBook("MHM")).rejects.toThrow("ログインしてください");
  });

  it("ログイン中は Supabase の問題集が一覧に加わり、問題を読める", async () => {
    session = { user: {} };
    serve({ "/books/index.json": staticIndex });
    const idx = await loadIndex();
    expect(idx.map((b) => [b.book_id, b.ready_count, b.question_count])).toEqual([["SAMPLE01", 6, 6], ["MHM", 1, 2]]);
    const book = await loadBook("MHM");
    expect(book.book_title).toBe("メンタルヘルス");
    expect(book.questions.map((q) => q.id)).toEqual(["MHM-Q1001", "MHM-Q1002"]);
  });
});
