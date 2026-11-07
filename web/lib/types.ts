// 教材JSON（schema/question_book.schema.json）の型。パイプラインの出力と同じ形。
export type QuestionType = "single_choice" | "multiple_choice" | "true_false" | "numeric";
export type ValidationStatus = "pending" | "auto_ok" | "verified" | "rejected";

export interface Option { id: string; label?: string; text: string }
export interface NumericAnswer { value: number; unit?: string | null; tolerance?: number }
export interface ImageRef { path: string; page: number; required: boolean; kind?: string }

export interface Question {
  id: string;
  chapter?: string;
  category?: string;
  difficulty?: number | null;
  question_type: QuestionType;
  question: string;
  options: Option[];
  correct_answers: string[];
  numeric_answer?: NumericAnswer | null;
  explanation: string;
  images?: ImageRef[];
  source: { page: number; question_number: number; answer_page?: number | null };
  audio_text: string;
  audio_answer_text?: string;
  audio?: { question?: string; answer?: string; full?: string }; // STEP 9 で作るMP3（book.json からの相対パス）
  tags: string[];
  validation_status: ValidationStatus;
}

export interface Book {
  book_id: string;
  book_title: string;
  version: string;
  exam_policy?: { allowed_statuses: ValidationStatus[] };
  questions: Question[];
}

export interface AudioManifest {
  engine: string;
  pause_seconds: number;
  chapters: { chapter: string; file: string; questions: number }[];
}

export interface BookIndexEntry { book_id: string; book_title: string; version: string; question_count: number; ready_count: number }

export type Mode = "normal" | "exam" | "weak" | "review";

export interface AnswerLog {
  id: string;              // UUID。端末で採番し、Supabaseへの二重送信を防ぐ
  synced?: boolean;        // Supabaseに送信済みか
  sessionId?: string;
  bookId: string;
  questionId: string;
  selected: string[];      // 選択肢ID。数値問題は入力文字列を1要素で
  correct: boolean;
  answeredAt: string;      // ISO
  elapsedMs: number;
  mode: Mode;
}

export interface Session {
  id: string;
  bookId: string;
  mode: Mode;
  questionIds: string[];
  cursor: number;                          // 次に解く問題の位置
  answers: Record<string, { selected: string[]; correct: boolean }>;
  startedAt: string;
  finishedAt?: string;
  updatedAt?: string;      // 端末間でどちらが新しいかの判定用
}
