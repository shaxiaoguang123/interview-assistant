import { defineComponent, h } from "vue";
import { createRouter, createWebHistory, type RouterHistory } from "vue-router";
import TaxonomyPage from "../pages/TaxonomyPage.vue";
import QuestionBankPage from "../pages/QuestionBankPage.vue";
import QuestionDetailPage from "../pages/QuestionDetailPage.vue";
import PracticeSetupPage from "../pages/PracticeSetupPage.vue";
import PracticeSessionPage from "../pages/PracticeSessionPage.vue";
import ProgressPage from "../pages/ProgressPage.vue";
import InboxPage from "../pages/InboxPage.vue";

const HomePlaceholder = defineComponent({
  name: "HomePlaceholder",
  setup() {
    return () => h("section", { "aria-label": "题库" }, [h("p", "题库页面即将启用")]);
  },
});

export function createAppRouter(history: RouterHistory = createWebHistory()) {
  return createRouter({
    history,
    routes: [
      { path: "/", name: "home", component: QuestionBankPage },
      { path: "/questions/:id", name: "question-detail", component: QuestionDetailPage },
      { path: "/taxonomy", name: "taxonomy", component: TaxonomyPage },
      { path: "/inbox", name: "inbox", component: InboxPage },
      { path: "/progress", name: "progress", component: ProgressPage },
      { path: "/practice", name: "practice-setup", component: PracticeSetupPage },
      { path: "/practice/sessions/:id", name: "practice-session", component: PracticeSessionPage },
    ],
  });
}

export const router = createAppRouter();
