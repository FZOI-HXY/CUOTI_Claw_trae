<script setup lang="ts">
import { onMounted } from "vue";
import { useMetaStore } from "./stores/meta";

const meta = useMetaStore();
onMounted(() => meta.loadAll());
</script>

<template>
  <div class="flex h-full">
    <aside class="w-56 shrink-0 bg-white border-r border-gray-200 flex flex-col">
      <div class="px-4 py-4 font-bold text-lg text-brand-600 border-b border-gray-100">
        错题本
      </div>
      <nav class="flex-1 p-3 space-y-1">
        <RouterLink
          to="/questions"
          class="block px-3 py-2 rounded-md text-sm hover:bg-gray-100"
          active-class="bg-brand-50 text-brand-600 font-medium"
        >
          错题列表
        </RouterLink>
        <RouterLink
          to="/questions/new"
          class="block px-3 py-2 rounded-md text-sm hover:bg-gray-100"
          active-class="bg-brand-50 text-brand-600 font-medium"
        >
          新增错题
        </RouterLink>
        <RouterLink
          to="/review"
          class="block px-3 py-2 rounded-md text-sm hover:bg-gray-100"
          active-class="bg-brand-50 text-brand-600 font-medium"
        >
          复习模式
        </RouterLink>
        <RouterLink
          to="/statistics"
          class="block px-3 py-2 rounded-md text-sm hover:bg-gray-100"
          active-class="bg-brand-50 text-brand-600 font-medium"
        >
          统计
        </RouterLink>
        <RouterLink
          to="/assistant"
          class="block px-3 py-2 rounded-md text-sm hover:bg-gray-100"
          active-class="bg-brand-50 text-brand-600 font-medium"
        >
          AI 问答
        </RouterLink>
        <RouterLink
          to="/settings"
          class="block px-3 py-2 rounded-md text-sm hover:bg-gray-100"
          active-class="bg-brand-50 text-brand-600 font-medium"
        >
          设置
        </RouterLink>
      </nav>
    </aside>
    <main class="flex-1 overflow-auto">
      <RouterView />
    </main>
  </div>
</template>