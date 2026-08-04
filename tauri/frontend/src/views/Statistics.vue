<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import * as api from "../lib/api";
import type { Stats } from "../lib/types";

const stats = ref<Stats | null>(null);
const loading = ref(false);

const typeLabels: Record<string, string> = {
  single: "单选",
  multiple: "多选",
  judge: "判断",
  fill: "填空",
  answer: "解答",
};

const masteryRate = computed(() => {
  if (!stats.value || stats.value.total === 0) return 0;
  return Math.round((stats.value.mastered / stats.value.total) * 100);
});

// 简易 SVG 条形图
function barWidth(value: number, max: number): string {
  if (max === 0) return "0%";
  return `${Math.round((value / max) * 100)}%`;
}

async function load() {
  loading.value = true;
  try {
    stats.value = await api.getStats();
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="max-w-5xl mx-auto p-6">
    <h1 class="text-2xl font-bold mb-6">统计</h1>

    <div v-if="loading" class="text-center text-gray-400 py-20">加载中…</div>
    <div v-else-if="!stats" class="text-center text-gray-400 py-20">暂无数据</div>
    <div v-else>
      <!-- 概览卡片 -->
      <div class="grid grid-cols-2 md:grid-cols-5 gap-4 mb-8">
        <div class="bg-white rounded-xl p-4 shadow-sm text-center">
          <div class="text-3xl font-bold text-brand-600 tabular-nums">{{ stats.total }}</div>
          <div class="text-sm text-gray-500 mt-1">总错题</div>
        </div>
        <div class="bg-white rounded-xl p-4 shadow-sm text-center">
          <div class="text-3xl font-bold text-green-500 tabular-nums">{{ stats.mastered }}</div>
          <div class="text-sm text-gray-500 mt-1">已掌握</div>
        </div>
        <div class="bg-white rounded-xl p-4 shadow-sm text-center">
          <div class="text-3xl font-bold text-yellow-500 tabular-nums">{{ stats.need_review }}</div>
          <div class="text-sm text-gray-500 mt-1">需复习</div>
        </div>
        <div class="bg-white rounded-xl p-4 shadow-sm text-center">
          <div class="text-3xl font-bold text-red-500 tabular-nums">{{ stats.not_mastered }}</div>
          <div class="text-sm text-gray-500 mt-1">未掌握</div>
        </div>
        <div class="bg-white rounded-xl p-4 shadow-sm text-center">
          <div class="text-3xl font-bold text-yellow-400 tabular-nums">{{ stats.favorite }}</div>
          <div class="text-sm text-gray-500 mt-1">收藏</div>
        </div>
      </div>

      <!-- 掌握率 -->
      <div class="bg-white rounded-xl p-6 shadow-sm mb-6">
        <div class="flex items-center justify-between mb-2">
          <h2 class="font-semibold">总体掌握率</h2>
          <span class="text-brand-600 font-bold tabular-nums">{{ masteryRate }}%</span>
        </div>
        <div class="h-3 bg-gray-100 rounded-full overflow-hidden">
          <div
            class="h-full bg-brand-600 transition-all"
            :style="{ width: masteryRate + '%' }"
          ></div>
        </div>
      </div>

      <!-- 按科目 -->
      <div class="bg-white rounded-xl p-6 shadow-sm mb-6">
        <h2 class="font-semibold mb-4">按科目</h2>
        <div v-if="stats.by_subject.length === 0" class="text-gray-400 text-sm">暂无数据</div>
        <div v-else class="space-y-3">
          <div v-for="s in stats.by_subject" :key="s.subject_id">
            <div class="flex justify-between text-sm mb-1">
              <span>{{ s.subject_name }}</span>
              <span class="text-gray-500 tabular-nums">{{ s.mastered }}/{{ s.total }} 已掌握</span>
            </div>
            <div class="h-2 bg-gray-100 rounded-full overflow-hidden">
              <div
                class="h-full bg-brand-500"
                :style="{ width: barWidth(s.mastered, s.total) }"
              ></div>
            </div>
          </div>
        </div>
      </div>

      <!-- 按知识点 -->
      <div class="bg-white rounded-xl p-6 shadow-sm mb-6">
        <h2 class="font-semibold mb-4">按知识点（错题最多的前 10）</h2>
        <div v-if="stats.by_chapter.length === 0" class="text-gray-400 text-sm">暂无数据</div>
        <div v-else class="space-y-2">
          <div
            v-for="c in stats.by_chapter.slice(0, 10)"
            :key="c.chapter_id"
            class="flex justify-between text-sm"
          >
            <span>{{ c.chapter_name }}</span>
            <span class="text-gray-500 tabular-nums">{{ c.total }} 题</span>
          </div>
        </div>
      </div>

      <!-- 按题型 -->
      <div class="bg-white rounded-xl p-6 shadow-sm">
        <h2 class="font-semibold mb-4">按题型</h2>
        <div v-if="stats.by_type.length === 0" class="text-gray-400 text-sm">暂无数据</div>
        <div v-else class="space-y-3">
          <div v-for="t in stats.by_type" :key="t.qtype">
            <div class="flex justify-between text-sm mb-1">
              <span>{{ typeLabels[t.qtype] || t.qtype }}</span>
              <span class="text-gray-500 tabular-nums">{{ t.total }} 题</span>
            </div>
            <div class="h-2 bg-gray-100 rounded-full overflow-hidden">
              <div
                class="h-full bg-gray-400"
                :style="{ width: barWidth(t.total, stats.by_type[0].total) }"
              ></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>