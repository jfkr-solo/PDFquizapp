import { describe, expect, it } from "vitest";
import { listenQueue, source } from "@/lib/audio";
import type { Book, Question } from "@/lib/types";

const q = (id: string, over: Partial<Question> = {}): Question => ({
  id, chapter: "第1章", category: "ネットワーク", difficulty: null, question_type: "single_choice",
  question: id, options: [{ id: "A", text: "a" }], correct_answers: ["A"], explanation: "",
  source: { page: 1, question_number: 1 }, audio_text: `問題${id}`, audio_answer_text: `正解${id}`, tags: [], validation_status: "auto_ok", ...over,
});
const book: Book = {
  book_id: "B 1", book_title: "t", version: "1.0",
  questions: [
    q("Q1", { audio: { question: "audio/Q1_q.mp3", answer: "audio/Q1_a.mp3" } }),
    q("Q2", { chapter: "第2章" }),
    q("Q3", { validation_status: "pending" }),
    q("Q4", { validation_status: "rejected" }),
  ],
};

describe("音声学習", () => {
  it("出題できる問題だけを原本の順に並べる", () => {
    expect(listenQueue(book).map((x) => x.id)).toEqual(["Q1", "Q2"]);
    expect(listenQueue(book, { chapter: "第2章" }).map((x) => x.id)).toEqual(["Q2"]);
    expect(listenQueue(book, { includePending: true }).map((x) => x.id)).toEqual(["Q1", "Q2", "Q3"]); // 除外は含めない
  });
  it("MP3があればURL、無ければ読み上げ文章", () => {
    expect(source(book, book.questions[0], "question")).toEqual({ src: "/books/B%201/audio/Q1_q.mp3", text: "問題Q1" });
    expect(source(book, book.questions[1], "answer")).toEqual({ text: "正解Q2" });
    expect(source(book, q("Q9", { audio_answer_text: undefined }), "answer").text).toBe("正解は登録されていません。");
  });
});
