// 音声学習モード：問題を読む → 考える時間 → 正解・解説を読む、を順に流す。
// MP3（パイプラインの STEP 9 で作成）があればそれを再生し、無ければブラウザの読み上げ（Web Speech API）を使う。
import { bookBase } from "./data";
import { isReady } from "./quiz";
import type { AudioManifest, Book, Question } from "./types";

export const RATES = [0.75, 1, 1.25, 1.5, 2];
export const PAUSES = [0, 3, 5, 10];

export interface ListenFilters { chapter?: string; category?: string; includePending?: boolean }

/** 聞く問題の順番。出題できる問題だけ（要確認は includePending のときだけ、除外は出さない）。原本の順。 */
export function listenQueue(book: Book, f: ListenFilters = {}): Question[] {
  return book.questions.filter((q) => {
    if (q.validation_status === "rejected") return false;
    if (!isReady(book, q) && !(f.includePending && q.validation_status === "pending")) return false;
    if (f.chapter && q.chapter !== f.chapter) return false;
    if (f.category && q.category !== f.category) return false;
    return true;
  });
}

export type Part = "question" | "answer";

/** 再生するもの。MP3 のURL か、読み上げる文章。 */
export function source(book: Book, q: Question, part: Part): { src?: string; text: string } {
  const text = part === "question" ? q.audio_text : q.audio_answer_text || "正解は登録されていません。";
  const file = q.audio?.[part];
  return file ? { src: `${bookBase(book.book_id)}/${file}`, text } : { text };
}

export async function loadManifest(bookId: string): Promise<AudioManifest | null> {
  try {
    const r = await fetch(`${bookBase(bookId)}/audio/manifest.json`, { cache: "no-store" });
    return r.ok ? await r.json() : null;
  } catch {
    return null;
  }
}

export const speechAvailable = () => typeof window !== "undefined" && "speechSynthesis" in window;

function abortError() {
  return new DOMException("中断しました", "AbortError");
}

/** 1つ再生して終わるまで待つ。signal で止める。 */
export function play(item: { src?: string; text: string }, rate: number, signal: AbortSignal, audio: HTMLAudioElement): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(abortError());
    if (item.src) {
      const done = () => { cleanup(); resolve(); };
      const fail = () => { cleanup(); reject(new Error("音声ファイルを再生できませんでした")); };
      const stop = () => { cleanup(); audio.pause(); reject(abortError()); };
      const cleanup = () => {
        audio.removeEventListener("ended", done);
        audio.removeEventListener("error", fail);
        signal.removeEventListener("abort", stop);
      };
      audio.addEventListener("ended", done);
      audio.addEventListener("error", fail);
      signal.addEventListener("abort", stop);
      audio.src = item.src;
      audio.playbackRate = rate;
      audio.play().catch(fail);
      return;
    }
    if (!speechAvailable()) return reject(new Error("この端末では読み上げを使えません"));
    const u = new SpeechSynthesisUtterance(item.text);
    u.lang = "ja-JP";
    u.rate = rate;
    const stop = () => { speechSynthesis.cancel(); reject(abortError()); };
    u.onend = () => { signal.removeEventListener("abort", stop); resolve(); };
    u.onerror = (e) => { signal.removeEventListener("abort", stop); if (e.error === "interrupted" || e.error === "canceled") reject(abortError()); else reject(new Error("読み上げに失敗しました")); };
    signal.addEventListener("abort", stop);
    speechSynthesis.cancel();
    speechSynthesis.speak(u);
  });
}

export function wait(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(abortError());
    const t = setTimeout(() => { signal.removeEventListener("abort", stop); resolve(); }, ms);
    const stop = () => { clearTimeout(t); reject(abortError()); };
    signal.addEventListener("abort", stop);
  });
}

export const isAbort = (e: unknown) => e instanceof DOMException && e.name === "AbortError";
