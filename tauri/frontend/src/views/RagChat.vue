<script setup lang="ts">
import { onMounted, ref } from "vue";
import * as api from "../lib/api";
import type { RagSource } from "../lib/types";

const question = ref("");
const answer = ref("");
const sources = ref<RagSource[]>([]);
const loading = ref(false);
const indexing = ref(false);
const indexMsg = ref("");
const error = ref("");

async function ask() {
  const text = question.value.trim();
  if (!text || loading.value) return;
  loading.value = true;
  error.value = "";
  answer.value = "";
  sources.value = [];
  try {
    const res = await api.ragAsk(text, 5);
    answer.value = res.answer;
    sources.value = res.sources;
  } catch (e) {
    error.value = `问答失败: ${e}`;
  } finally {
    loading.value = false;
  }
}

async function indexNow() {
  if (indexing.value) return;
  indexing.value = true;
  indexMsg.value = "";
  try {
    const n = await api.ragIndex();
    indexMsg.value = `索引完成，共 ${n} 题`;
  } catch (e) {
    indexMsg.value = `索引失败: ${e}`;
  } finally {
    indexing.value = false;
  }
}

onMounted(() => {});
</script>

<template>
  <div class="max-w-3xl mx-auto p-6">
    <div class="flex items-center justify-between mb-6">
      <h1 class="text-2xl font-bold">AI 问答</h1>
      <button
        class="px-4 py-2 border border-gray-300 rounded-lg text-sm hover:bg-gray-50 disabled:opacity-50"
        :disabled="indexing"
        @click="indexNow"
      >
        {{ indexing ? "索引中…" : "更新索引" }}
      </button>
    </div>

    <p v-if="indexMsg" class="text-sm text-gray-500 mb-4">{{ indexMsg }}</p>

    <div class="flex gap-2 mb-4">
      <input
        v-model="question"
        class="flex-1 border border-gray-200 rounded-lg px-3 py-2"
        placeholder="用自然语言提问，例如：怎么解一元二次方程？"
        @keyup.enter="ask"
      />
      <button
        class="px-6 py-2 bg-brand-600 text-white rounded-lg hover:bg-brand-700 disabled:opacity-50"
        :disabled="loading || !question.trim()"
        @click="ask"
      >
        {{ loading ? "思考中…" : "提问" }}
      </button>
    </div>

    <p v-if="error" class="text-red-500 text-sm mb-4">{{ error }}</p>

    <div
      v-if="answer"
      class="bg-white rounded-xl shadow-sm p-6 mb-6 whitespace-pre-wrap leading-relaxed"
    >
      {{ answer }}
    </div>

    <div v-if="sources.length" class="bg-white rounded-xl shadow-sm p-6">
      <h2 class="font-semibold mb-3">参考题目</h2>
      <ul class="space-y-2">
        <li v-for="s in sources" :key="s.question_id" class="text-sm">
          <RouterLink
            :to="`/questions/${s.question_id}/edit`"
            class="text-brand-600 hover:underline"
          >
            {{ s.title }}
          </RouterLink>
          <span class="text-gray-400 ml-2 tabular-nums">相关度 {{ (s.score * 100).toFixed(1) }}%</span>
        </li>
      </ul>
    </div>
  </div>
</template>