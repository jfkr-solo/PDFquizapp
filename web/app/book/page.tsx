"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { loadBook } from "@/lib/data";
import { accuracyBy, eligible, isReady, MODE_LABEL, pickQuestions, statsByQuestion } from "@/lib/quiz";
import { localStore } from "@/lib/storage";
import { syncBook, type SyncResult } from "@/lib/sync";
import type { AnswerLog, Book, Mode, Session } from "@/lib/types";

function pct(r: number) {
  return `${Math.round(r * 100)}%`;
}

function BookPage() {
  const id = useSearchParams().get("id") ?? "";
  const router = useRouter();
  const [book, setBook] = useState<Book | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [logs, setLogs] = useState<AnswerLog[]>([]);
  const [session, setSession] = useState<Session | null>(null);
  const [chapter, setChapter] = useState("");
  const [category, setCategory] = useState("");
  const [difficulty, setDifficulty] = useState("");
  const [random, setRandom] = useState(false);
  const [includePending, setIncludePending] = useState(false);
  const [sync, setSync] = useState<SyncResult | null>(null);

  useEffect(() => {
    if (!id) return;
    loadBook(id).then(setBook).catch((e) => setError(String(e.message ?? e)));
    const refresh = () => {
      setLogs(localStore.logs(id));
      const s = localStore.session(id);
      setSession(s && !s.finishedAt ? s : null);
    };
    refresh();
    syncBook(id).then((r) => {
      setSync(r);
      if (r.state === "ok") refresh(); // 他の端末の履歴を反映
    });
  }, [id]);

  const filters = { chapter: chapter || undefined, category: category || undefined, difficulty: difficulty ? Number(difficulty) : undefined };
  const options = useMemo(() => {
    if (!book) return { chapters: [], categories: [], difficulties: [] as number[] };
    const uniq = <T,>(xs: T[]) => [...new Set(xs)].filter((x) => x !== undefined && x !== null && x !== "") as T[];
    return {
      chapters: uniq(book.questions.map((q) => q.chapter)),
      categories: uniq(book.questions.map((q) => q.category)),
      difficulties: uniq(book.questions.map((q) => q.difficulty)).sort() as number[],
    };
  }, [book]);

  if (error) return <div className="card">{error} <Link href="/">一覧へ戻る</Link></div>;
  if (!book) return <p className="muted">読み込み中…</p>;

  const ready = book.questions.filter((q) => isReady(book, q));
  const pendingCount = book.questions.filter((q) => q.validation_status === "pending").length;
  const stats = statsByQuestion(logs);
  const weakCount = pickQuestions(eligible(book, "weak", filters), "weak", logs).length;
  const reviewCount = pickQuestions(eligible(book, "review", filters), "review", logs).length;
  const normalCount = eligible(book, "normal", { ...filters, includePending }).length;
  const examPool = eligible(book, "exam", filters).length;
  const total = logs.length;
  const correct = logs.filter((l) => l.correct).length;
  const byCategory = accuracyBy(book, logs, "category").sort((a, b) => a.rate - b.rate);
  const byChapter = accuracyBy(book, logs, "chapter").sort((a, b) => a.key.localeCompare(b.key, "ja"));
  const byDifficulty = accuracyBy(book, logs, "difficulty");
  const wrongList = book.questions.filter((q) => {
    const s = stats.get(q.id);
    return s && s.lastCorrect === false;
  });

  const start = (mode: Mode, count?: number) => {
    const p = new URLSearchParams({ book: id, mode });
    if (count) p.set("count", String(count));
    if (filters.chapter) p.set("chapter", filters.chapter);
    if (filters.category) p.set("category", filters.category);
    if (filters.difficulty) p.set("difficulty", String(filters.difficulty));
    if (mode === "normal" && random) p.set("random", "1");
    if (mode === "normal" && includePending) p.set("pending", "1");
    router.push(`/play/?${p}`);
  };

  return (
    <>
      <Link href="/" className="muted">← 問題集一覧</Link>
      <h1>{book.book_title}</h1>
      <div className="muted">
        出題できる問題 {ready.length}問 / 全{book.questions.length}問
        {pendingCount > 0 && <span className="badge warn" style={{ marginLeft: 8 }}>要確認 {pendingCount}問は模擬試験に出ません</span>}
      </div>

      {sync?.state === "ok" && <div className="muted">履歴をクラウドと同期しました</div>}
      {sync?.state === "error" && <div className="badge warn">{sync.message}</div>}

      {session && (
        <div className="card">
          <div className="spread">
            <div>
              <strong>続きから</strong>
              <div className="muted">{MODE_LABEL[session.mode]}・{session.cursor}/{session.questionIds.length}問まで回答</div>
            </div>
            <Link className="btn primary" href={`/play/?book=${encodeURIComponent(id)}&resume=1`}>再開</Link>
          </div>
        </div>
      )}

      <h2>出題範囲</h2>
      <div className="card">
        <div className="grid2">
          <label className="field">章
            <select value={chapter} onChange={(e) => setChapter(e.target.value)}>
              <option value="">すべて</option>
              {options.chapters.map((c) => <option key={c}>{c}</option>)}
            </select>
          </label>
          <label className="field">分野
            <select value={category} onChange={(e) => setCategory(e.target.value)}>
              <option value="">すべて</option>
              {options.categories.map((c) => <option key={c}>{c}</option>)}
            </select>
          </label>
        </div>
        {options.difficulties.length > 0 && (
          <label className="field">難易度
            <select value={difficulty} onChange={(e) => setDifficulty(e.target.value)}>
              <option value="">すべて</option>
              {options.difficulties.map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
          </label>
        )}
      </div>

      <h2>学習モード</h2>
      <div className="card">
        <div className="spread"><strong>通常学習</strong><span className="muted">{normalCount}問</span></div>
        <div className="muted">1問ずつ解いて、すぐに解説を読みます。</div>
        <label className="check"><input type="checkbox" checked={random} onChange={(e) => setRandom(e.target.checked)} />ランダムな順番で出す</label>
        {pendingCount > 0 && (
          <label className="check"><input type="checkbox" checked={includePending} onChange={(e) => setIncludePending(e.target.checked)} />要確認の問題も含める（正解が原本と未照合）</label>
        )}
        <button className="btn primary block" disabled={!normalCount} onClick={() => start("normal")}>通常学習を始める</button>
      </div>
      <div className="card">
        <div className="spread"><strong>模擬試験</strong><span className="muted">出題できる {examPool}問からランダム</span></div>
        <div className="muted">最後にまとめて採点します。要確認の問題は出ません。</div>
        <div className="row" style={{ marginTop: 8 }}>
          {examPool === 0 && <button className="btn" style={{ flex: 1 }} disabled>出題できる問題がありません</button>}
          {[20, 50, 100].filter((n) => n < examPool).map((n) => (
            <button key={n} className="btn" style={{ flex: 1 }} onClick={() => start("exam", n)}>{n}問</button>
          ))}
          {examPool > 0 && examPool <= 100 && (
            <button className="btn" style={{ flex: 1 }} onClick={() => start("exam", examPool)}>全{examPool}問</button>
          )}
        </div>
      </div>
      <div className="grid2">
        <div className="card">
          <strong>弱点克服</strong>
          <div className="muted">間違えた {weakCount}問を正答率の低い順に</div>
          <button className="btn block" style={{ marginTop: 8 }} disabled={!weakCount} onClick={() => start("weak")}>始める</button>
        </div>
        <div className="card">
          <strong>復習</strong>
          <div className="muted">解いた {reviewCount}問を前回不正解から</div>
          <button className="btn block" style={{ marginTop: 8 }} disabled={!reviewCount} onClick={() => start("review")}>始める</button>
        </div>
      </div>

      <h2>学習の記録</h2>
      <div className="card">
        {total === 0 ? (
          <div className="muted">まだ回答がありません。</div>
        ) : (
          <>
            <div className="spread">
              <div><div className="muted">全体の正答率</div><div className="big">{pct(correct / total)}</div></div>
              <div className="muted" style={{ textAlign: "right" }}>回答 {total}回<br />解いた問題 {stats.size}/{ready.length}問</div>
            </div>
            {byCategory.length > 0 && <h2>苦手分野ランキング</h2>}
            {byCategory.map((a, i) => <Bar key={a.key} label={`${i + 1}. ${a.key}`} rate={a.rate} n={a.attempts} />)}
            {byChapter.length > 1 && <h2>章別</h2>}
            {byChapter.length > 1 && byChapter.map((a) => <Bar key={a.key} label={a.key} rate={a.rate} n={a.attempts} />)}
            {byDifficulty.length > 1 && <h2>難易度別</h2>}
            {byDifficulty.length > 1 && byDifficulty.map((a) => <Bar key={a.key} label={`難易度 ${a.key}`} rate={a.rate} n={a.attempts} />)}
            {wrongList.length > 0 && (
              <details>
                <summary>前回間違えた問題（{wrongList.length}問）</summary>
                <ul>
                  {wrongList.map((q) => (
                    <li key={q.id}>問{q.source.question_number}（{q.chapter}）{q.question.slice(0, 40)}</li>
                  ))}
                </ul>
              </details>
            )}
          </>
        )}
      </div>
    </>
  );
}

function Bar({ label, rate, n }: { label: string; rate: number; n: number }) {
  return (
    <div className="bar" title={`${n}回回答`}>
      <span>{label}</span>
      <div className="track"><div style={{ width: pct(rate) }} /></div>
      <span>{pct(rate)}</span>
    </div>
  );
}

export default function Page() {
  return (
    <Suspense fallback={<p className="muted">読み込み中…</p>}>
      <BookPage />
    </Suspense>
  );
}
