<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter, useRoute } from "vue-router";
import { open } from "@tauri-apps/plugin-dialog";
import { readFile } from "@tauri-apps/plugin-fs";
import * as api from "../lib/api";
import { useMetaStore } from "../stores/meta";
import type {
  CleanedQuestion,
  Question,
  QuestionInput,
  Subject,
  QuestionType,
} from "../lib/types";

const router = useRouter();
const route = useRoute();
const meta = useMetaStore();
const id = route.params.id ? Number(route.params.id) : null;
const isNew = id == null;

const form = ref<QuestionInput>({
  subject_id: 0,
  chapter_id: null,
  qtype: "single",
  title: "",
  options: [],
  answer: "",
  analysis: "",
  difficulty: 3,
  status: "not_mastered",
  notes: "",
  is_favorite: false,
  image_path: "",
  source: "",
  wrong_reason: "",
  tags: [],
});
const tagsInput = ref("");
const optionsText = ref("");
const ocrText = ref("");
const ocrLoading = ref(false);
const saving = ref(false);

const difficultyOptions = [
  { value: 1, label: "1（最简单）" },
  { value: 2, label: "2" },
  { value: 3, label: "3" },
  { value: 4, label: "4" },
  { value: 5, label: "5（最难）" },
];

async function fillFromCleaned(c: CleanedQuestion) {
  if (c.qtype) form.value.qtype = c.qtype;
  if (c.title) form.value.title = c.title;
  if (c.options) {
    form.value.options = c.options;
    optionsText.value = c.options.join("\n");
  }
  if (c.answer) form.value.answer = c.answer;
  if (c.analysis) form.value.analysis = c.analysis;
  if (c.difficulty) form.value.difficulty = c.difficulty;
  if (c.tags) form.value.tags = c.tags;
}

async function handleFileSelect() {
  const file = await open({
    multiple: false,
    filters: [{ name: "图片", extensions: ["jpg", "jpeg", "png", "webp"] }],
  });
  if (!file) return;
  ocrLoading.value = true;
  try {
    const data = await readFile(file.path);
    const result = await api.recognizeImage(Array.from(data), file.name);
    ocrText.value = result.raw_text;
    if (result.cleaned) {
      fillFromCleaned(result.cleaned);
    }
  } catch (e) {
    alert(`OCR 识别失败: ${e}`);
  } finally {
    ocrLoading.value = false;
  }
}

async function submit() {
  if (!form.value.title.trim()) {
    alert("请输入题干");
    return;
  }
  if (form.value.subject_id === 0) {
    alert("请选择科目");
    return;
  }
  // 拆分标签与选项输入
  form.value.tags = tagsInput.value
    .split(/[,\n]/)
    .map((s) => s.trim())
    .filter(Boolean);
  form.value.options = optionsText.value
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
  saving.value = true;
  try {
    if (isNew) {
      await api.createQuestion(form.value);
    } else {
      await api.updateQuestion(id!, form.value);
    }
    router.push("/questions");
  } catch (e) {
    alert(`保存失败: ${e}`);
  } finally {
    saving.value = false;
  }
}

function addTag(tag: string) {
  if (!tag.trim() || form.value.tags?.includes(tag)) return;
  form.value.tags = [...(form.value.tags || []), tag.trim()];
  tagsInput.value = "";
}

function removeTag(i: number) {
  form.value.tags?.splice(i, 1);
}

onMounted(async () => {
  if (!isNew) {
    const q = await api.getQuestion(id!);
    form.value = {
      ...q,
      options: q.options ? JSON.parse(q.options) : [],
    };
    optionsText.value = q.options ? JSON.parse(q.options).join("\n") : "";
    tagsInput.value = q.tags ? q.tags.join(", ") : "";
    if (q.subject_id) {
      await meta.loadChapters(q.subject_id);
    }
  }
});
</script>

<template>
  <div class="max-w-3xl mx-auto p-6">
    <h1 class="text-2xl font-bold mb-6">
      {{ isNew ? "新增错题" : "编辑错题" }}
    </h1>

    <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">科目</label>
        <select
          v-model="form.subject_id"
          class="w-full border border-gray-200 rounded-lg px-3 py-2"
          @change="meta.loadChapters(form.subject_id)"
        >
          <option :value="0">请选择科目</option>
          <option v-for="s in meta.subjects" :key="s.id" :value="s.id">{{ s.name }}</option>
        </select>
      </div>
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">知识点</label>
        <select
          v-model="form.chapter_id"
          class="w-full border border-gray-200 rounded-lg px-3 py-2"
        >
          <option :value="null">无/顶级</option>
          <option
            v-for="c in meta.chapters[form.subject_id || 0] || []"
            :key="c.id"
            :value="c.id"
          >
            {{ c.name }}
          </option>
        </select>
      </div>
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">题型</label>
        <select v-model="form.qtype" class="w-full border border-gray-200 rounded-lg px-3 py-2">
          <option value="single">单选</option>
          <option value="multiple">多选</option>
          <option value="judge">判断</option>
          <option value="fill">填空</option>
          <option value="answer">解答</option>
        </select>
      </div>
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">难度</label>
        <select
          v-model="form.difficulty"
          class="w-full border border-gray-200 rounded-lg px-3 py-2"
        >
          <option v-for="opt in difficultyOptions" :key="opt.value" :value="opt.value">
            {{ opt.label }}
          </option>
        </select>
      </div>
    </div>

    <div class="mb-4">
      <div class="flex items-center justify-between mb-1">
        <label class="block text-sm font-medium text-gray-700">题干</label>
        <button
          :disabled="ocrLoading"
          class="px-3 py-1 text-sm bg-brand-50 text-brand-600 rounded hover:bg-brand-100"
          @click="handleFileSelect"
        >
          {{ ocrLoading ? "识别中…" : "📷 OCR 识别" }}
        </button>
      </div>
      <textarea
        v-model="form.title"
        rows="3"
        class="w-full border border-gray-200 rounded-lg px-3 py-2"
        placeholder="输入题干…"
      />
    </div>

    <div class="mb-4">
      <label class="block text-sm font-medium text-gray-700 mb-1">选项（每行一个）</label>
      <textarea
        v-model="optionsText"
        rows="4"
        class="w-full border border-gray-200 rounded-lg px-3 py-2"
        placeholder="A. xxx&#10;B. xxx"
      />
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">正确答案</label>
        <input
          v-model="form.answer"
          class="w-full border border-gray-200 rounded-lg px-3 py-2"
        />
      </div>
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1">来源</label>
        <input
          v-model="form.source"
          class="w-full border border-gray-200 rounded-lg px-3 py-2"
          placeholder="试卷名称/页码"
        />
      </div>
    </div>

    <div class="mb-4">
      <label class="block text-sm font-medium text-gray-700 mb-1">解析</label>
      <textarea
        v-model="form.analysis"
        rows="4"
        class="w-full border border-gray-200 rounded-lg px-3 py-2"
      />
    </div>

    <div class="mb-4">
      <label class="block text-sm font-medium text-gray-700 mb-1">标签（逗号分隔）</label>
      <div class="flex flex-wrap gap-2 mb-2">
        <span
          v-for="(tag, i) in form.tags"
          :key="i"
          class="px-2 py-1 bg-gray-100 rounded text-sm flex items-center gap-1"
        >
          {{ tag }}
          <button class="text-gray-400 hover:text-red-500" @click="removeTag(i)">×</button>
        </span>
      </div>
      <input
        v-model="tagsInput"
        class="w-full border border-gray-200 rounded-lg px-3 py-2"
        placeholder="输入后回车添加"
        @keyup.enter="addTag(tagsInput.value)"
      />
    </div>

    <div class="mb-4">
      <label class="block text-sm font-medium text-gray-700 mb-1">错题原因</label>
      <textarea
        v-model="form.wrong_reason"
        rows="2"
        class="w-full border border-gray-200 rounded-lg px-3 py-2"
      />
    </div>

    <div class="mb-4">
      <label class="block text-sm font-medium text-gray-700 mb-1">笔记</label>
      <textarea
        v-model="form.notes"
        rows="2"
        class="w-full border border-gray-200 rounded-lg px-3 py-2"
      />
    </div>

    <div class="flex items-center gap-3 mb-6">
      <label class="flex items-center gap-2">
        <input v-model="form.is_favorite" type="checkbox" />
        <span class="text-sm">收藏 / 重点标记</span>
      </label>
    </div>

    <div v-if="ocrText" class="bg-gray-50 p-3 rounded-lg mb-6 text-sm">
      <div class="font-medium mb-1">OCR 识别结果（原始）：</div>
      <pre class="whitespace-pre-wrap text-gray-600">{{ ocrText }}</pre>
    </div>

    <div class="flex gap-3">
      <button
        :disabled="saving"
        class="px-6 py-2 bg-brand-600 text-white rounded-lg hover:bg-brand-700 disabled:opacity-50"
        @click="submit"
      >
        {{ saving ? "保存中…" : "保存" }}
      </button>
      <button
        class="px-6 py-2 border border-gray-200 rounded-lg hover:bg-gray-50"
        @click="router.back()"
      >
        返回
      </button>
    </div>
  </div>
</template>