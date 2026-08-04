import { invoke } from "@tauri-apps/api/core";
import type {
  Chapter,
  CleanedQuestion,
  LlmConfig,
  OcrConfig,
  OcrDraft,
  Question,
  QuestionFilter,
  QuestionInput,
  Stats,
  Subject,
  Tag,
} from "./types";

// ---- 错题 ----
export const createQuestion = (input: QuestionInput) =>
  invoke<Question>("create_question", { input });
export const updateQuestion = (id: number, input: QuestionInput) =>
  invoke<Question>("update_question", { id, input });
export const deleteQuestion = (id: number) =>
  invoke<void>("delete_question", { id });
export const getQuestion = (id: number) => invoke<Question>("get_question", { id });
export const listQuestions = (filter: QuestionFilter) =>
  invoke<Question[]>("list_questions", { filter });
export const reviewQueue = (limit?: number) =>
  invoke<Question[]>("review_queue", { limit });
export const updateStatus = (id: number, status: string) =>
  invoke<Question>("update_status", { id, status });
export const incrementWrongCount = (id: number) =>
  invoke<Question>("increment_wrong_count", { id });
export const toggleFavorite = (id: number) =>
  invoke<Question>("toggle_favorite", { id });

// ---- 科目 ----
export const createSubject = (name: string) =>
  invoke<Subject>("create_subject", { name });
export const listSubjects = () => invoke<Subject[]>("list_subjects");
export const renameSubject = (id: number, name: string) =>
  invoke<Subject>("rename_subject", { id, name });
export const deleteSubject = (id: number) => invoke<void>("delete_subject", { id });

// ---- 知识点 ----
export const createChapter = (subjectId: number, parentId: number, name: string) =>
  invoke<Chapter>("create_chapter", { subjectId, parentId, name });
export const listChapters = (subjectId: number) =>
  invoke<Chapter[]>("list_chapters", { subjectId });
export const renameChapter = (id: number, name: string) =>
  invoke<Chapter>("rename_chapter", { id, name });
export const deleteChapter = (id: number) => invoke<void>("delete_chapter", { id });

// ---- 标签 ----
export const createTag = (name: string) => invoke<Tag>("create_tag", { name });
export const listTags = () => invoke<Tag[]>("list_tags");
export const deleteTag = (id: number) => invoke<void>("delete_tag", { id });

// ---- 统计 ----
export const getStats = () => invoke<Stats>("get_stats");

// ---- 配置 ----
export const getOcrConfig = () => invoke<OcrConfig>("get_ocr_config");
export const setOcrConfig = (cfg: OcrConfig) => invoke<void>("set_ocr_config", { cfg });
export const getLlmConfig = () => invoke<LlmConfig>("get_llm_config");
export const setLlmConfig = (cfg: LlmConfig) => invoke<void>("set_llm_config", { cfg });

// ---- OCR ----
export const recognizeImage = (imageData: number[], filename: string) =>
  invoke<OcrDraft>("recognize_image", { imageData, filename });
export const cleanText = (text: string) =>
  invoke<CleanedQuestion>("clean_text", { text });