import { defineComponent, h } from "vue";
import { createRouter, createWebHistory, type RouterHistory } from "vue-router";
import TaxonomyPage from "../pages/TaxonomyPage.vue";

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
      { path: "/", name: "home", component: HomePlaceholder },
      { path: "/taxonomy", name: "taxonomy", component: TaxonomyPage },
    ],
  });
}

export const router = createAppRouter();
