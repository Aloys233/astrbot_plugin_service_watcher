# 互联网服务状态监控插件 (Service Watcher)

聚合监控 GitHub、OpenAI、Cloudflare 等主流服务的运行状态。通过各服务官方提供的 JSON API 进行轮询，在检测到服务状态异常或恢复时第一时间发送预警推送。

## 功能特性

- ✅ **专业监控**：原生支持 GitHub, OpenAI, Cloudflare 官方状态 API
- ✅ **智能推送**：自动对比状态变化，仅在发生故障或恢复时推送，避免骚扰
- ✅ **主动通知**：状态变化时自动向订阅的会话推送通知
- ✅ **多维指令**：支持一键查询所有服务实时状态
- ✅ **可配置化**：自定义监控频率及推送目标
- ✅ **自动清理**：自动处理 API 返回的复杂格式，输出精简易读的通知

## 配置说明

在 AstrBot 管理面板中配置：

| 配置项                 | 类型   | 默认值     | 说明               |
|:--------------------|:-----|:--------|:-----------------|
| `enable_github`     | bool | `false` | 监控 GitHub 状态     |
| `enable_openai`     | bool | `false` | 监控 OpenAI 状态     |
| `enable_cloudflare` | bool | `false` | 监控 Cloudflare 状态 |
| `check_interval`    | int  | `60`    | 轮询频率（秒）          |
| `notify_targets`    | list | `[]`    | 接收状态变化通知的会话列表    |

## 指令列表

| 指令                   | 说明                    |
|:---------------------|:----------------------|
| `/servicestatus`     | 获取所有已启用服务的当前概览状态      |
| `/servicetest <服务名>` | 强制触发一次指定服务的状态检查（用于调试） |

## 使用方法

1. 在需要接收通知的群聊或私聊中发送 `/sid`（AstrBot 内置命令）获取会话 ID
2. 复制返回的 `unified_msg_origin` 字符串
3. 在 AstrBot 管理面板的插件配置中，将其添加到 `notify_targets` 列表
4. 当监控的服务状态发生变化时，机器人会自动向该会话推送通知

## 状态页参考

- [GitHub Status](https://www.githubstatus.com/)
- [OpenAI Status](https://status.openai.com/)
- [Cloudflare Status](https://www.cloudflarestatus.com/)

## 开发者相关

- 基于 [AstrBot](https://github.com/Soulter/AstrBot) 插件框架
- 支持 [AstrBot 插件开发规范](https://docs.astrbot.app/dev/star/plugin-new.html)
- 如需添加更多服务，请修改 `lib/services.py` 中的 `AVAILABLE_SERVICES` 并在 `_conf_schema.json` 中添加对应开关
