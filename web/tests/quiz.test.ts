import { describe, expect, it } from "vitest";
import { accuracyBy, eligible, grade, parseNumber, pickQuestions } from "@/lib/quiz";
import type { AnswerLog, Book, Question } from "@/lib/types";

const q = (id: string, over: Partial<Question> = {}): Question => ({
  id, chapter: "第1章", category: "ネットワーク", difficulty: null, question_type: "single_choice",
  question: id, options: [{ id: "A", text: "a" }, { id: "B", text: "b" }], correct_answers: ["A"],
  explanation: "", source: { page: 1, question_number: 1 }, audio_text: "", tags: [], validation_status: "auto_ok", ...over,
});
const book: Book = {
  book_id: "B", book_title: "t", version: "1.0",
  questions: [
    q("Q1"),
    q("Q2", { question_type: "multiple_choice", correct_answers: ["A", "B"], category: "セキュリティ", chapter: "第2章" }),
    q("Q3", { validation_status: "pending" }),
    q("Q4", { validation_status: "rejected" }),
    q("Q5", { question_type: "numeric", options: [], correct_answers: [], numeric_answer: { value: 12.5, unit: "Mbps", tolerance: 0.1 } }),
  ],
};
const log = (questionId: string, correct: boolean, at: string): AnswerLog =>
  ({ id: `${questionId}-${at}`, bookId: "B", questionId, selected: [], correct, answeredAt: at, elapsedMs: 1000, mode: "normal" });

describe("eligible", () => {
  it("模擬試験には要確認・除外の問題を出さない", () => {
    expect(eligible(book, "exam").map((x) => x.id)).toEqual(["Q1", "Q2", "Q5"]);
    expect(eligible(book, "exam", { includePending: true }).map((x) => x.id)).toEqual(["Q1", "Q2", "Q5"]);
  });
  it("通常学習では要確認を含めることを選べる（除外は常に出さない）", () => {
    expect(eligible(book, "normal", { includePending: true }).map((x) => x.id)).toEqual(["Q1", "Q2", "Q3", "Q5"]);
  });
  it("章・分野で絞り込める", () => {
    expect(eligible(book, "normal", { category: "セキュリティ" }).map((x) => x.id)).toEqual(["Q2"]);
  });
});

describe("grade", () => {
  it("単一選択・複数選択は完全一致のみ正解", () => {
    expect(grade(book.questions[0], ["A"])).toBe(true);
    expect(grade(book.questions[0], ["B"])).toBe(false);
    expect(grade(book.questions[1], ["B", "A"])).toBe(true);
    expect(grade(book.questions[1], ["A"])).toBe(false);
  });
  it("数値は許容誤差と全角・単位付き入力に対応", () => {
    expect(grade(book.questions[4], ["12.55"])).toBe(true);
    expect(grade(book.questions[4], ["１２．５Mbps"])).toBe(true);
    expect(grade(book.questions[4], ["13"])).toBe(false);
    expect(parseNumber("abc")).toBeNull();
  });
});

describe("pickQuestions", () => {
  const pool = eligible(book, "normal");
  const logs = [log("Q1", false, "2026-11-01"), log("Q1", true, "2026-11-02"), log("Q2", false, "2026-11-03"), log("Q5", true, "2026-11-01")];
  it("弱点克服は間違えたことのある問題を正答率の低い順に", () => {
    expect(pickQuestions(pool, "weak", logs).map((x) => x.id)).toEqual(["Q2", "Q1"]);
  });
  it("復習は前回不正解 → 古い順", () => {
    expect(pickQuestions(pool, "review", logs).map((x) => x.id)).toEqual(["Q2", "Q5", "Q1"]);
  });
  it("模擬試験は指定数をランダムに", () => {
    const r = pickQuestions(pool, "exam", [], { count: 2, rand: () => 0 });
    expect(r).toHaveLength(2);
  });
  it("分野別の正答率", () => {
    const a = accuracyBy(book, logs, "category");
    expect(a.find((x) => x.key === "ネットワーク")).toMatchObject({ attempts: 3, correct: 2 });
  });
});
