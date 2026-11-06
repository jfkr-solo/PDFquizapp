import type { Book, BookIndexEntry } from "./types";

export const bookBase = (id: string) => `/books/${encodeURIComponent(id)}`;

export async function loadIndex(): Promise<BookIndexEntry[]> {
  const r = await fetch("/books/index.json", { cache: "no-store" });
  if (!r.ok) throw new Error("問題集の一覧を読み込めませんでした");
  return r.json();
}

export async function loadBook(id: string): Promise<Book> {
  const r = await fetch(`${bookBase(id)}/book.json`, { cache: "no-store" });
  if (!r.ok) throw new Error(`問題集「${id}」を読み込めませんでした`);
  return r.json();
}
