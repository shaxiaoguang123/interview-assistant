# Agent Interview Workspace — 面试知识工作台

本轮已授权的前端升级设计；沿用 Flask / Vue 3 / SQLite 与既有四个入口。

## 视觉体系

- 画布 `#f4f6fa`，工作区 `#ffffff`；正文 `#172b4d`，辅助文字 `#526277`，边框 `#d9e1ec`。
- 品牌/主操作 `#087f8c`，悬停 `#066672`，选中底色 `#e7f5f5`；警告 `#854d0e` / `#fff8e8`，危险 `#b42338` / `#fff1f3`，成功 `#12624b` / `#eaf7f0`。
- 不依赖远程字体：system-ui、-apple-system、Segoe UI、PingFang SC、Microsoft YaHei。代码/ID 用系统等宽字体。
- 页面标题 28px/1.3，区域标题 18px/1.4，正文 15px/1.65，辅助文字 13px/1.5；移动页面标题 24px。
- 8px 间距体系：8 / 16 / 24 / 32 / 48px；局部图标与细节可用 4px。面板圆角 12px、控件 8px，避免装饰性大阴影和渐变。
- 控件至少 44px 高；按钮提供 hover、focus-visible、disabled、busy 反馈。焦点环 3px，颜色不作为唯一状态提示。

## 布局

- Desktop：224px 固定宽度侧栏；主区域最大 1440px、24–40px 内边距。导航有统一线性 SVG 图标、当前入口高亮和连接状态。
- 1024px 以下：导航切换顶部布局，内容单栏。768px 以下：紧凑品牌、可换行四入口导航、16px 内容内边距，不用遮挡内容的固定浮层。
- 题库：标题/新增操作 → 搜索 → 可展开筛选 → 实际结果数 → 正文优先的题目行。新增表单为独立区域。
- Inbox：上传与历史在左侧，选中 Job、候选审核在中间，来源证据在右侧（宽屏）；较窄桌面为历史+审核两栏，证据顺序跟随编辑；移动全部单栏。
- 详情：正文/分类/组级状态 → 编辑区 → 相似审核 → 来源与聚合历史。历史标记原始 Question ID；child 原始详情只读并提供 canonical 链接。
- 练习：设置采用聚焦宽度；会话显示真实进度、当前题、临时回答和四级自评；队列作为次要区域。
- 分类：Topic/Tag 分区；Topic 层级缩进有上限，名称、slug、父级和操作可换行；新增与已有编辑分开。

## 轻量组件边界

- `WorkspaceIcon`：仅渲染四类导航与品牌的线性图标，无网络/依赖。
- `App.vue`：导航、连接状态、主内容与跳转焦点入口。
- `QuestionHistory`：呈现来源、Review、SessionItem；props 为完整 history，emit 选择来源和更正自评，保留历史 ID。
- 既有 QuestionForm、TopicTagPicker、QuestionRelationReview、IngestionCandidateEditor、SourceImageViewer：沿用 props/emits，统一样式；来源缩放与坐标算法不重写。
- 路由页保留既有 API/状态流程；仅在需要 grouped history 与安全请求生命周期处调整。

## 交互与范围

- 清楚区分建议、待处理、已排除、已确认、错误；Confirm 门禁原因可见。
- 显式说明取消收藏/错题作用于整个归并组。详情 history 加载失败可重试，不冒充空历史。
- 保留 aria-label 与语义 HTML；多选提供操作说明，不隐藏键盘焦点；尊重 prefers-reduced-motion。
- Task 6 Merge Dialog 与路由归并工作流不实施；无统计假数据、无新导航、无框架/字体依赖。

## 验收

Native + TDD 验证 history/state/navigation；iab 真实操作全部主要页面；1440×900、1280×800、768×1024、390×844、375×812 两轮截图和宽度/焦点/来源坐标检查。
证据保存在 Git 忽略的 browser-task5-qa 目录；合成截图 ZIP 不包含 DB、模型、Profile、环境文件或用户数据。

## Skill 决策

ui-ux-pro-max 提供 Flat Design、焦点、触控与密度建议；两次设计系统查询的 marketing landing pattern 不适合本地工具，未使用该页面结构或远程字体建议。采用用户明确要求的知识工作台布局和本地字体。Vue 保持 Composition API / script setup / TypeScript。
