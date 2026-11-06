// 出題・採点のロジック（画面から切り離してテストできるようにしている）
import type { AnswerLog, Book, Mode, Question, ValidationStatus } from "./types";

export const MODE_LABEL: Record<Mode, string> = {
  normal: "通常学習",
  exam: "模擬試験",
  weak: "弱点克服",
  review: "復習",
};

export interface Filters {
  chapter?: string;
  category?: string;
  difficulty?: number;
  includePending?: boolean;   // 通常学習でのみ選べる。模擬試験では常に除外
}

/** 出題してよい問題か。原則 verified と auto_ok のみ（問題集の exam_policy に従う）。 */
export function isReady(book: Book, q: Question): boolean {
  const allowed: ValidationStatus[] = book.exam_policy?.allowed_statuses ?? ["verified", "auto_ok"];
  return allowed.includes(q.validation_status);
}

export function eligible(book: Book, mode: Mode, f: Filters = {}): Question[] {
  return book.questions.filter((q) => {
    if (q.validation_status === "rejected") return false;
    const pendingOk = mode === "normal" && f.includePending;
    if (!isReady(book, q) && !pendingOk) return false;
    if (f.chapter && q.chapter !== f.chapter) return false;
    if (f.category && q.category !== f.category) return false;
    if (f.difficulty && q.difficulty !== f.difficulty) return false;
    return true;
  });
}

export function shuffle<T>(arr: T[], rand: () => number = Math.random): T[] {
  const a = arr.slice();
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

export interface QuestionStat { attempts: number; correct: number; lastAt?: string; lastCorrect?: boolean }

export function statsByQuestion(logs: AnswerLog[]): Map<string, QuestionStat> {
  const m = new Map<string, QuestionStat>();
  for (const l of logs) {
    const s = m.get(l.questionId) ?? { attempts: 0, correct: 0 };
    s.attempts += 1;
    if (l.correct) s.correct += 1;
    if (!s.lastAt || l.answeredAt >= s.lastAt) {
      s.lastAt = l.answeredAt;
      s.lastCorrect = l.correct;
    }
    m.set(l.questionId, s);
  }
  return m;
}

export interface PickOptions { count?: number; random?: boolean; rand?: () => number }

/** モードごとに出題する問題を選ぶ */
export function pickQuestions(pool: Question[], mode: Mode, logs: AnswerLog[], o: PickOptions = {}): Question[] {
  const rand = o.rand ?? Math.random;
  const stats = statsByQuestion(logs);
  let list: Question[];
  switch (mode) {
    case "exam":
      list = shuffle(pool, rand);
      break;
    case "weak": {
      // 一度でも間違えた問題を、正答率が低い順・最後に間違えた順に
      list = pool
        .filter((q) => {
          const s = stats.get(q.id);
          return s && s.correct < s.attempts;
        })
        .sort((a, b) => {
          const sa = stats.get(a.id)!, sb = stats.get(b.id)!;
          const ra = sa.correct / sa.attempts, rb = sb.correct / sb.attempts;
          if (ra !== rb) return ra - rb;
          return (sb.lastAt ?? "").localeCompare(sa.lastAt ?? "");
        });
      break;
    }
    case "review": {
      // 解いたことがある問題を、前回不正解 → 前回から時間が空いた順に
      list = pool
        .filter((q) => stats.has(q.id))
        .sort((a, b) => {
          const sa = stats.get(a.id)!, sb = stats.get(b.id)!;
          if (sa.lastCorrect !== sb.lastCorrect) return sa.lastCorrect ? 1 : -1;
          return (sa.lastAt ?? "").localeCompare(sb.lastAt ?? "");
        });
      break;
    }
    default:
      list = o.random ? shuffle(pool, rand) : pool.slice();
  }
  return o.count ? list.slice(0, o.count) : list;
}

/** 全角数字などを半角にし、単位などを除いて数値にする */
export function parseNumber(input: string): number | null {
  const s = input.normalize("NFKC").replace(/[,，\s]/g, "");
  const m = s.match(/^[-+]?\d+(?:\.\d+)?/);
  return m ? Number(m[0]) : null;
}

export function grade(q: Question, selected: string[]): boolean {
  if (q.question_type === "numeric") {
    const na = q.numeric_answer;
    const v = parseNumber(selected[0] ?? "");
    if (!na || v === null) return false;
    return Math.abs(v - na.value) <= Math.max(na.tolerance ?? 0, 1e-9);
  }
  const a = [...new Set(selected)].sort();
  const b = [...q.correct_answers].sort();
  return a.length === b.length && a.every((x, i) => x === b[i]);
}

export function correctAnswerText(q: Question): string {
  if (q.question_type === "numeric" && q.numeric_answer) {
    return `${q.numeric_answer.value}${q.numeric_answer.unit ?? ""}`;
  }
  return q.correct_answers
    .map((id) => {
      const o = q.options.find((x) => x.id === id);
      return o ? `${o.label ?? o.id} ${o.text}` : id;
    })
    .join("、");
}

export interface Accuracy { key: string; attempts: number; correct: number; rate: number }

/** 章・分野・難易度ごとの正答率（回答ログの全回答を対象） */
export function accuracyBy(book: Book, logs: AnswerLog[], field: "chapter" | "category" | "difficulty"): Accuracy[] {
  const byId = new Map(book.questions.map((q) => [q.id, q]));
  const acc = new Map<string, { attempts: number; correct: number }>();
  for (const l of logs) {
    const q = byId.get(l.questionId);
    if (!q) continue;
    const key = String(q[field] ?? "未設定");
    const a = acc.get(key) ?? { attempts: 0, correct: 0 };
    a.attempts += 1;
    if (l.correct) a.correct += 1;
    acc.set(key, a);
  }
  return [...acc.entries()].map(([key, a]) => ({ key, ...a, rate: a.correct / a.attempts }));
}
