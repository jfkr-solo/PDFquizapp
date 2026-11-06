// 学習履歴の保存先。端末内（localStorage）に必ず保存し、Supabaseが設定されていれば lib/sync.ts で同期する。
import type { AnswerLog, Session } from "./types";

export interface HistoryStore {
  logs(bookId: string): AnswerLog[];
  setLogs(bookId: string, logs: AnswerLog[]): void;
  addLog(log: Omit<AnswerLog, "id"> & { id?: string }): AnswerLog;
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

export function newId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}

/** 古い版（idなし）で保存した履歴にidを振る */
function withIds(logs: AnswerLog[]): AnswerLog[] {
  return logs.map((l) => (l.id ? l : { ...l, id: newId() }));
}

export const localStore: HistoryStore = {
  logs: (bookId) => withIds(read<AnswerLog[]>(LOGS + bookId, [])),
  setLogs: (bookId, logs) => write(LOGS + bookId, logs),
  addLog: (log) => {
    const full: AnswerLog = { ...log, id: log.id ?? newId(), synced: false };
    write(LOGS + log.bookId, [...localStore.logs(log.bookId), full]);
    return full;
  },
  session: (bookId) => read<Session | null>(SESSION + bookId, null),
  saveSession: (s) => write(SESSION + s.bookId, { ...s, updatedAt: new Date().toISOString() }),
  clearSession: (bookId) => {
    try {
      window.localStorage.removeItem(SESSION + bookId);
    } catch {
      /* noop */
    }
  },
};
