// 問題集の読み込み。サイトに同梱した問題集（public/books/）に加えて、Supabase に取り込んだ問題集を
// ログイン中だけ読む。市販の問題集はサイトに同梱せず Supabase に置けば、URL を知っていても中身は見られない。
import { supabase } from "./supabase";
import type { Book, BookIndexEntry, Question, ValidationStatus } from "./types";

export const bookBase = (id: string) => `/books/${encodeURIComponent(id)}`;
const READY: ValidationStatus[] = ["verified", "auto_ok"];
const PAGE = 1000; // Supabase が1回に返す行数の上限

async function staticIndex(): Promise<BookIndexEntry[]> {
  const r = await fetch("/books/index.json", { cache: "no-store" });
  if (r.status === 404) return [];
  if (!r.ok) throw new Error("問題集の一覧を読み込めませんでした");
  return r.json();
}

/** ログイン中なら Supabase のクライアント、そうでなければ null */
async function signedIn() {
  const sb = supabase();
  if (!sb) return null;
  const { data } = await sb.auth.getSession();
  return data.session ? sb : null;
}

async function remoteIndex(): Promise<BookIndexEntry[]> {
  const sb = await signedIn();
  if (!sb) return [];
  const { data: books, error } = await sb.from("books").select("book_id,title,current_version").order("book_id");
  if (error) throw new Error(`Supabase の問題集一覧を読み込めませんでした: ${error.message}`);
  const out: BookIndexEntry[] = [];
  for (const b of books ?? []) {
    const { data: rows, error: e2 } = await sb.from("questions").select("validation_status")
      .eq("book_id", b.book_id).eq("version", b.current_version).limit(100000);
    if (e2) throw new Error(`Supabase の問題集「${b.book_id}」を読み込めませんでした: ${e2.message}`);
    out.push({
      book_id: b.book_id, book_title: b.title, version: b.current_version,
      question_count: rows?.length ?? 0,
      ready_count: (rows ?? []).filter((r) => READY.includes(r.validation_status)).length,
    });
  }
  return out;
}

export async function loadIndex(): Promise<BookIndexEntry[]> {
  const [local, remote] = await Promise.all([staticIndex(), remoteIndex()]);
  const ids = new Set(local.map((b) => b.book_id));
  return [...local, ...remote.filter((b) => !ids.has(b.book_id))];
}

async function remoteBook(id: string): Promise<Book | null> {
  const sb = await signedIn();
  if (!sb) return null;
  const { data: b, error } = await sb.from("books").select("book_id,title,current_version").eq("book_id", id).maybeSingle();
  if (error) throw new Error(`Supabase の問題集「${id}」を読み込めませんでした: ${error.message}`);
  if (!b) return null;
  const questions: Question[] = [];
  for (let from = 0; ; from += PAGE) {
    const { data, error: e2 } = await sb.from("questions").select("body")
      .eq("book_id", id).eq("version", b.current_version).order("id").range(from, from + PAGE - 1);
    if (e2) throw new Error(`Supabase の問題集「${id}」を読み込めませんでした: ${e2.message}`);
    questions.push(...(data ?? []).map((r) => r.body as Question));
    if (!data || data.length < PAGE) break;
  }
  return { book_id: b.book_id, book_title: b.title, version: b.current_version, questions };
}

export async function loadBook(id: string): Promise<Book> {
  const r = await fetch(`${bookBase(id)}/book.json`, { cache: "no-store" });
  if (r.ok) return r.json();
  const remote = await remoteBook(id);
  if (remote) return remote;
  throw new Error(supabase() && !(await signedIn())
    ? `問題集「${id}」を読むにはログインしてください`
    : `問題集「${id}」を読み込めませんでした`);
}
