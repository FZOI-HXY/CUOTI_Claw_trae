import { describe, it, expect, vi, beforeEach } from "vitest";
import { setActivePinia, createPinia } from "pinia";

// Mock api 层，隔离 store 与 Tauri 后端
const api = vi.hoisted(() => ({
  listSubjects: vi.fn(),
  listTags: vi.fn(),
  listChapters: vi.fn(),
}));
vi.mock("../lib/api", () => api);

import { useMetaStore } from "./meta";

describe("meta store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    api.listSubjects.mockReset();
    api.listTags.mockReset();
    api.listChapters.mockReset();
  });

  it("loadSubjects 填充 subjects", async () => {
    const store = useMetaStore();
    api.listSubjects.mockResolvedValue([{ id: 1, name: "数学", created_at: "" }]);
    await store.loadSubjects();
    expect(store.subjects).toEqual([{ id: 1, name: "数学", created_at: "" }]);
  });

  it("loadTags 填充 tags", async () => {
    const store = useMetaStore();
    api.listTags.mockResolvedValue([{ id: 1, name: "易错" }]);
    await store.loadTags();
    expect(store.tags).toEqual([{ id: 1, name: "易错" }]);
  });

  it("loadChapters 按 subjectId 存入 chapters 映射", async () => {
    const store = useMetaStore();
    api.listChapters.mockResolvedValue([{ id: 10, subject_id: 1, parent_id: 0, name: "第一节", path: "", created_at: "" }]);
    await store.loadChapters(1);
    expect(store.chapters[1]).toEqual([
      { id: 10, subject_id: 1, parent_id: 0, name: "第一节", path: "", created_at: "" },
    ]);
  });

  it("loadChapters 对 null subjectId 不发请求", async () => {
    const store = useMetaStore();
    await store.loadChapters(null as unknown as number);
    expect(api.listChapters).not.toHaveBeenCalled();
  });

  it("loadAll 并行加载科目、标签，并为每个科目加载章节", async () => {
    const store = useMetaStore();
    api.listSubjects.mockResolvedValue([
      { id: 1, name: "数学", created_at: "" },
      { id: 2, name: "物理", created_at: "" },
    ]);
    api.listTags.mockResolvedValue([]);
    api.listChapters.mockResolvedValue([]);

    await store.loadAll();

    expect(api.listSubjects).toHaveBeenCalledTimes(1);
    expect(api.listTags).toHaveBeenCalledTimes(1);
    // 应为每个科目各调用一次章节加载
    expect(api.listChapters).toHaveBeenCalledTimes(2);
    expect(api.listChapters).toHaveBeenCalledWith(1);
    expect(api.listChapters).toHaveBeenCalledWith(2);
  });

  it("loadAll 包裹 loading 状态", async () => {
    const store = useMetaStore();
    api.listSubjects.mockResolvedValue([]);
    api.listTags.mockResolvedValue([]);
    const loadPromise = store.loadAll();
    expect(store.loading).toBe(true);
    await loadPromise;
    expect(store.loading).toBe(false);
  });
});