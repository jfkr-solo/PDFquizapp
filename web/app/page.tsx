"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { loadIndex } from "@/lib/data";
import { localStore } from "@/lib/storage";
import type { BookIndexEntry } from "@/lib/types";

export default function Home() {
  const [books, setBooks] = useState<BookIndexEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadIndex().then(setBooks).catch((e) => setError(String(e.message ?? e)));
  }, []);

  return (
    <>
      <h1>問題集を選ぶ</h1>
      {error && <div className="card">{error}</div>}
      {!books && !error && <p className="muted">読み込み中…</p>}
      {books?.length === 0 && (
        <div className="card">
          問題集がまだありません。パイプラインで変換したあと <code>npm run sync-books</code> を実行してください。
        </div>
      )}
      {books?.map((b) => {
        const answered = new Set(localStore.logs(b.book_id).map((l) => l.questionId)).size;
        const pct = b.ready_count ? Math.min(100, Math.round((answered / b.ready_count) * 100)) : 0;
        return (
          <Link key={b.book_id} href={`/book/?id=${encodeURIComponent(b.book_id)}`} className="card" style={{ display: "block", textDecoration: "none", color: "inherit" }}>
            <div className="spread">
              <strong>{b.book_title}</strong>
              <span className="muted">v{b.version}</span>
            </div>
            <div className="muted">
              出題できる問題 {b.ready_count}問 / 全{b.question_count}問
              {b.question_count > b.ready_count && <span className="badge warn" style={{ marginLeft: 8 }}>要確認 {b.question_count - b.ready_count}問</span>}
            </div>
            <div className="progress" style={{ marginTop: 10 }} aria-label={`学習進捗 ${pct}%`}>
              <div style={{ width: `${pct}%` }} />
            </div>
            <div className="muted" style={{ marginTop: 4 }}>解いた問題 {answered}問（{pct}%）</div>
          </Link>
        );
      })}
    </>
  );
}
