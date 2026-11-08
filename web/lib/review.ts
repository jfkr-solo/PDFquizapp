// 忘却曲線に合わせた復習（間隔反復）。回答ログだけから計算するので、保存や同期の仕組みは増やさない。
//
// ・一度でも間違えた問題が復習の対象になる。間違えるたびに段階0に戻る。
// ・復習の予定日（due）以降に正解すると次の段階に進み、間隔が延びる。予定日より前の正解では進まない
//   （直後に解き直して覚えたつもりになるのを防ぐため）。
// ・最後の段階で正解したら「定着」として対象から外れる。
import type { AnswerLog } from "./types";

/** 各段階で次の復習までに空ける日数（エビングハウスの忘却曲線を目安にした一般的な間隔） */
export const INTERVAL_DAYS = [1, 3, 7, 14, 30];
const DAY = 24 * 60 * 60 * 1000;

export interface ReviewItem {
  questionId: string;
  stage: number;          // 0〜INTERVAL_DAYS.length-1。次の復習で正解すると +1
  dueAt: string;          // ISO。この時刻以降に出題する
  lastWrongAt: string;
  lapses: number;         // 間違えた回数
}

/** 回答ログから問題ごとの復習予定を作る。定着した問題は含めない。 */
export function reviewSchedule(logs: AnswerLog[]): Map<string, ReviewItem> {
  const byQ = new Map<string, AnswerLog[]>();
  for (const l of logs) {
    const a = byQ.get(l.questionId) ?? [];
    a.push(l);
    byQ.set(l.questionId, a);
  }
  const out = new Map<string, ReviewItem>();
  for (const [qid, ls] of byQ) {
    ls.sort((a, b) => a.answeredAt.localeCompare(b.answeredAt));
    let item = null as ReviewItem | null;
    for (const l of ls) {
      const t = Date.parse(l.answeredAt);
      if (!l.correct) {
        item = {
          questionId: qid, stage: 0, lastWrongAt: l.answeredAt,
          dueAt: new Date(t + INTERVAL_DAYS[0] * DAY).toISOString(), lapses: (item?.lapses ?? 0) + 1,
        };
      } else if (item && t >= Date.parse(item.dueAt)) {
        const stage: number = item.stage + 1;
        if (stage >= INTERVAL_DAYS.length) {
          item = null; // 定着
        } else {
          item = { ...item, stage, dueAt: new Date(t + INTERVAL_DAYS[stage] * DAY).toISOString() };
        }
      }
    }
    if (item) out.set(qid, item);
  }
  return out;
}

/** 今が予定日を過ぎている問題を、予定日の古い順に */
export function dueItems(logs: AnswerLog[], now: Date = new Date()): ReviewItem[] {
  return [...reviewSchedule(logs).values()]
    .filter((r) => Date.parse(r.dueAt) <= now.getTime())
    .sort((a, b) => a.dueAt.localeCompare(b.dueAt));
}

/** まだ予定日が来ていない問題のうち、いちばん近い予定日（なければ null） */
export function nextDueAt(logs: AnswerLog[], now: Date = new Date()): string | null {
  const later = [...reviewSchedule(logs).values()].filter((r) => Date.parse(r.dueAt) > now.getTime());
  if (!later.length) return null;
  return later.reduce((m, r) => (r.dueAt < m ? r.dueAt : m), later[0].dueAt);
}

/** 「あすから」「3日後」などの言い方 */
export function dueLabel(dueAt: string, now: Date = new Date()): string {
  const d = Math.ceil((Date.parse(dueAt) - now.getTime()) / DAY);
  if (d <= 0) return "今日";
  if (d === 1) return "あす";
  return `${d}日後`;
}
