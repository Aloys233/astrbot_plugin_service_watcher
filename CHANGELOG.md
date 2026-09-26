<!-- markdownlint-disable MD024 -->
<!-- markdownlint-disable MD025 -->
<!-- markdownlint-disable MD028 -->
<!-- markdownlint-disable MD033 -->
<!-- markdownlint-disable MD034 -->
<!-- markdownlint-disable MD041 -->
# ChangeLog

# 2026/09/26 v0.5.0

## 🚀 What's Changed

### ✨ New Features (新功能)

- 新增 **AI 翻译** 功能，可将状态通知中的英文内容（事件标题、说明、计划维护名称等）自动翻译为中文 by @Aloys233
  - 支持通过 `启用 AI 翻译` 配置项开启（默认关闭），并通过 `翻译使用的模型提供商` 在 WebUI 中手动选择用于翻译的 LLM 提供商
  - 走 AstrBot 标准的 `llm_generate` 调用方式，与 WebUI 中已配置的模型提供商无缝集成
  - 内置 **原文 → 译文** 缓存：未变化的内容只在首次通知时翻译一次，之后全部命中缓存，不产生额外的模型调用开销
  - 纯中文与 URL 文本自动跳过翻译；单次通知最多翻译 20 条文本，单条 30 秒超时
  - 翻译失败或未配置提供商时自动降级为原文推送，不影响通知的送达
  - `/servicetest` 指令同样支持翻译预览

### 🛠 Improvements (改进)

- **状态变更通知改为差异优先输出**：修复了以往通知只输出全量状态快照、两次通知几乎一模一样、无法一眼看出到底变了什么的问题 by @Aloys233
  - 通知现在优先展示 `📌 本次变化` 区块，包括：🆕 新增事件、✅ 事件已解决、🔄 事件状态/影响/最新说明更新、🔧 计划维护新增/取消/状态变化
  - 未变化的部分合并为一行汇总（如 `✅ 无变化: 其余 2 个事件、计划维护 25 项`），不再整页复读
  - 支持 StatusPage 与阿里云两类数据源；升级后首次变化仍为全量格式（暂无历史快照可比对），此后自动切换为差异格式

### 🔧 Chore (杂项)

- 新增持久化状态快照存储，用于差异比对，与原有的状态签名同生命周期 by @Aloys233
- 新增 `lib/diff.py`（快照差异比对）与 `lib/translator.py`（AI 翻译）模块 by @Aloys233
- 插件版本号更新至 v0.5.0 by @Aloys233

**Full Changelog**: https://github.com/Aloys233/astrbot_plugin_service_watcher/compare/v0.4.0...v0.5.0

<details>
<summary>点击查看历史更新内容</summary>

# 2026/09/25 v0.4.0

## 🚀 What's Changed

### ✨ New Features (新功能)

- 新增国内服务监控：Moonshot AI (Kimi)、阿里云、哔哩哔哩、微信公众平台、QQ 机器人开放平台等
- 新增 HTTP 探测适配器 (probe)：适用于没有官方状态页的服务，任何 HTTP 响应均视为可达，支持 DeepSeek、智谱AI、硅基流动等国内平台
- 新增 WebUI 管理页：支持实时查看各服务状态、管理服务开关、调整检查间隔与通知目标
- 阿里云数据源支持按事件签名检测状态变化，避免漏报事件状态更新

### 🔧 Chore (杂项)

- 插件版本号更新至 v0.4.0

**Full Changelog**: https://github.com/Aloys233/astrbot_plugin_service_watcher/compare/v0.2.0...v0.4.0

# 2026/03/12 v0.2.0

## 🚀 What's Changed

### ✨ New Features (新功能)

- 新增 Steam (SteamStat.us) 服务适配器，支持监控 Steam Web API 等服务的负载状态
- 服务列表新增 `ai_services` 分组（OpenAI）

### 🔧 Chore (杂项)

- 插件版本号更新至 v0.2.0

**Full Changelog**: https://github.com/Aloys233/astrbot_plugin_service_watcher/compare/v0.1.0...v0.2.0

# 2026/01/26 v0.1.0

## 🚀 首个发布版本

- **多数据源支持**：StatusPage.io 状态页、RSS/Atom 订阅、阿里云状态 API、SteamStat.us、HTTP 探测
- **状态变更检测**：基于签名的多维度变更检测（整体指标、事件状态/影响/更新内容、计划维护状态）
- **状态变更推送**：检测到变化时自动推送到配置的会话列表
- **查询指令**：`/servicestatus` 查询所有服务状态、`/servicetest` 测试单个服务的监控
- **状态翻译**：内置 StatusPage 常见整体状态描述的中文翻译
- **WebUI 状态页**：内置 dashboard 页面，可视化查看各服务实时状态

</details>
