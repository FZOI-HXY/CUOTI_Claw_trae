<script setup lang="ts">
import { onMounted, ref } from "vue";
import * as api from "../lib/api";
import type { LlmConfig } from "../lib/types";

const llm = ref<LlmConfig>({
  base_url: "",
  api_key: "",
  model: "",
  enabled: false,
});
const saving = ref(false);
const saved = ref(false);

async function load() {
  llm.value = await api.getLlmConfig();
}

async function save() {
  saving.value = true;
  saved.value = false;
  try {
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

    <!-- AI 识别（多模态 LLM） -->
    <div class="bg-white rounded-xl shadow-sm p-6 mb-6">
      <div class="flex items-center justify-between mb-4">
        <h2 class="font-semibold">AI 识别（多模态 LLM）</h2>
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
            placeholder="如 https://open.bigmodel.cn/api/paas/v4"
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
            placeholder="如 glm-4.5-air"
          />
        </div>
        <p class="text-xs text-gray-400">
          启用后，可通过「AI 识别」把图片直接交给多模态大模型识别，自动填充错题表单。
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