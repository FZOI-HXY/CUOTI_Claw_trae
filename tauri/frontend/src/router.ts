import { createRouter, createWebHashHistory } from "vue-router";
import { defineAsyncComponent } from "vue";

// 路由级懒加载：首屏只加载当前页面组件
const QuestionList = defineAsyncComponent(() => import("./views/QuestionList.vue"));
const QuestionDetail = defineAsyncComponent(() => import("./views/QuestionDetail.vue"));
const Review = defineAsyncComponent(() => import("./views/Review.vue"));
const Statistics = defineAsyncComponent(() => import("./views/Statistics.vue"));
const Settings = defineAsyncComponent(() => import("./views/Settings.vue"));

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: "/", redirect: "/questions" },
    { path: "/questions", component: QuestionList },
    { path: "/questions/new", component: QuestionDetail },
    { path: "/questions/:id/edit", component: QuestionDetail },
    { path: "/review", component: Review },
    { path: "/statistics", component: Statistics },
    { path: "/settings", component: Settings },
  ],
});

export default router;