import { defineStore } from "pinia";
import { ref } from "vue";
import * as api from "../lib/api";
import type { Chapter, Subject, Tag } from "../lib/types";

export const useMetaStore = defineStore("meta", () => {
  const subjects = ref<Subject[]>([]);
  const chapters = ref<Record<number, Chapter[]>>({});
  const tags = ref<Tag[]>([]);
  const loading = ref(false);

  async function loadSubjects() {
    subjects.value = await api.listSubjects();
  }

  async function loadChapters(subjectId: number) {
    if (subjectId == null) return;
    chapters.value[subjectId] = await api.listChapters(subjectId);
  }

  async function loadTags() {
    tags.value = await api.listTags();
  }

  async function loadAll() {
    loading.value = true;
    try {
      await Promise.all([loadSubjects(), loadTags()]);
      for (const s of subjects.value) {
        await loadChapters(s.id);
      }
    } finally {
      loading.value = false;
    }
  }

  return { subjects, chapters, tags, loading, loadAll, loadSubjects, loadChapters, loadTags };
});