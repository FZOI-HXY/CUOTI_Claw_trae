<script setup lang="ts">
import { onMounted, ref } from "vue";
import * as api from "../lib/api";
import type { Question } from "../lib/types";

const queue = ref<Question[]>([]);
const index = ref(0);
const showAnswer = ref(false);
const loading = ref(false);
// 选项缓存：一次解析，避免每次渲染重复 JSON.parse
const optionsCache = new Map<number, string[]>();

const typeLabels: Record<string, string> = {
  single: "单选",
  multiple: "多选",
  judge: "判断",
  fill: "填空",
  answer: "解答",
};

function parseOptions(q: Question): string[] {
  if (optionsCache.has(q.id)) return optionsCache.get(q.id)!;
  let parsed: string[];
  try {
    parsed = q.options ? JSON.parse(q.options) : [];
  } catch {
    parsed = [];
  }
  optionsCache.set(q.id, parsed);
  return parsed;
}

async function load() {
  loading.value = true;
  try {
    queue.value = await api.reviewQueue(50);
    // 预解析所有选项
    optionsCache.clear();
    for (const q of queue.value) {
      // 预热缓存
      parseOptions(q);
    }
    index.value = 0;
    showAnswer.value = false;
  } finally {
    loading.value = false;
  }
}

async function mark(status: string) {
  const q = queue.value[index.value];
  await api.updateStatus(q.id, status);
  await api.incrementWrongCount(q.id);
  await next();
}

async function next() {
  showAnswer.value = false;
  if (index.value < queue.value.length - 1) {
    index.value++;
  } else {
    await load();
  }
}

onMounted(load);
</script>

<template>
  <div class="max-w-3xl mx-auto p-6">
    <div class="flex items-center justify-between mb-6">
      <h1 class="text-2xl font-bold">复习模式</h1>
      <button class="text-sm text-brand-600 hover:underline" @click="load">刷新队列</button>
    </div>

    <div v-if="loading" class="text-center text-gray-400 py-20">加载中…</div>
    <div v-else-if="queue.length === 0" class="text-center text-gray-400 py-20">
      暂无待复习的错题 🎉
    </div>
    <div v-else>
      <div class="mb-4 text-sm text-gray-500">
        第 {{ index + 1 }} / {{ queue.length }} 题
      </div>
      <div class="bg-white rounded-xl shadow-sm p-6">
        <div class="flex items-center gap-2 mb-3">
          <span class="text-xs px-2 py-0.5 rounded bg-brand-50 text-brand-600">
            {{ typeLabels[queue[index].qtype] || queue[index].qtype }}
          </span>
          <span class="text-xs px-2 py-0.5 rounded bg-gray-100 text-gray-600">
            {{ queue[index].subject_name || "未分类" }}
          </span>
          <span class="text-xs text-gray-400">难度 {{ queue[index].difficulty }}</span>
        </div>
        <div class="text-lg font-medium mb-4">{{ queue[index].title }}</div>
        <div v-if="parseOptions(queue[index]).length" class="space-y-1 mb-4">
          <div v-for="opt in parseOptions(queue[index])" :key="opt" class="text-gray-700">
            {{ opt }}
          </div>
        </div>

        <div v-if="showAnswer" class="border-t border-gray-100 pt-4 mt-2 space-y-2">
          <div v-if="queue[index].answer" class="text-sm">
            <span class="font-medium text-brand-600">正确答案：</span>
            {{ queue[index].answer }}
          </div>
          <div v-if="queue[index].analysis" class="text-sm text-gray-600">
            <span class="font-medium">解析：</span>{{ queue[index].analysis }}
          </div>
          <div v-if="queue[index].wrong_reason" class="text-sm text-red-500">
            <span class="font-medium">错因：</span>{{ queue[index].wrong_reason }}
          </div>
        </div>

        <div class="mt-6 flex gap-3">
          <button
            v-if="!showAnswer"
            class="px-6 py-2 bg-brand-600 text-white rounded-lg hover:bg-brand-700"
            @click="showAnswer = true"
          >
            查看答案
          </button>
          <template v-else>
            <button
              class="px-4 py-2 bg-red-500 text-white rounded-lg hover:bg-red-600"
              @click="mark('not_mastered')"
            >
              未掌握
            </button>
            <button
              class="px-4 py-2 bg-yellow-500 text-white rounded-lg hover:bg-yellow-600"
              @click="mark('need_review')"
            >
              需复习
            </button>
            <button
              class="px-4 py-2 bg-green-500 text-white rounded-lg hover:bg-green-600"
              @click="mark('mastered')"
            >
              已掌握
            </button>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>