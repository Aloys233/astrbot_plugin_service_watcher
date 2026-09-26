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

- 新增 **差异通知**：状态变更通知优先展示 `📌 本次变化` 区块（🆕 新增事件、✅ 事件已解决、🔄 状态/影响/说明更新、🔧 维护变化），未变化部分合并为一行汇总，不再整页复读全量状态 by @Aloys233
- 新增 **推送灵敏度三档配置**：`low`（仅 major/critical 级故障与恢复）、`medium`（影响升级+恢复+新增事件）、`high`（全部变化，默认，与旧版一致） by @Aloys233
- 新增 **AI 翻译** 功能，可将通知中的英文内容（事件标题、说明、维护名称等）自动翻译为中文 by @Aloys233
  - 通过 `启用 AI 翻译` 开启（默认关闭），`翻译使用的模型提供商` 在 WebUI 中自选
  - 走 AstrBot 标准的 `llm_generate` 调用；内置译文缓存（未变化内容只翻译一次）、单批 20 条上限、并发限流 5、单条 30s 超时、失败自动降级为原文
  - `/servicetest` 同样支持翻译预览
- 新增 **会话自助订阅指令** `/servicewatch`（仅管理员）：`/servicewatch <服务名|all>` 订阅、`/servicewatch off <服务名|all>` 退订、无参数查看当前会话订阅列表，无需再手动复制会话 ID 填配置 by @Aloys233
- 新增 **计划维护提醒**：维护开始前 N 分钟（可配置，默认 60，0 关闭）自动提醒一次 by @Aloys233
- 新增 **每日状态摘要**（可选）：每天在配置的时间（默认 09:00）推送一次所有服务的状态汇总 by @Aloys233
- 新增 **可用率统计**：自动按天聚合检查结果，支持 7/30 天可用率 by @Aloys233
- 事件/维护状态中文化：通知中 `investigating/monitoring/identified` 等状态显示为 `调查中/监控中/已定位` by @Aloys233

### 💻 WebUI / Frontend (前端)

- Dashboard 新增移动端响应式适配（≤768px 与 ≤480px 断点：卡片网格降列、标签页横滚、弹窗近全屏） by @Aloys233
- 服务卡片与详情弹窗展示 7/30 天可用率 by @Aloys233

### ⚡ Performance / Reliability (性能与可靠性)

- `/status` Web API 新增 30 秒内存缓存，频繁刷新页面不再打爆上游 API by @Aloys233
- 状态检查网络异常自动重试一次（间隔 2 秒） by @Aloys233
- 连续 3 次检查失败的服务自动退避 2 轮后再试，避免高频轰炸故障源 by @Aloys233

### 🔧 Chore (杂项)

- 新增持久化状态快照存储（含整体 indicator），用于差异比对与升降级判定 by @Aloys233
- 新增 `lib/diff.py`、`lib/policy.py`、`lib/subscriptions.py`、`lib/uptime.py`、`lib/text.py` 模块；抽取公共文本处理工具消除重复 by @Aloys233
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
