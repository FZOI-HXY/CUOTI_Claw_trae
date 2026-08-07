import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock Tauri invoke 层，验证各 API 正确调用后端命令名与参数
const invoke = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({ invoke: (...args: unknown[]) => invoke(...args) }));

import * as api from "./api";

describe("api", () => {
  beforeEach(() => {
    invoke.mockReset();
  });

  describe("错题", () => {
    it("createQuestion 调用 create_question 并传入 input", async () => {
      const input = { subject_id: 1, title: "题干" };
      invoke.mockResolvedValue({ id: 1 });
      await api.createQuestion(input);
      expect(invoke).toHaveBeenCalledWith("create_question", { input });
    });

    it("updateQuestion 调用 update_question 并传入 id 与 input", async () => {
      invoke.mockResolvedValue({ id: 5 });
      await api.updateQuestion(5, { subject_id: 1, title: "x" });
      expect(invoke).toHaveBeenCalledWith("update_question", {
        id: 5,
        input: { subject_id: 1, title: "x" },
      });
    });

    it("deleteQuestion 调用 delete_question", async () => {
      invoke.mockResolvedValue(undefined);
      await api.deleteQuestion(3);
      expect(invoke).toHaveBeenCalledWith("delete_question", { id: 3 });
    });

    it("getQuestion 调用 get_question", async () => {
      invoke.mockResolvedValue({ id: 9 });
      await api.getQuestion(9);
      expect(invoke).toHaveBeenCalledWith("get_question", { id: 9 });
    });

    it("listQuestions 调用 list_questions 并透传 filter", async () => {
      invoke.mockResolvedValue([]);
      const filter = { subject_id: 2, status: "not_mastered" };
      await api.listQuestions(filter);
      expect(invoke).toHaveBeenCalledWith("list_questions", { filter });
    });

    it("reviewQueue 调用 review_queue 并透传 limit", async () => {
      invoke.mockResolvedValue([]);
      await api.reviewQueue(50);
      expect(invoke).toHaveBeenCalledWith("review_queue", { limit: 50 });
    });

    it("reviewQueue 无参时 limit 为 undefined", async () => {
      invoke.mockResolvedValue([]);
      await api.reviewQueue();
      expect(invoke).toHaveBeenCalledWith("review_queue", { limit: undefined });
    });

    it("updateStatus 调用 update_status", async () => {
      invoke.mockResolvedValue({});
      await api.updateStatus(7, "mastered");
      expect(invoke).toHaveBeenCalledWith("update_status", { id: 7, status: "mastered" });
    });

    it("incrementWrongCount 调用 increment_wrong_count", async () => {
      invoke.mockResolvedValue({});
      await api.incrementWrongCount(4);
      expect(invoke).toHaveBeenCalledWith("increment_wrong_count", { id: 4 });
    });

    it("toggleFavorite 调用 toggle_favorite", async () => {
      invoke.mockResolvedValue({});
      await api.toggleFavorite(2);
      expect(invoke).toHaveBeenCalledWith("toggle_favorite", { id: 2 });
    });
  });

  describe("科目", () => {
    it("createSubject 调用 create_subject", async () => {
      invoke.mockResolvedValue({});
      await api.createSubject("数学");
      expect(invoke).toHaveBeenCalledWith("create_subject", { name: "数学" });
    });

    it("listSubjects 调用 list_subjects", async () => {
      invoke.mockResolvedValue([]);
      await api.listSubjects();
      expect(invoke).toHaveBeenCalledWith("list_subjects");
    });

    it("renameSubject 调用 rename_subject", async () => {
      invoke.mockResolvedValue({});
      await api.renameSubject(1, "新名");
      expect(invoke).toHaveBeenCalledWith("rename_subject", { id: 1, name: "新名" });
    });
  });

  describe("知识点", () => {
    it("createChapter 调用 create_chapter 并传入三参数", async () => {
      invoke.mockResolvedValue({});
      await api.createChapter(1, 0, "第一节");
      expect(invoke).toHaveBeenCalledWith("create_chapter", {
        subjectId: 1,
        parentId: 0,
        name: "第一节",
      });
    });

    it("listChapters 调用 list_chapters", async () => {
      invoke.mockResolvedValue([]);
      await api.listChapters(1);
      expect(invoke).toHaveBeenCalledWith("list_chapters", { subjectId: 1 });
    });
  });

  describe("标签", () => {
    it("createTag 调用 create_tag", async () => {
      invoke.mockResolvedValue({});
      await api.createTag("易错");
      expect(invoke).toHaveBeenCalledWith("create_tag", { name: "易错" });
    });

    it("listTags 调用 list_tags", async () => {
      invoke.mockResolvedValue([]);
      await api.listTags();
      expect(invoke).toHaveBeenCalledWith("list_tags");
    });
  });

  describe("统计", () => {
    it("getStats 调用 get_stats", async () => {
      invoke.mockResolvedValue({});
      await api.getStats();
      expect(invoke).toHaveBeenCalledWith("get_stats");
    });
  });

  describe("配置", () => {
    it("getLlmConfig 调用 get_llm_config", async () => {
      invoke.mockResolvedValue({});
      await api.getLlmConfig();
      expect(invoke).toHaveBeenCalledWith("get_llm_config");
    });

    it("setLlmConfig 调用 set_llm_config", async () => {
      invoke.mockResolvedValue(undefined);
      const cfg = { base_url: "u", api_key: "k", model: "m", enabled: true };
      await api.setLlmConfig(cfg);
      expect(invoke).toHaveBeenCalledWith("set_llm_config", { cfg });
    });
  });

  describe("OCR", () => {
    it("recognizeImage 调用 recognize_image 并传入数据与文件名", async () => {
      invoke.mockResolvedValue({ raw_text: "" });
      const data = [1, 2, 3];
      await api.recognizeImage(data, "a.png");
      expect(invoke).toHaveBeenCalledWith("recognize_image", { imageData: data, filename: "a.png" });
    });

    it("cleanText 调用 clean_text", async () => {
      invoke.mockResolvedValue({});
      await api.cleanText("题目文本");
      expect(invoke).toHaveBeenCalledWith("clean_text", { text: "题目文本" });
    });
  });

  describe("RAG", () => {
    it("ragAsk 调用 rag_ask 并传入 question/top_k", async () => {
      invoke.mockResolvedValue({ answer: "ok", sources: [] });
      await api.ragAsk("怎样解二次方程", 5);
      expect(invoke).toHaveBeenCalledWith("rag_ask", { question: "怎样解二次方程", top_k: 5 });
    });

    it("ragIndex 调用 rag_index", async () => {
      invoke.mockResolvedValue(3);
      await api.ragIndex();
      expect(invoke).toHaveBeenCalledWith("rag_index");
    });

    it("ragRetrieve 调用 rag_retrieve 并传入 query", async () => {
      invoke.mockResolvedValue([]);
      await api.ragRetrieve("勾股定理", 3);
      expect(invoke).toHaveBeenCalledWith("rag_retrieve", { query: "勾股定理", top_k: 3 });
    });
  });
});