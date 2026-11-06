// 学習履歴の保存先。STEP 7 はブラウザ（localStorage）、STEP 8 で Supabase 実装に差し替える。
import type { AnswerLog, Session } from "./types";

export interface HistoryStore {
  logs(bookId: string): AnswerLog[];
  addLog(log: AnswerLog): void;
  session(bookId: string): Session | null;
  saveSession(s: Session): void;
  clearSession(bookId: string): void;
}

const LOGS = "pq:logs:";
const SESSION = "pq:session:";

function read<T>(key: string, fallback: T): T {
  try {
    const v = window.localStorage.getItem(key);
    return v ? (JSON.parse(v) as T) : fallback;
  } catch {
    return fallback; // プライベートブラウズ等で使えない場合も画面は動かす
  }
}

function write(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* 保存できなくても学習は続けられる */
  }
}

export const localStore: HistoryStore = {
  logs: (bookId) => read<AnswerLog[]>(LOGS + bookId, []),
  addLog: (log) => write(LOGS + log.bookId, [...read<AnswerLog[]>(LOGS + log.bookId, []), log]),
  session: (bookId) => read<Session | null>(SESSION + bookId, null),
  saveSession: (s) => write(SESSION + s.bookId, s),
  clearSession: (bookId) => {
    try {
      window.localStorage.removeItem(SESSION + bookId);
    } catch {
      /* noop */
    }
  },
};
