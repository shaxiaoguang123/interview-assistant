import { defineComponent, h } from "vue";
import { createRouter, createWebHistory, type RouterHistory } from "vue-router";
import TaxonomyPage from "../pages/TaxonomyPage.vue";
import QuestionBankPage from "../pages/QuestionBankPage.vue";
import QuestionDetailPage from "../pages/QuestionDetailPage.vue";

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
    ],
  });
}

export const router = createAppRouter();
