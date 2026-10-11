<script setup lang="ts">
import { computed, onMounted, ref, shallowRef, watch } from "vue";
import { RouterLink, RouterView, useRoute } from "vue-router";
import { ApiError, request } from "./api/client";
import WorkspaceIcon from "./components/WorkspaceIcon.vue";

const healthStatus = ref("checking");
const route = useRoute();
const mobileMenuOpen = shallowRef(false);
const navigation = [
  {to:"/dashboard",label:"工作台",icon:"dashboard",hint:"今日待办"},
  {to:"/questions",label:"题库",icon:"bank",hint:"知识与证据"},
  {to:"/inbox",label:"截图收件箱",icon:"inbox",hint:"采集与审核"},
  {to:"/taxonomy",label:"分类管理",icon:"taxonomy",hint:"Topic 与 Tag"},
  {to:"/practice",label:"练习",icon:"practice",hint:"组织与表达"},
  {to:"/mock-interview",label:"模拟面试",icon:"interview",hint:"AI 文本追问"},
  {to:"/progress",label:"学习进度",icon:"progress",hint:"复习与薄弱知识点"},
  {to:"/projects",label:"项目经历",icon:"projects",hint:"事实与版本"},
  {to:"/materials",label:"资料库",icon:"materials",hint:"文档与上下文"},
  {to:"/settings",label:"设置",icon:"settings",hint:"模型、备份与恢复"},
] as const;
const activePath = computed(() => route.path.startsWith('/questions') ? '/questions' : navigation.find(n => n.to !== '/dashboard' && route.path.startsWith(n.to))?.to ?? '/dashboard');
const healthLabel = computed(() => healthStatus.value === 'ok' ? '后端已连接' : healthStatus.value === 'checking' ? '正在检查连接' : '后端暂不可用');

watch(() => route.fullPath, () => { mobileMenuOpen.value = false; });

onMounted(async () => {
  try {
    const response = await request<{ status: string }>("/api/v1/health");
    healthStatus.value = response.status;
  } catch (error) {
    healthStatus.value = error instanceof ApiError ? "unavailable" : "error";
  }
});
</script>

<template>
  <a class="skip-link" href="#workspace-content">跳至主要内容</a>
  <div class="app-shell">
    <aside class="workspace-sidebar" :class="{'mobile-menu-open': mobileMenuOpen}">
      <div class="workspace-brand"><span class="brand-mark"><WorkspaceIcon name="brand" /></span><div><h1>Agent Interview Workspace</h1><p>面试知识工作台</p></div></div>
      <button class="mobile-menu-toggle" type="button" :aria-expanded="mobileMenuOpen" aria-controls="workspace-navigation" @click="mobileMenuOpen = !mobileMenuOpen">{{ mobileMenuOpen ? '收起菜单' : '打开菜单' }}</button>
      <p class="nav-caption">工作空间</p>
      <nav id="workspace-navigation" aria-label="主导航">
        <RouterLink v-for="item in navigation" :key="item.to" :to="item.to" :class="{'nav-selected':activePath === item.to}" :aria-current="activePath === item.to ? 'page' : undefined">
          <WorkspaceIcon :name="item.icon" /><span><strong>{{ item.label }}</strong><small>{{ item.hint }}</small></span>
        </RouterLink>
      </nav>
      <div class="workspace-connection" role="status" :data-connected="healthStatus === 'ok'"><span class="connection-dot" />{{ healthLabel }}<small>本地个人工作空间</small></div>
    </aside>
    <main id="workspace-content" class="workspace-content" tabindex="-1"><RouterView /></main>
  </div>
</template>
