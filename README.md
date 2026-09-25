# 互联网服务状态监控插件 (Service Watcher)

聚合监控 GitHub、OpenAI、Cloudflare、阿里云、Moonshot AI 等国内外主流服务的运行状态。通过各服务官方提供的 JSON API 进行轮询，在检测到服务状态异常或恢复时第一时间发送预警推送。

## 功能特性

- ✅ **专业监控**：原生支持 StatusPage.io 架构的官方状态 API（GitHub、OpenAI、Cloudflare、Moonshot AI 等）
- ✅ **国内服务**：支持阿里云事件接口，以及 DeepSeek API、哔哩哔哩、QQ 机器人开放平台等无状态页服务的 HTTP 探测
- ✅ **智能推送**：自动对比状态变化，仅在发生故障或恢复时推送，避免骚扰
- ✅ **主动通知**：状态变化时自动向订阅的会话推送通知
- ✅ **多维指令**：支持一键查询所有服务实时状态
- ✅ **可配置化**：自定义监控频率及推送目标

## 支持的服务类型

| 类型 | 说明 | 适用服务 |
|:-----|:-----|:--------|
| `statuspage` | StatusPage.io 标准 JSON API | GitHub、OpenAI、Cloudflare、Moonshot AI (Kimi) 等 |
| `aliyun` | 阿里云官方事件接口 | 阿里云 |
| `probe` | 通用 HTTP 探测，任何 HTTP 响应视为在线 | DeepSeek API、哔哩哔哩、Steam、QQ 机器人开放平台等 |
| `rss` | RSS/Atom 订阅源 | 提供状态 RSS 的服务 |
| `steamstat` | SteamStat.us JSON（已被 Cloudflare 拦截，保留兼容） | 不推荐 |

> 关于 Steam：SteamStat.us 曾是常用的第三方 Steam 状态源，但现已启用 Cloudflare 人机验证，
> 服务端轮询会收到 403。插件已改用 HTTP 探测 Steam 商店 / 社区 / Web API 域名。

## 配置说明

在 AstrBot 管理面板中按分组开启需要监控的服务（默认全部关闭），主要分组：

| 分组 | 包含服务（示例） |
|:-----|:----------------|
| 国内服务 | Moonshot AI (Kimi)、DeepSeek API、智谱AI、硅基流动、哔哩哔哩、QQ机器人开放平台、微信公众平台、阿里云 |
| AI 服务 | OpenAI |
| 云服务 | Cloudflare、DigitalOcean、Vercel、Linode |
| 开发运维 | GitHub、NPM、PyPI、CircleCI、Sentry、Datadog、Atlassian |
| 通讯社交 | Discord、Reddit、Zoom、Twilio |
| 生产力 | Figma、Dropbox、Trello、Canva |
| 游戏 | Epic Games、Steam 商店/社区/Web API |

| 配置项              | 类型 | 默认值 | 说明                                  |
|:--------------------|:-----|:-------|:--------------------------------------|
| `check_interval`    | int  | `60`   | 轮询频率（秒，最小 10）               |
| `notify_targets`    | list | `[]`   | 接收状态变化通知的会话列表            |
| `service_groups`    | obj  | -      | 各服务监控开关                        |

## 指令列表

| 指令                   | 说明                                   |
|:-----------------------|:---------------------------------------|
| `/servicestatus`       | 获取所有已启用服务的当前概览状态       |
| `/servicetest <服务名>` | 强制触发一次指定服务的状态检查（用于调试），服务名支持配置项标识符（如 `deepseek_api`）或显示名（如 `DeepSeek API`） |

## WebUI 管理页 (Plugin Pages)

插件自带一个 WebUI 页面（`pages/dashboard/`），在 AstrBot 管理面板中打开插件详情页即可进入，提供：

- **概览**：所有已启用服务的实时状态卡片与统计，支持自动刷新，点击卡片可查看故障与维护详情
- **服务管理**：勾选/取消监控的服务开关，保存后立即生效（无需重启）
- **设置**：检查间隔与通知目标列表的可视化编辑

页面支持 WebUI 亮暗主题跟随与中英文切换。需要较新版本的 AstrBot（提供插件 Pages 功能）；旧版本上插件仍可正常工作，仅无此页面。

## 使用方法

1. 在需要接收通知的群聊或私聊中发送 `/sid`（AstrBot 内置命令）获取会话 ID
2. 复制返回的 `unified_msg_origin` 字符串
3. 在 AstrBot 管理面板的插件配置中，将其添加到 `notify_targets` 列表
4. 勾选需要监控的服务
5. 当监控的服务状态发生变化时，机器人会自动向该会话推送通知

## 添加新服务

1. 在 `services.json` 中添加条目：

```json
"example": {
  "name": "显示名称",
  "api_url": "https://...",
  "type": "statuspage"
}
```

2. 在 `_conf_schema.json` 的 `service_groups` 对应分组中添加开关：

```json
"enable_example": {
  "type": "bool",
  "default": false,
  "description": "显示名称"
}
```

无需修改任何 Python 代码。若服务有官方 StatusPage（通常在状态页域名后拼 `/api/v2/summary.json` 验证），直接使用 `statuspage` 类型；否则可用 `probe` 类型探测任意 URL。

## 升级说明

- **v0.2.x → v0.3.0**：状态缓存 key 已按服务类型区分，升级后所有服务会静默重新初始化一次（不会推送误报）；Steam 监控数据源已更换（见上）。

## 开发者相关

- 基于 [AstrBot](https://github.com/Soulter/AstrBot) 插件框架
- 支持 [AstrBot 插件开发规范](https://docs.astrbot.app/dev/star/plugin-new.html)
- 服务定义见 `services.json`，适配器实现见 `lib/adapters.py`
