# AstrBot 群广播插件

> 版本：1.2.0 | 作者：Care

## 功能概览

| 功能 | 说明 |
|------|------|
| 全群广播 | 向 Bot 加入的所有群发送消息 |
| 指定群广播 | 向一个或多个指定群发送消息 |
| 富媒体支持 | 可在广播中包含图片、视频、文件、语音 |
| 定时广播 | 使用 Cron 表达式配置定时发送，重启后自动恢复 |
| 网页配置 | 在 AstrBot Dashboard 中可视化配置所有选项 |
| 广播日志 | 自动记录每次广播结果，可通过指令查看 |

---

## 安装

将 `astrbot_plugin_broadcast` 文件夹放入 AstrBot 的 `addons/plugins/` 目录，重启或在管理面板中重载插件即可。

---

## 指令说明

> ⚠️ 所有广播指令**必须在与 Bot 的私聊中**使用。  
> 只有 Bot 主人（`admins_id`）以及在配置中添加的管理员才能使用。

### 基础广播

```
/broadcast all <内容>
```
向 Bot 加入的**全部群**发送广播。

```
/broadcast group <群号1,群号2,...> <内容>
```
向**指定群**发送广播，多个群号用英文逗号隔开。

```
/broadcast list
```
查看 Bot 当前已加入的所有群。

---

### 富媒体格式

在广播内容末尾追加媒体标记：

```
[image:https://example.com/image.jpg]   # 图片
[video:https://example.com/video.mp4]   # 视频
[file:https://example.com/file.zip]     # 文件
[record:https://example.com/audio.mp3] # 语音
```

**示例：**
```
/broadcast all 今日公告！[image:https://example.com/notice.jpg]
/broadcast group 123456,789012 紧急通知[video:https://example.com/v.mp4]
```

---

### 定时广播

使用标准 **5 段 Cron 表达式**（`分 时 日 月 周`）。

```
/broadcast schedule add <cron> [group <群号,...>] <内容>
```

**示例：**
```bash
# 每天 08:00 向全部群发早安
/broadcast schedule add 0 8 * * * 早安，大家好！☀️

# 每周一 09:30 向指定群发通知
/broadcast schedule add 30 9 * * 1 group 123456,789012 本周工作安排请查看群公告！

# 每天 12:00 发午餐提醒，带图片
/broadcast schedule add 0 12 * * * 午饭时间到啦！[image:https://example.com/food.jpg]
```

```
/broadcast schedule list          # 查看所有定时任务
/broadcast schedule remove <ID>   # 删除指定任务
```

---

### 日志查看

```
/broadcast log        # 查看最近 20 条日志
/broadcast log 50     # 查看最近 50 条日志
```

---

## 网页配置项

在 AstrBot Dashboard → 插件配置 中可设置：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `broadcast_admin_ids` | 允许使用广播的额外管理员 QQ 号（逗号分隔） | 空 |
| `broadcast_interval_seconds` | 每次群发间隔秒数（防风控） | `2` |
| `broadcast_max_media_size_mb` | 允许的最大媒体文件大小（MB） | `50` |
| `blacklist_groups` | 广播黑名单群号（这些群不会收到广播） | 空 |
| `broadcast_prefix` | 广播消息前缀 | `📢 【系统广播】\n` |
| `broadcast_suffix` | 广播消息后缀 | 空 |
| `enable_broadcast_log` | 是否记录日志 | `true` |

---

## Cron 表达式速查

```
字段顺序：分钟 小时 日 月 星期

*        任意值
,        列举（如 1,3,5）
-        范围（如 1-5）
/        步长（如 */2 = 每隔2）

常用示例：
0 8 * * *      每天 08:00
0 8 * * 1      每周一 08:00
0 */2 * * *    每 2 小时整点
30 12 1 * *    每月 1 日 12:30
```

---

## 文件结构

```
astrbot_plugin_broadcast/
├── main.py              # 插件主逻辑
├── metadata.yaml        # 插件元信息
├── _conf_schema.json    # 网页配置 Schema
├── README.md            # 本文档
├── broadcast_log.txt    # 运行时生成：广播日志
└── schedule_state.json  # 运行时生成：定时任务持久化
```

---

## 注意事项

1. **发送间隔**：默认每个群之间等待 2 秒，群多时广播耗时较长，期间请勿重复发送。  
2. **平台支持**：本插件通过 `platform.send_msg` 发送，理论上支持所有已接入的平台（QQ、微信、Discord 等）。实际效果取决于对应平台的消息类型支持情况。  
3. **富媒体**：图片/视频必须是可公网访问的 URL，或已上传至平台的资源链接。  
4. **定时任务**：重启后会自动从 `schedule_state.json` 恢复，无需重新添加。
