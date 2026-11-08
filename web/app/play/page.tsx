"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { bookBase, loadBook } from "@/lib/data";
import { correctAnswerText, eligible, grade, MODE_LABEL, pickQuestions } from "@/lib/quiz";
import { localStore } from "@/lib/storage";
import { pushLogs, pushSession } from "@/lib/sync";
import type { Book, Mode, Question, Session } from "@/lib/types";

function newSession(book: Book, params: URLSearchParams): Session {
  const mode = (params.get("mode") as Mode) || "normal";
  const filters = {
    chapter: params.get("chapter") || undefined,
    category: params.get("category") || undefined,
    difficulty: params.get("difficulty") ? Number(params.get("difficulty")) : undefined,
    includePending: params.get("pending") === "1",
  };
  const count = params.get("count") ? Number(params.get("count")) : undefined;
  const qs = pickQuestions(eligible(book, mode, filters), mode, localStore.logs(book.book_id), {
    count,
    random: params.get("random") === "1",
  });
  return {
    id: `${Date.now()}`,
    bookId: book.book_id,
    mode,
    questionIds: qs.map((q) => q.id),
    cursor: 0,
    answers: {},
    startedAt: new Date().toISOString(),
  };
}

function Play() {
  const params = useSearchParams();
  const bookId = params.get("book") ?? "";
  const [book, setBook] = useState<Book | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [numeric, setNumeric] = useState("");
  const [revealed, setRevealed] = useState(false);
  const shownAt = useRef(Date.now());

  useEffect(() => {
    if (!bookId) return;
    loadBook(bookId)
      .then((b) => {
        setBook(b);
        const saved = localStore.session(bookId);
        const s = params.get("resume") === "1" && saved && !saved.finishedAt ? saved : newSession(b, new URLSearchParams(params.toString()));
        localStore.saveSession(s);
        setSession(s);
      })
      .catch((e) => setError(String(e.message ?? e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bookId]);

  const byId = useMemo(() => new Map(book?.questions.map((q) => [q.id, q]) ?? []), [book]);
  const q: Question | undefined = session ? byId.get(session.questionIds[session.cursor]) : undefined;

  useEffect(() => {
    setSelected([]);
    setNumeric("");
    setRevealed(false);
    shownAt.current = Date.now();
  }, [session?.cursor]);

  if (error) return <div className="card">{error} <Link href="/">一覧へ戻る</Link></div>;
  if (!book || !session) return <p className="muted">読み込み中…</p>;
  const back = `/book/?id=${encodeURIComponent(bookId)}`;
  if (session.questionIds.length === 0) {
    return (
      <div className="card">
        条件に合う問題がありません。<Link href={back}>戻る</Link>
      </div>
    );
  }
  if (session.finishedAt || !q) return <Result book={book} session={session} back={back} />;

  const isExam = session.mode === "exam";
  const total = session.questionIds.length;
  const answer = q.question_type === "numeric" ? [numeric] : selected;
  const canSubmit = q.question_type === "numeric" ? numeric.trim() !== "" : selected.length > 0;
  const isCorrect = revealed ? grade(q, answer) : false;

  const toggle = (id: string) => {
    if (revealed) return;
    if (q.question_type === "multiple_choice") setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
    else setSelected([id]);
  };

  const submit = () => {
    const correct = grade(q, answer);
    localStore.addLog({
      bookId, questionId: q.id, selected: answer, correct, sessionId: session.id,
      answeredAt: new Date().toISOString(), elapsedMs: Date.now() - shownAt.current, mode: session.mode,
    });
    void pushLogs(bookId); // ログイン中ならSupabaseへ送る（失敗しても端末に残り、次回送信）
    const next: Session = { ...session, answers: { ...session.answers, [q.id]: { selected: answer, correct } } };
    if (isExam) advance(next);
    else {
      setSession(next);
      localStore.saveSession(next);
      void pushSession(next);
      setRevealed(true);
    }
  };

  const advance = (s: Session = session) => {
    const cursor = s.cursor + 1;
    const next: Session = { ...s, cursor, finishedAt: cursor >= s.questionIds.length ? new Date().toISOString() : undefined };
    localStore.saveSession(next);
    void pushSession(next);
    setSession(next);
    window.scrollTo({ top: 0 });
  };

  const optClass = (id: string) => {
    if (!revealed) return selected.includes(id) ? "option selected" : "option";
    if (q.correct_answers.includes(id)) return "option correct";
    if (selected.includes(id)) return "option wrong";
    return "option";
  };

  return (
    <>
      <div className="spread">
        <Link href={back} className="muted">中断して戻る</Link>
        <span className="muted">{MODE_LABEL[session.mode]}　{session.cursor + 1} / {total}</span>
      </div>
      <div className="progress" style={{ margin: "8px 0 16px" }}><div style={{ width: `${(session.cursor / total) * 100}%` }} /></div>

      <div className="muted">
        {q.chapter} {q.category && `・${q.category}`}　問{q.source.question_number}{book.source_pdf && `（原本 p.${q.source.page}）`}
        {q.validation_status === "pending" && <span className="badge warn" style={{ marginLeft: 8 }}>要確認</span>}
        {q.question_type === "multiple_choice" && <span className="badge" style={{ marginLeft: 8 }}>すべて選ぶ</span>}
      </div>
      <p className="question">{q.question}</p>
      {q.images?.map((im) => (
        // eslint-disable-next-line @next/next/no-img-element
        <img key={im.path} className="figure" src={`${bookBase(bookId)}/${im.path}`} alt={`問${q.source.question_number}の図`} />
      ))}

      {q.question_type === "numeric" ? (
        <label className="field" style={{ margin: "16px 0" }}>答え{q.numeric_answer?.unit ? `（単位: ${q.numeric_answer.unit}）` : ""}
          <input type="text" inputMode="decimal" value={numeric} disabled={revealed} onChange={(e) => setNumeric(e.target.value)} placeholder="数値を入力" />
        </label>
      ) : (
        <div className="options" role={q.question_type === "multiple_choice" ? "group" : "radiogroup"}>
          {q.options.map((o) => (
            <button key={o.id} className={optClass(o.id)} onClick={() => toggle(o.id)} aria-pressed={selected.includes(o.id)}>
              <span className="mark">{o.label ?? o.id}</span>
              <span>{o.text}</span>
            </button>
          ))}
        </div>
      )}

      {revealed && (
        <div className={`feedback ${isCorrect ? "good" : "bad"}`} aria-live="polite">
          <strong>{isCorrect ? "正解" : "不正解"}</strong>
          <div>正解：{correctAnswerText(q)}</div>
          {!isCorrect && (
            <div>あなたの回答：{q.question_type === "numeric" ? numeric : selected.map((id) => q.options.find((o) => o.id === id)?.label ?? id).join("、")}</div>
          )}
          <div style={{ marginTop: 8 }}>{q.explanation ? q.explanation : <span className="muted">解説はありません</span>}</div>
        </div>
      )}

      <div className="actionbar">
        <div className="inner">
          {revealed ? (
            <button className="btn primary" onClick={() => advance()}>{session.cursor + 1 >= total ? "結果を見る" : "次の問題へ"}</button>
          ) : (
            <button className="btn primary" disabled={!canSubmit} onClick={submit}>{isExam ? "回答して次へ" : "回答する"}</button>
          )}
        </div>
      </div>
    </>
  );
}

function Result({ book, session, back }: { book: Book; session: Session; back: string }) {
  const byId = new Map(book.questions.map((q) => [q.id, q]));
  const answered = session.questionIds.filter((id) => session.answers[id]);
  const correct = answered.filter((id) => session.answers[id].correct).length;
  const wrong = answered.filter((id) => !session.answers[id].correct).map((id) => byId.get(id)!).filter(Boolean);
  const rate = answered.length ? Math.round((correct / answered.length) * 100) : 0;
  return (
    <>
      <h1>{MODE_LABEL[session.mode]}の結果</h1>
      <div className="card">
        <div className="big">{correct} / {answered.length}問</div>
        <div className="muted">正答率 {rate}%</div>
      </div>
      {wrong.length > 0 && <h2>間違えた問題</h2>}
      {wrong.map((q) => (
        <details key={q.id} className="card">
          <summary>問{q.source.question_number}　{q.question.slice(0, 30)}…</summary>
          <p className="question">{q.question}</p>
          <div>正解：{correctAnswerText(q)}</div>
          <div className="muted" style={{ marginTop: 8 }}>{q.explanation || "解説はありません"}</div>
        </details>
      ))}
      <div className="actionbar">
        <div className="inner">
          <Link className="btn primary" href={back}>問題集に戻る</Link>
        </div>
      </div>
    </>
  );
}

export default function Page() {
  return (
    <Suspense fallback={<p className="muted">読み込み中…</p>}>
      <Play />
    </Suspense>
  );
}
