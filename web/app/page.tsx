"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import Account from "@/components/Account";
import { loadIndex } from "@/lib/data";
import { supabase } from "@/lib/supabase";
import { localStore } from "@/lib/storage";
import type { BookIndexEntry } from "@/lib/types";

export default function Home() {
  const [books, setBooks] = useState<BookIndexEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = () => loadIndex().then((b) => { setBooks(b); setError(null); }).catch((e) => setError(String(e.message ?? e)));
    load();
    // ログイン・ログアウトで、Supabase に置いた問題集が見える・見えないが変わる
    const sub = supabase()?.auth.onAuthStateChange((e) => { if (e === "SIGNED_IN" || e === "SIGNED_OUT") load(); });
    return () => sub?.data.subscription.unsubscribe();
  }, []);

  return (
    <>
      <h1>問題集を選ぶ</h1>
      <Account />
      {error && <div className="card">{error}</div>}
      {!books && !error && <p className="muted">読み込み中…</p>}
      {books?.length === 0 && (
        <div className="card">
          {supabase()
            ? "問題集はログインすると表示されます。"
            : <>問題集がまだありません。パイプラインで変換したあと <code>npm run sync-books</code> を実行してください。</>}
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
