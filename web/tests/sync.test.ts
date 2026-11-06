import { describe, expect, it } from "vitest";
import { fromRow, mergeLogs, newerSession, toRow } from "@/lib/sync";
import type { AnswerLog, Session } from "@/lib/types";

const log = (id: string, at: string, over: Partial<AnswerLog> = {}): AnswerLog =>
  ({ id, bookId: "B", questionId: "B-Q0001", selected: ["A"], correct: true, answeredAt: at, elapsedMs: 10, mode: "normal", ...over });

describe("mergeLogs", () => {
  it("同じidは1件にまとめ、サーバーにあるものは送信済みにする", () => {
    const local = [log("1", "2026-11-01", { synced: false }), log("2", "2026-11-03", { synced: false })];
    const remote = [log("1", "2026-11-01"), log("3", "2026-11-02")];
    const m = mergeLogs(local, remote);
    expect(m.map((l) => l.id)).toEqual(["1", "3", "2"]);
    expect(m.find((l) => l.id === "1")!.synced).toBe(true);
    expect(m.find((l) => l.id === "2")!.synced).toBe(false);
  });
});

describe("toRow / fromRow", () => {
  it("DBの列名と相互に変換できる", () => {
    const l = log("1", "2026-11-01T00:00:00Z", { sessionId: "s1" });
    const r = toRow(l);
    expect(r).toMatchObject({ id: "1", book_id: "B", question_id: "B-Q0001", is_correct: true, session_id: "s1" });
    expect(fromRow(r)).toEqual({ ...l, synced: true });
  });
});

describe("newerSession", () => {
  const s = (id: string, updatedAt: string): Session =>
    ({ id, bookId: "B", mode: "normal", questionIds: [], cursor: 0, answers: {}, startedAt: "2026-11-01", updatedAt });
  it("更新が新しい方を選ぶ", () => {
    expect(newerSession(s("a", "2026-11-02"), s("b", "2026-11-03"))!.id).toBe("b");
    expect(newerSession(null, s("b", "2026-11-03"))!.id).toBe("b");
    expect(newerSession(s("a", "2026-11-04"), s("b", "2026-11-03"))!.id).toBe("a");
  });
});
