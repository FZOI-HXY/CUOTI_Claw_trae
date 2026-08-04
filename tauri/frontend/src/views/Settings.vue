<script setup lang="ts">
import { onMounted, ref } from "vue";
import * as api from "../lib/api";
import type { LlmConfig, OcrConfig } from "../lib/types";

const ocr = ref<OcrConfig>({
  api_url: "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs",
  api_key: "",
  model: "PaddleOCR-VL-1.6",
});
const llm = ref<LlmConfig>({
  base_url: "",
  api_key: "",
  model: "",
  enabled: false,
});
const saving = ref(false);
const saved = ref(false);

const modelOptions = [
  "PaddleOCR-VL-1.6",
  "PaddleOCR-VL-1.5",
  "PaddleOCR-VL",
  "PP-StructureV3",
  "PP-OCRv6",
  "PP-OCRv5",
];

async function load() {
  ocr.value = await api.getOcrConfig();
  llm.value = await api.getLlmConfig();
}

async function save() {
  saving.value = true;
  saved.value = false;
  try {
    await api.setOcrConfig(ocr.value);
    await api.setLlmConfig(llm.value);
    saved.value = true;
    setTimeout(() => (saved.value = false), 2000);
  } finally {
    saving.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="max-w-2xl mx-auto p-6">
    <h1 class="text-2xl font-bold mb-6">设置</h1>

    <!-- PaddleOCR 配置 -->
    <div class="bg-white rounded-xl shadow-sm p-6 mb-6">
      <h2 class="font-semibold mb-4">PaddleOCR 识别 API</h2>
      <div class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">API URL</label>
          <input
            v-model="ocr.api_url"
            class="w-full border border-gray-200 rounded-lg px-3 py-2"
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">API Key (Token)</label>
          <input
            v-model="ocr.api_key"
            type="password"
            class="w-full border border-gray-200 rounded-lg px-3 py-2"
            placeholder="从百度 AI Studio 获取"
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">模型</label>
          <select
            v-model="ocr.model"
            class="w-full border border-gray-200 rounded-lg px-3 py-2"
          >
            <option v-for="m in modelOptions" :key="m" :value="m">{{ m }}</option>
          </select>
        </div>
      </div>
    </div>

    <!-- LLM 清洗 (RAG) -->
    <div class="bg-white rounded-xl shadow-sm p-6 mb-6">
      <div class="flex items-center justify-between mb-4">
        <h2 class="font-semibold">LLM 清洗（RAG 增强）</h2>
        <label class="flex items-center gap-2 text-sm">
          <input v-model="llm.enabled" type="checkbox" />
          启用
        </label>
      </div>
      <div class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">Base URL</label>
          <input
            v-model="llm.base_url"
            class="w-full border border-gray-200 rounded-lg px-3 py-2"
            placeholder="如 https://api.deepseek.com/v1"
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">API Key</label>
          <input
            v-model="llm.api_key"
            type="password"
            class="w-full border border-gray-200 rounded-lg px-3 py-2"
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">模型</label>
          <input
            v-model="llm.model"
            class="w-full border border-gray-200 rounded-lg px-3 py-2"
            placeholder="如 deepseek-chat"
          />
        </div>
        <p class="text-xs text-gray-400">
          启用后，OCR 识别结果会通过 LLM 清洗为结构化错题，自动填充表单。未配置时直接使用 OCR 原始输出。
        </p>
      </div>
    </div>

    <div class="flex items-center gap-3">
      <button
        :disabled="saving"
        class="px-6 py-2 bg-brand-600 text-white rounded-lg hover:bg-brand-700 disabled:opacity-50"
        @click="save"
      >
        {{ saving ? "保存中…" : "保存设置" }}
      </button>
      <span v-if="saved" class="text-green-500 text-sm">已保存 ✓</span>
    </div>
  </div>
</template>