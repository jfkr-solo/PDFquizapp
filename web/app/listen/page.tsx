"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { isAbort, listenQueue, PAUSES, play, RATES, source, speechAvailable, wait } from "@/lib/audio";
import { loadBook } from "@/lib/data";
import { correctAnswerText } from "@/lib/quiz";
import type { Book } from "@/lib/types";

type Phase = "idle" | "question" | "pause" | "answer";
const PHASE_LABEL: Record<Phase, string> = { idle: "停止中", question: "問題を読んでいます", pause: "考える時間", answer: "正解と解説" };
const PREF_KEY = "pdfquiz:listen-prefs";

function loadPrefs(): { rate: number; pause: number } {
  try {
    const p = JSON.parse(localStorage.getItem(PREF_KEY) ?? "{}");
    return { rate: RATES.includes(p.rate) ? p.rate : 1, pause: PAUSES.includes(p.pause) ? p.pause : 5 };
  } catch {
    return { rate: 1, pause: 5 };
  }
}

function Listen() {
  const params = useSearchParams();
  const bookId = params.get("book") ?? "";
  const chapter = params.get("chapter") || undefined;
  const category = params.get("category") || undefined;
  const includePending = params.get("pending") === "1";
  const [book, setBook] = useState<Book | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [index, setIndex] = useState(0);
  const [phase, setPhase] = useState<Phase>("idle");
  const [playing, setPlaying] = useState(false);
  const [rate, setRate] = useState(1);
  const [pause, setPause] = useState(5);
  const [auto, setAuto] = useState(true);
  const [showAnswer, setShowAnswer] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const ctrl = useRef<AbortController | null>(null);
  const settings = useRef({ rate, pause, auto });
  settings.current = { rate, pause, auto };

  useEffect(() => {
    const p = loadPrefs();
    setRate(p.rate);
    setPause(p.pause);
    if (bookId) loadBook(bookId).then(setBook).catch((e) => setError(String(e.message ?? e)));
    return () => ctrl.current?.abort();
  }, [bookId]);

  useEffect(() => {
    try { localStorage.setItem(PREF_KEY, JSON.stringify({ rate, pause })); } catch { /* 保存できなくても再生はできる */ }
    if (audioRef.current) audioRef.current.playbackRate = rate;
  }, [rate, pause]);

  const queue = useMemo(() => (book ? listenQueue(book, { chapter, category, includePending }) : []), [book, chapter, category, includePending]);

  const stop = () => {
    ctrl.current?.abort();
    ctrl.current = null;
    setPlaying(false);
    setPhase("idle");
  };

  const run = async (from: number) => {
    if (!book) return;
    ctrl.current?.abort();
    const c = new AbortController();
    ctrl.current = c;
    audioRef.current ??= new Audio();
    setPlaying(true);
    setError(null);
    try {
      for (let i = from; i < queue.length; i++) {
        const q = queue[i];
        setIndex(i);
        setShowAnswer(false);
        if ("mediaSession" in navigator) {
          navigator.mediaSession.metadata = new MediaMetadata({ title: `問${q.source.question_number} ${q.question.slice(0, 30)}`, artist: book.book_title, album: q.chapter ?? "" });
        }
        setPhase("question");
        await play(source(book, q, "question"), settings.current.rate, c.signal, audioRef.current);
        setPhase("pause");
        await wait(settings.current.pause * 1000, c.signal);
        setPhase("answer");
        setShowAnswer(true);
        await play(source(book, q, "answer"), settings.current.rate, c.signal, audioRef.current);
        if (!settings.current.auto) break;
        if (i + 1 < queue.length) await wait(1000, c.signal);
      }
      setPlaying(false);
      setPhase("idle");
    } catch (e) {
      if (!isAbort(e)) {
        setError(e instanceof Error ? e.message : String(e));
        setPlaying(false);
        setPhase("idle");
      }
    }
  };

  const go = (i: number) => {
    const n = Math.max(0, Math.min(queue.length - 1, i));
    if (playing) void run(n);
    else { setIndex(n); setShowAnswer(false); }
  };

  if (error && !book) return <div className="card">{error} <Link href="/">一覧へ戻る</Link></div>;
  if (!book) return <p className="muted">読み込み中…</p>;
  const back = `/book/?id=${encodeURIComponent(bookId)}`;
  if (queue.length === 0) return <div className="card">聞ける問題がありません。<Link href={back}>戻る</Link></div>;

  const q = queue[index];
  const usesMp3 = !!q.audio?.question;
  const scope = [chapter, category].filter(Boolean).join("・") || "すべての章";

  return (
    <>
      <div className="spread">
        <Link href={back} className="muted" onClick={stop}>← 問題集に戻る</Link>
        <span className="muted">音声学習　{index + 1} / {queue.length}</span>
      </div>
      <div className="progress" style={{ margin: "8px 0 16px" }}><div style={{ width: `${((index + (phase === "idle" ? 0 : 0.5)) / queue.length) * 100}%` }} /></div>
      <div className="muted">{scope}　{q.chapter} {q.category && `・${q.category}`}　問{q.source.question_number}
        {q.validation_status === "pending" && <span className="badge warn" style={{ marginLeft: 8 }}>要確認</span>}
        <span className="badge" style={{ marginLeft: 8 }}>{usesMp3 ? "音声ファイル" : "端末の読み上げ"}</span>
      </div>

      <div className="card" aria-live="polite">
        <strong>{PHASE_LABEL[phase]}</strong>
        <p className="question">{q.question}</p>
        {q.options.length > 0 && q.question_type !== "true_false" && (
          <ol className="muted" style={{ paddingLeft: 20 }}>
            {q.options.map((o) => <li key={o.id} style={{ listStyle: "none" }}>{o.label ?? o.id}　{o.text}</li>)}
          </ol>
        )}
        {showAnswer ? (
          <div className="feedback good">
            <div><strong>正解：{correctAnswerText(q)}</strong></div>
            <div style={{ marginTop: 8 }}>{q.explanation || <span className="muted">解説はありません</span>}</div>
          </div>
        ) : (
          <button className="btn" onClick={() => setShowAnswer(true)}>正解を表示</button>
        )}
      </div>

      {error && <div className="badge warn">{error}</div>}
      {!usesMp3 && !speechAvailable() && <div className="badge warn">この端末では読み上げを使えません。パイプラインで音声ファイルを作ってください。</div>}

      <div className="card">
        <div className="grid2">
          <label className="field">再生速度
            <select value={rate} onChange={(e) => setRate(Number(e.target.value))}>
              {RATES.map((r) => <option key={r} value={r}>{r}倍</option>)}
            </select>
          </label>
          <label className="field">考える時間
            <select value={pause} onChange={(e) => setPause(Number(e.target.value))}>
              {PAUSES.map((p) => <option key={p} value={p}>{p === 0 ? "なし" : `${p}秒`}</option>)}
            </select>
          </label>
        </div>
        <label className="check"><input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />続けて次の問題を流す</label>
        <div className="muted">解答は記録されません。画面を消して聞き流すときは、問題集ページの「章ごとの音声」が便利です。</div>
      </div>

      <div className="actionbar">
        <div className="inner">
          <button className="btn" disabled={index === 0} onClick={() => go(index - 1)} aria-label="前の問題">前へ</button>
          {playing
            ? <button className="btn primary" onClick={stop}>一時停止</button>
            : <button className="btn primary" onClick={() => run(index)}>{phase === "idle" && index === 0 ? "再生する" : "この問題から再生"}</button>}
          <button className="btn" disabled={index + 1 >= queue.length} onClick={() => go(index + 1)} aria-label="次の問題">次へ</button>
        </div>
      </div>
    </>
  );
}

export default function Page() {
  return (
    <Suspense fallback={<p className="muted">読み込み中…</p>}>
      <Listen />
    </Suspense>
  );
}
