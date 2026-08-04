import { createRouter, createWebHashHistory } from "vue-router";
import QuestionList from "./views/QuestionList.vue";
import QuestionDetail from "./views/QuestionDetail.vue";
import Review from "./views/Review.vue";
import Statistics from "./views/Statistics.vue";
import Settings from "./views/Settings.vue";

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