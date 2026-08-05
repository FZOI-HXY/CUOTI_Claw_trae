// 类型定义（与 Rust 后端对应）

export type QuestionType = "single" | "multiple" | "judge" | "fill" | "answer";
export type MasteryStatus = "not_mastered" | "mastered" | "need_review";

export interface Subject {
  id: number;
  name: string;
  created_at: string;
}

export interface Chapter {
  id: number;
  subject_id: number;
  parent_id: number;
  name: string;
  path: string;
  created_at: string;
}

export interface Tag {
  id: number;
  name: string;
}

export interface Question {
  id: number;
  subject_id: number;
  chapter_id: number | null;
  qtype: QuestionType;
  title: string;
  options: string | null;
  answer: string | null;
  analysis: string | null;
  difficulty: number;
  status: MasteryStatus;
  wrong_count: number;
  notes: string | null;
  is_favorite: boolean;
  image_path: string | null;
  source: string | null;
  wrong_reason: string | null;
  last_reviewed_at: string | null;
  created_at: string;
  updated_at: string;
  subject_name?: string;
  chapter_name?: string;
  tags?: string[];
}

export interface QuestionInput {
  subject_id: number;
  chapter_id?: number | null;
  qtype?: string;
  title: string;
  options?: string[] | null;
  answer?: string | null;
  analysis?: string | null;
  difficulty?: number | null;
  status?: string | null;
  notes?: string | null;
  is_favorite?: boolean | null;
  image_path?: string | null;
  source?: string | null;
  wrong_reason?: string | null;
  tags?: string[] | null;
}

export interface QuestionFilter {
  subject_id?: number | null;
  chapter_id?: number | null;
  qtype?: string | null;
  difficulty?: number | null;
  status?: string | null;
  keyword?: string | null;
  is_favorite?: boolean | null;
  tag?: string | null;
}

export interface SubjectStat {
  subject_id: number;
  subject_name: string;
  total: number;
  mastered: number;
  need_review: number;
  not_mastered: number;
}

export interface ChapterStat {
  chapter_id: number;
  chapter_name: string;
  path: string;
  total: number;
  mastered: number;
}

export interface TypeStat {
  qtype: string;
  total: number;
}

export interface Stats {
  total: number;
  mastered: number;
  need_review: number;
  not_mastered: number;
  favorite: number;
  by_subject: SubjectStat[];
  by_chapter: ChapterStat[];
  by_type: TypeStat[];
}

export interface OcrConfig {
  api_url: string;
  api_key: string;
  model: string;
}

export interface LlmConfig {
  base_url: string;
  api_key: string;
  model: string;
  enabled: boolean;
}

export interface CleanedQuestion {
  qtype?: string | null;
  title?: string | null;
  options?: string[] | null;
  answer?: string | null;
  analysis?: string | null;
  difficulty?: number | null;
  subject?: string | null;
  chapter?: string | null;
  tags?: string[] | null;
}

export interface OcrDraft {
  raw_text: string;
  cleaned?: CleanedQuestion | null;
  error?: string | null;
}

export interface RagSource {
  question_id: number;
  title: string;
  score: number;
}

export interface RagAnswer {
  answer: string;
  sources: RagSource[];
}