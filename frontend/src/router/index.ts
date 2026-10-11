import { createRouter, createWebHistory, type RouterHistory } from "vue-router";
import TaxonomyPage from "../pages/TaxonomyPage.vue";
import QuestionBankPage from "../pages/QuestionBankPage.vue";
import QuestionDetailPage from "../pages/QuestionDetailPage.vue";
import PracticeSetupPage from "../pages/PracticeSetupPage.vue";
import PracticeSessionPage from "../pages/PracticeSessionPage.vue";
import ProgressPage from "../pages/ProgressPage.vue";
import ProjectsPage from "../pages/ProjectsPage.vue";
import ProjectDetailPage from "../pages/ProjectDetailPage.vue";
import MaterialsPage from "../pages/MaterialsPage.vue";
import SettingsPage from "../pages/SettingsPage.vue";
import InboxPage from "../pages/InboxPage.vue";
import DashboardPage from "../pages/DashboardPage.vue";
import MockInterviewSetupPage from "../pages/MockInterviewSetupPage.vue";
import MockInterviewRoomPage from "../pages/MockInterviewRoomPage.vue";
import MockInterviewSavedPage from "../pages/MockInterviewSavedPage.vue";

export function createAppRouter(history: RouterHistory = createWebHistory()) {
  return createRouter({
    history,
    routes: [
      { path: "/", name: "home", redirect: "/dashboard" },
      { path: "/dashboard", name: "dashboard", component: DashboardPage },
      { path: "/questions", name: "question-bank", component: QuestionBankPage },
      { path: "/questions/:id", name: "question-detail", component: QuestionDetailPage },
      { path: "/taxonomy", name: "taxonomy", component: TaxonomyPage },
      { path: "/inbox", name: "inbox", component: InboxPage },
      { path: "/projects", name: "projects", component: ProjectsPage },
      { path: "/projects/:id", name: "project-detail", component: ProjectDetailPage },
      { path: "/materials", name: "materials", component: MaterialsPage },
      { path: "/settings", name: "settings", component: SettingsPage },
      { path: "/progress", name: "progress", component: ProgressPage },
      { path: "/practice", name: "practice-setup", component: PracticeSetupPage },
      { path: "/practice/sessions/:id", name: "practice-session", component: PracticeSessionPage },
      { path: "/mock-interview", name: "mock-interview", component: MockInterviewSetupPage },
      { path: "/mock-interview/room/:sessionId", name: "mock-interview-room", component: MockInterviewRoomPage },
      { path: "/mock-interview/saved/:id", name: "mock-interview-saved", component: MockInterviewSavedPage },
    ],
  });
}

export const router = createAppRouter();
