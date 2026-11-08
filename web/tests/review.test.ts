import { describe, expect, it } from "vitest";
import { dueItems, dueLabel, nextDueAt, reviewSchedule } from "@/lib/review";
import { eligible } from "@/lib/quiz";
import type { AnswerLog, Book } from "@/lib/types";

const log = (questionId: string, correct: boolean, at: string): AnswerLog => ({
  id: `${questionId}-${at}`, bookId: "B", questionId, selected: [], correct, answeredAt: at, elapsedMs: 0, mode: "normal",
});

describe("忘却曲線の復習", () => {
  it("間違えた問題は1日後に復習、予定日以降の正解で 3→7→14→30日と延び、最後に定着して外れる", () => {
    const logs = [log("Q", false, "2026-11-01T09:00:00Z")];
    expect(reviewSchedule(logs).get("Q")).toMatchObject({ stage: 0, dueAt: "2026-11-02T09:00:00.000Z", lapses: 1 });
    logs.push(log("Q", true, "2026-11-02T10:00:00Z"));
    expect(reviewSchedule(logs).get("Q")).toMatchObject({ stage: 1, dueAt: "2026-11-05T10:00:00.000Z" });
    logs.push(log("Q", true, "2026-11-05T10:00:00Z"), log("Q", true, "2026-11-12T10:00:00Z"), log("Q", true, "2026-11-26T10:00:00Z"));
    expect(reviewSchedule(logs).get("Q")).toMatchObject({ stage: 4, dueAt: "2026-12-26T10:00:00.000Z" });
    logs.push(log("Q", true, "2026-12-27T10:00:00Z"));
    expect(reviewSchedule(logs).has("Q")).toBe(false);
  });
  it("予定日より前の正解では進まず、途中で間違えると最初からやり直し", () => {
    const logs = [log("Q", false, "2026-11-01T09:00:00Z"), log("Q", true, "2026-11-01T09:05:00Z")];
    expect(reviewSchedule(logs).get("Q")?.stage).toBe(0);
    logs.push(log("Q", true, "2026-11-02T09:00:00Z"), log("Q", false, "2026-11-05T09:00:00Z"));
    expect(reviewSchedule(logs).get("Q")).toMatchObject({ stage: 0, dueAt: "2026-11-06T09:00:00.000Z", lapses: 2 });
  });
  it("一度も間違えていない問題は対象外。今日の分と次の予定日がわかる", () => {
    const logs = [log("A", true, "2026-11-01T00:00:00Z"), log("B", false, "2026-11-01T00:00:00Z"), log("C", false, "2026-11-03T00:00:00Z")];
    const now = new Date("2026-11-02T12:00:00Z");
    expect(dueItems(logs, now).map((r) => r.questionId)).toEqual(["B"]);
    expect(nextDueAt(logs, now)).toBe("2026-11-04T00:00:00.000Z");
    expect(dueLabel("2026-11-04T00:00:00.000Z", now)).toBe("2日後");
  });
  it("要確認の問題も、練習（復習）では含められるが模擬試験では出ない", () => {
    const book: Book = { book_id: "B", book_title: "t", version: "1", questions: [
      { id: "P", question_type: "single_choice", question: "", options: [], correct_answers: [], explanation: "",
        source: { page: 1, question_number: 1 }, audio_text: "", tags: [], validation_status: "pending" },
    ] };
    expect(eligible(book, "review", { includePending: true })).toHaveLength(1);
    expect(eligible(book, "exam", { includePending: true })).toHaveLength(0);
  });
});
