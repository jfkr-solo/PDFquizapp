// 端末内の履歴とSupabaseの履歴を同期する。オフラインや未ログインでも学習は止めない。
import type { SupabaseClient } from "@supabase/supabase-js";
import { localStore } from "./storage";
import { supabase } from "./supabase";
import type { AnswerLog, Mode, Session } from "./types";

export interface LogRow {
  id: string;
  book_id: string;
  question_id: string;
  session_id: string | null;
  selected: string[];
  is_correct: boolean;
  answered_at: string;
  elapsed_ms: number | null;
  mode: Mode;
}

export const toRow = (l: AnswerLog): LogRow => ({
  id: l.id, book_id: l.bookId, question_id: l.questionId, session_id: l.sessionId ?? null,
  selected: l.selected, is_correct: l.correct, answered_at: l.answeredAt, elapsed_ms: l.elapsedMs, mode: l.mode,
});

export const fromRow = (r: LogRow): AnswerLog => ({
  id: r.id, bookId: r.book_id, questionId: r.question_id, sessionId: r.session_id ?? undefined,
  selected: r.selected, correct: r.is_correct, answeredAt: r.answered_at, elapsedMs: r.elapsed_ms ?? 0, mode: r.mode, synced: true,
});

/** 端末とサーバーの履歴をidで合わせ、回答日時順に並べる */
export function mergeLogs(local: AnswerLog[], remote: AnswerLog[]): AnswerLog[] {
  const byId = new Map<string, AnswerLog>();
  for (const l of local) byId.set(l.id, l);
  for (const r of remote) byId.set(r.id, { ...byId.get(r.id), ...r, synced: true });
  return [...byId.values()].sort((a, b) => a.answeredAt.localeCompare(b.answeredAt));
}

/** 新しい方のセッションを採用（終了済みは再開対象にしない） */
export function newerSession(a: Session | null, b: Session | null): Session | null {
  if (!a) return b;
  if (!b) return a;
  return (a.updatedAt ?? a.startedAt) >= (b.updatedAt ?? b.startedAt) ? a : b;
}

export type SyncResult = { state: "off" | "signed_out" | "ok" | "error"; message?: string };

async function userId(c: SupabaseClient): Promise<string | null> {
  const { data } = await c.auth.getSession();
  return data.session?.user.id ?? null;
}

export async function pushLogs(bookId: string): Promise<SyncResult> {
  const c = supabase();
  if (!c) return { state: "off" };
  if (!(await userId(c))) return { state: "signed_out" };
  const logs = localStore.logs(bookId);
  const pending = logs.filter((l) => !l.synced);
  if (pending.length === 0) return { state: "ok" };
  const { error } = await c.from("answer_logs").upsert(pending.map(toRow), { onConflict: "id", ignoreDuplicates: true });
  if (error) return { state: "error", message: `履歴を送信できませんでした（${error.message}）。次回また送信します。` };
  const sent = new Set(pending.map((l) => l.id));
  localStore.setLogs(bookId, localStore.logs(bookId).map((l) => (sent.has(l.id) ? { ...l, synced: true } : l)));
  return { state: "ok" };
}

export async function pushSession(s: Session): Promise<void> {
  const c = supabase();
  if (!c || !(await userId(c))) return;
  await c.from("study_sessions").upsert({
    id: s.id, book_id: s.bookId, mode: s.mode, question_ids: s.questionIds, cursor: s.cursor,
    answers: s.answers, started_at: s.startedAt, finished_at: s.finishedAt ?? null, updated_at: s.updatedAt ?? new Date().toISOString(),
  }, { onConflict: "user_id,id" });
}

/** 問題集を開いたときに呼ぶ：未送信を送り、他の端末の履歴と途中のセッションを取り込む */
export async function syncBook(bookId: string): Promise<SyncResult> {
  const c = supabase();
  if (!c) return { state: "off" };
  if (!(await userId(c))) return { state: "signed_out" };
  const pushed = await pushLogs(bookId);
  if (pushed.state === "error") return pushed;
  const { data, error } = await c.from("answer_logs")
    .select("id,book_id,question_id,session_id,selected,is_correct,answered_at,elapsed_ms,mode")
    .eq("book_id", bookId).order("answered_at").limit(20000);
  if (error) return { state: "error", message: `履歴を取得できませんでした（${error.message}）` };
  localStore.setLogs(bookId, mergeLogs(localStore.logs(bookId), (data as LogRow[]).map(fromRow)));

  const { data: ss } = await c.from("study_sessions").select("*").eq("book_id", bookId)
    .is("finished_at", null).order("updated_at", { ascending: false }).limit(1);
  const r = ss?.[0];
  if (r) {
    const remote: Session = {
      id: r.id, bookId, mode: r.mode, questionIds: r.question_ids, cursor: r.cursor, answers: r.answers,
      startedAt: r.started_at, updatedAt: r.updated_at,
    };
    const local = localStore.session(bookId);
    if (newerSession(local, remote) === remote) localStore.saveSession(remote);
  }
  return { state: "ok" };
}
