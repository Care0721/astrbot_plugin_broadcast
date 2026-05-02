###本插件停用
---

```markdown
# AstrBot 广播插件 (astrbot_plugin_broadcast)

[![AstrBot](https://img.shields.io/badge/AstrBot-≥4.17.0-blue)](https://github.com/Soulter/AstrBot)
[![License](https://img.shields.io/badge/license-MIT-green)](./LICENSE)

管理员通过私聊向机器人所在全部群聊或指定群聊发送文字、图片、视频等富媒体广播消息；支持 Web 端可视化配置与定时广播任务。

---

## 功能速览

- 📣 **全群广播**：管理员私聊指令一键向所有群发送广播。
- 🎯 **定向广播**：指定一个或多个群号发送广播，发布通知更灵活。
- 🖼️ **富媒体支持**：文字、图片、视频、本地文件、语音、@全体成员等均可广播。
- 📅 **定时广播**：支持配置多条 cron 定时任务，自动按时发送（如每日早安）。
- 🌐 **Web 面板管理**：在 AstrBot 管理后台可视化编辑管理员、群列表和定时任务。

---

## 安装

1. 将本插件文件夹（`astrbot_plugin_broadcast`）放入 AstrBot 的插件目录下：
```

AstrBot/data/plugins/astrbot_plugin_broadcast/

```
2. 在 AstrBot WebUI 中，进入 **控制台 → 安装 Pip 库**，输入 `apscheduler` 并点击安装。
3. 如果 AstrBot 已运行，可在 WebUI 的 **插件管理** 页面点击 **重载插件**，使插件生效。

---

## 配置项

打开 AstrBot WebUI，进入 **配置 → 插件配置 → 广播插件**，将看到以下配置：

| 配置键 | 类型 | 说明 | 示例 |
|--------|------|------|------|
| `admin_ids` | 字符串 | 管理员 QQ 号，多个用英文逗号分隔 | `123456789,987654321` |
| `group_ids` | 字符串 | 机器人所在的所有群号列表（用于全群广播与定时广播 `"all"` 目标） | `100001,100002,100003` |
| `scheduled_broadcasts` | JSON 字符串 | 定时广播任务配置，见下方说明 | 见下文示例 |

> **重要**：`group_ids` 必须手动填写，否则 `broadcast_all` 和定时广播的 `"all"` 目标无法使用。请确保群号与消息平台一致。

### 定时广播配置示例

```json
[
  {
    "cron": "0 8 * * *",
    "groups": ["all"],
    "message": [
      {"type": "Plain", "data": {"text": "早上好！今天也是充满希望的一天。"}},
      {"type": "Image", "data": {"url": "https://example.com/morning.jpg"}}
    ]
  },
  {
    "cron": "30 21 * * *",
    "groups": ["100001", "100002"],
    "message": [
      {"type": "Plain", "data": {"text": "晚安，明天见！"}}
    ]
  }
]
```

· cron：标准 cron 表达式（分钟 小时 日 月 星期），秒级表达式不支持。
· groups：["all"] 表示所有群；也可写具体群号列表。
· message：消息链数组，组件类型见下表。

支持的富媒体组件类型：

类型 说明 示例 data
Plain 纯文本 {"text": "大家好"}
Image 图片（URL 或本地路径） {"url": "https://.../pic.jpg"} 或 {"file": "/本地/图片.jpg"}
Video 视频 {"url": "https://.../video.mp4"} 或 {"file": "/local/video.mp4"}
File 文件 {"file": "/path/file.txt", "name": "备注名.txt"}
Record 语音 {"url": "https://.../voice.amr"}
At @成员 {"qq": "all"} 或 {"qq": "123456"}

---

使用指令

以下指令仅限管理员在私聊中使用：

指令 用法 示例
/broadcast_all 向所有群发送广播（文字+附件） /broadcast_all 维护通知：今晚 22:00 服务器重启   或附带图片/文件
/broadcast_to 向指定群发送广播 /broadcast_to 100001,100002 重要公告，详见群文件

截图示例（私聊窗口）：

你：/broadcast_to 123456 测试广播 [图片]
Bot：广播发送完成：成功 1 个，失败 0 个。

发送时会原样保留消息中的图片、视频等媒体；纯文本会自动去除首尾空格（如需保留，可在两端加零宽空格 \u200b）。

---

文件结构

```
astrbot_plugin_broadcast/
├── main.py                  # 插件主逻辑
├── metadata.yaml            # 插件元信息
├── requirements.txt         # Python 依赖
├── _conf_schema.json        # Web 端配置表单定义
└── README.md                # 本说明文件
```

---

常见问题

Q：为什么发送图片/视频失败？
A：请确保图片/视频链接为有效的网络 URL（以 http/https 开头），或本地路径在机器人运行环境可访问。部分消息平台可能限制文件大小。

Q：定时任务没有触发？
A：定时任务依赖 AstrBot 的“主动型能力”，请确认 WebUI 其他配置 中已开启 Proactive Agent（主动型代理）。另外 cron 表达式需为 5 字段（分 时 日 月 周），且配置保存后需重载插件。

Q：全群广播说“未找到可用的群组”？
A：请检查 WebUI 配置中的 group_ids 是否正确填写了所有群号，并用英文逗号分隔。

Q：如何添加新的定时广播？
A：在 WebUI 配置页面编辑 scheduled_broadcasts，按 JSON 数组格式添加新任务，保存后重载插件即可（apscheduler 会自动替换旧任务）。

Q：为什么我 @全体成员没有效果？
A：At 组件只支持 @ 数字 QQ 或 "all" 文本，但取决于消息平台是否支持；部分平台群 @all 可能需要群主或管理员权限，请确保机器人在目标群中有相应权限。

---

反馈与贡献

欢迎提交 Issue 或 PR 到 GitHub 仓库。

---

许可证

本项目采用 MIT 许可证，详见 LICENSE 文件。

```

---

将以上内容保存为 `README.md` 并放在插件目录下即可。在 WebUI 插件详情页或 GitHub 仓库中都能获得友好展示。如果还有其他需求，随时告诉我。