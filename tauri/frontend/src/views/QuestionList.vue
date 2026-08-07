<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { convertFileSrc } from "@tauri-apps/api/core";
import * as api from "../lib/api";
import { useMetaStore } from "../stores/meta";
import type { Question, QuestionFilter } from "../lib/types";

const router = useRouter();
const meta = useMetaStore();

const questions = ref<Question[]>([]);
const loading = ref(false);
const filter = ref<QuestionFilter>({});
const keyword = ref("");
// 选项缓存：一次解析，避免每次渲染重复 JSON.parse
const optionsCache = new Map<number, string[]>();

const typeLabels: Record<string, string> = {
  single: "单选",
  multiple: "多选",
  judge: "判断",
  fill: "填空",
  answer: "解答",
};
const statusLabels: Record<string, string> = {
  not_mastered: "未掌握",
  mastered: "已掌握",
  need_review: "需复习",
};

async function load() {
  loading.value = true;
  try {
    filter.value.keyword = keyword.value || null;
    questions.value = await api.listQuestions(filter.value);
    // 预解析选项，供模板直接读取
    optionsCache.clear();
    for (const q of questions.value) {
      optionsCache.set(q.id, parseOptions(q.options));
    }
  } finally {
    loading.value = false;
  }
}

function parseOptions(options: string | null): string[] {
  if (!options) return [];
  try {
    return JSON.parse(options);
  } catch {
    return [];
  }
}

function optionsOf(q: Question): string[] {
  return optionsCache.get(q.id) ?? [];
}

function imageSrc(path: string | null | undefined): string {
  return path ? convertFileSrc(path) : "";
}

async function onToggleFavorite(q: Question) {
  await api.toggleFavorite(q.id);
  // 局部更新：只修改当前项的收藏状态，避免全量重拉
  const index = questions.value.findIndex(item => item.id === q.id);
  if (index !== -1) {
    questions.value[index].is_favorite = !questions.value[index].is_favorite;
  }
}

async function onDelete(q: Question) {
  if (!confirm(`确定删除该错题？\n${q.title}`)) return;
  await api.deleteQuestion(q.id);
  // 局部更新：直接从列表中移除，避免全量重拉
  const index = questions.value.findIndex(item => item.id === q.id);
  if (index !== -1) {
    optionsCache.delete(q.id);
    questions.value.splice(index, 1);
  }
}

onMounted(() => {
  meta.loadAll();
  load();
});
</script>

<template>
  <div class="p-6 max-w-6xl mx-auto">
    <div class="flex items-center justify-between mb-4">
      <h1 class="text-2xl font-bold">错题列表</h1>
      <button
        class="px-4 py-2 bg-brand-600 text-white rounded-lg hover:bg-brand-700"
        @click="router.push('/questions/new')"
      >
        新增错题
      </button>
    </div>

    <!-- 筛选栏 -->
    <div class="bg-white p-4 rounded-xl shadow-sm mb-4 grid grid-cols-2 md:grid-cols-4 gap-3">
      <input
        v-model="keyword"
        placeholder="搜索题干/答案/解析…"
        class="border border-gray-200 rounded-lg px-3 py-2 text-sm"
        @keyup.enter="load"
      />
      <select v-model="filter.subject_id" class="border border-gray-200 rounded-lg px-3 py-2 text-sm">
        <option :value="null">全部科目</option>
        <option v-for="s in meta.subjects" :key="s.id" :value="s.id">{{ s.name }}</option>
      </select>
      <select v-model="filter.qtype" class="border border-gray-200 rounded-lg px-3 py-2 text-sm">
        <option :value="null">全部题型</option>
        <option value="single">单选</option>
        <option value="multiple">多选</option>
        <option value="judge">判断</option>
        <option value="fill">填空</option>
        <option value="answer">解答</option>
      </select>
      <select v-model="filter.status" class="border border-gray-200 rounded-lg px-3 py-2 text-sm">
        <option :value="null">全部状态</option>
        <option value="not_mastered">未掌握</option>
        <option value="mastered">已掌握</option>
        <option value="need_review">需复习</option>
      </select>
      <button
        class="px-4 py-2 bg-brand-50 text-brand-600 rounded-lg text-sm hover:bg-brand-100"
        @click="load"
      >
        应用筛选
      </button>
    </div>

    <!-- 列表 -->
    <div v-if="loading" class="text-center text-gray-400 py-10">加载中…</div>
    <div v-else-if="questions.length === 0" class="text-center text-gray-400 py-10">
      暂无错题，点击「新增错题」开始记录
    </div>
    <div v-else class="space-y-3">
      <RouterLink
        v-for="q in questions"
        :key="q.id"
        :to="`/questions/${q.id}/edit`"
        class="block bg-white rounded-xl shadow-sm p-4 hover:shadow-md transition cursor-pointer"
      >
        <div class="flex items-start justify-between gap-3">
          <img
            v-if="imageSrc(q.image_path)"
            :src="imageSrc(q.image_path)"
            alt="题目图片"
            class="w-16 h-16 rounded-lg border border-gray-200 object-cover shrink-0"
          />
          <div class="flex-1">
            <div class="flex items-center gap-2 mb-1">
              <span class="text-xs px-2 py-0.5 rounded bg-brand-50 text-brand-600">
                {{ typeLabels[q.qtype] || q.qtype }}
              </span>
              <span class="text-xs px-2 py-0.5 rounded bg-gray-100 text-gray-600">
                {{ q.subject_name || "未分类" }}
              </span>
              <span
                class="text-xs px-2 py-0.5 rounded"
                :class="{
                  'bg-red-50 text-red-600': q.status === 'not_mastered',
                  'bg-green-50 text-green-600': q.status === 'mastered',
                  'bg-yellow-50 text-yellow-600': q.status === 'need_review',
                }"
              >
                {{ statusLabels[q.status] }}
              </span>
              <span v-if="q.chapter_name" class="text-xs text-gray-400">{{ q.chapter_name }}</span>
            </div>
            <div class="font-medium line-clamp-2">{{ q.title }}</div>
            <div v-if="optionsOf(q).length" class="text-sm text-gray-500 mt-1">
              <span v-for="opt in optionsOf(q)" :key="opt" class="mr-3">{{ opt }}</span>
            </div>
            <div class="text-xs text-gray-400 mt-2 flex items-center gap-3">
              <span>难度 {{ q.difficulty }}</span>
              <span>出错 {{ q.wrong_count }} 次</span>
              <span v-if="q.tags?.length">标签: {{ q.tags.join(", ") }}</span>
            </div>
          </div>
          <div class="flex flex-col items-center gap-2">
            <button
              class="text-xl"
              :class="q.is_favorite ? 'text-yellow-400' : 'text-gray-300'"
              :aria-label="q.is_favorite ? '取消收藏' : '收藏'"
              :title="q.is_favorite ? '取消收藏' : '收藏'"
              @click.stop="onToggleFavorite(q)"
            >
              ★
            </button>
            <button
              class="text-gray-400 hover:text-red-500 text-sm"
              @click.stop="onDelete(q)"
            >
              删除
            </button>
          </div>
        </div>
      </RouterLink>
    </div>
  </div>
</template>