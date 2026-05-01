### 本插件停用

```markdown
### 📢 AstrBot 广播插件 

[![AstrBot](https://img.shields.io/badge/AstrBot-插件-brightgreen)](https://github.com/Soulter/AstrBot)
[![Version](https://img.shields.io/badge/version-2.0.0-blue)](./metadata.yaml)
[![License](https://img.shields.io/badge/license-MIT-green)](./LICENSE)

功能强大的机器人广播插件，支持私聊向全部群或指定群发送消息、定时广播、@全体成员、黑名单过滤、权限管理、Markdown / 图片消息、消息撤回、超长文本自动分段、广播历史记录等。

---

## ✨ 功能特性

- 🚀 **私聊专用** 所有指令仅在私聊中生效，避免群聊误触发。
- 📣 **全群 / 指定群广播** 一键将消息发送到所有已加入的群聊或手动指定群号。
- ⏰ **定时广播** 通过 WebUI 配置 Cron 表达式，自动定时发送广播，并可指定目标群。
- 📌 **@全体成员** 支持自动在广播消息前添加 @all（需群权限支持）。
- 🚫 **黑名单** 可设置不接收广播的群，自动跳过。
- 🔐 **权限控制** 限定只有特定用户 ID 才能使用广播命令。
- 📝 **Markdown / 图片** 支持 `[MD]` 前缀发送 Markdown 消息，`[img:url]` 嵌入图片。
- ↩️ **消息撤回** 可撤回最近广播到特定群的消息（依赖平台接口）。
- 📜 **广播日志** 记录每次广播的目标、内容、结果，支持随时查询。
- 📏 **自动分段** 超长纯文本自动按设定长度拆分发送并标记进度。

---

## 📦 安装方法

1. 将本插件文件夹放入 AstrBot 的 `plugins` 目录下。
2. 确保已安装依赖：
   ```bash
   pip install apscheduler>=3.9.0
```

1. 重启 AstrBot 或在 WebUI 插件管理中点击 重载插件。

---

🛠 使用指令

⚠️ 所有指令仅限私聊使用。

指令 说明 示例
/broadcast_all <文本> 向 Bot 加入的全部群发送广播 /broadcast_all 晚上开会哦~

/broadcast_to <群号> <文本> 向指定群（多个用逗号分隔）发送广播 /broadcast_to 123456,789012 大家好

/broadcast_status 查看定时广播状态 /broadcast_status

/broadcast_pause 暂停定时广播 /broadcast_pause

/broadcast_resume 恢复定时广播 /broadcast_resume

/broadcast_log [条数] 查看最近广播历史 /broadcast_log 5

/broadcast_recall <群号> 撤回该群最近一条广播 /broadcast_recall 123456

/broadcast_help 显示帮助信息 /broadcast_help

---

🎨 高级内容格式

· Markdown 消息
    若在 WebUI 开启了 enable_markdown，且群平台支持，可使用 [MD] 开头发送 Markdown 格式：
  ```
  /broadcast_all [MD]# 标题\n**重要通知**\n请大家及时查看。
  ```
· 图片插入
    在文本中任意位置使用 [img:图片URL] 即可发送图片：
  ```
  /broadcast_to 123456 这是今天的海报 [img:https://example.com/pic.jpg]
  ```
· @全体成员
    在配置中打开 use_at_all 后，所有广播消息将自动在开头附上 @all（需群主/管理员权限）。

---

⚙️ WebUI 配置项说明

在 AstrBot 管理界面 → 插件配置中找到本插件，可配置以下参数：

配置项 类型 说明
group_overrides 字符串 手动指定广播目标群 ID 列表（逗号分隔），留空时尝试自动获取
blacklist_groups 字符串 广播黑名单群 ID，逗号分隔
cron_expr 字符串 定时广播的 Cron 表达式，如 0 9 * * * 表示每天 9:00
cron_text 文本 定时广播内容，支持高级格式
cron_target_groups 字符串 定时广播专属目标群，留空则使用 group_overrides
platform_name 字符串 用于定时广播的平台标识，默认 aiocqhttp
use_at_all 布尔 是否在广播开头 @全体成员
enable_markdown 布尔 是否允许以 [MD] 开头的 Markdown 消息
allowed_users 字符串 允许使用广播指令的用户 ID，逗号分隔（空为不限）
max_message_length 整数 超长纯文本自动分段的长度阈值，默认 500 字符
max_log_entries 整数 最多保留的历史记录条数，默认 100

---

📂 文件结构

```
astrbot_plugin_broadcast/
├── main.py              # 插件主程序
├── metadata.yaml        # 插件元数据
├── _conf_schema.json    # WebUI 配置界面定义
├── requirements.txt     # 依赖声明
└── README.md            # 本说明文档
```

广播日志文件将自动保存在 data/astrbot_plugin_broadcast/broadcast_log.json。

---

❓ 常见问题

Q: 为什么群聊里发指令没反应？
A: 所有广播指令仅在私聊下生效，请私聊机器人使用。

Q: 提示“未获取到任何群聊”怎么办？
A: 请在 WebUI 配置中填写 group_overrides，手动输入你要广播的群号。

Q: 撤回功能无效？
A: 撤回需要平台适配器支持返回消息 ID 并提供撤回接口，且消息未过期（通常 2 分钟内）。如果平台不支持，该功能会返回失败提示。

Q: 定时广播怎么停止？
A: 清空 cron_expr 配置并保存，或使用 /broadcast_pause 暂停，重载插件即可彻底停止调度器。

Q: Markdown 消息不显示效果？
A: 请确认平台适配器已实现 Markdown 组件，并在 WebUI 中开启 enable_markdown。

---
