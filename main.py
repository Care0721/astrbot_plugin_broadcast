import asyncio
import json
import os
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig
from astrbot.api.message_components import Plain, AtAll, Image, MessageChain
try:
    from astrbot.api.message_components import Markdown
    HAS_MARKDOWN = True
except ImportError:
    HAS_MARKDOWN = False


@register(
    name="astrbot_plugin_broadcast",
    author="YourName",
    desc="支持私聊广播到全部/指定群聊，定时广播，@全体成员，历史记录，黑名单，权限控制，Markdown/图片，撤回，分段发送。",
    version="2.0.0",
    repo="https://github.com/YourName/astrbot_plugin_broadcast",
)
class BroadcastPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.scheduler: Optional[AsyncIOScheduler] = None
        self._paused: bool = False  # 定时广播暂停状态（不持久化）
        self._last_broadcast_msgs: Dict[str, Any] = {}  # group_id -> 消息对象，用于撤回

        # 数据目录
        self.data_dir = os.path.join(os.getcwd(), "data", "astrbot_plugin_broadcast")
        os.makedirs(self.data_dir, exist_ok=True)

        # 日志文件
        self.log_file = os.path.join(self.data_dir, "broadcast_log.json")
        self._ensure_log_file()

        # 配置项读取
        self.max_log_entries = int(self.config.get("max_log_entries", 100))
        self.max_message_length = int(self.config.get("max_message_length", 500))
        self.use_at_all = self.config.get("use_at_all", False)
        self.enable_markdown = self.config.get("enable_markdown", False)
        self.allowed_users_str = self.config.get("allowed_users", "")
        self.allowed_users = [u.strip() for u in self.allowed_users_str.split(",") if u.strip()]
        self.blacklist_groups_str = self.config.get("blacklist_groups", "")
        self.blacklist_groups = [g.strip() for g in self.blacklist_groups_str.split(",") if g.strip()]

        # 定时广播
        self._cron_expr = self.config.get("cron_expr", "")
        self._cron_text = self.config.get("cron_text", "")
        self._cron_target_groups_str = self.config.get("cron_target_groups", "")
        self._cron_target_groups = [g.strip() for g in self._cron_target_groups_str.split(",") if g.strip()] if self._cron_target_groups_str else []

        if self._cron_expr and self._cron_text:
            self._start_scheduler()

    def _ensure_log_file(self):
        if not os.path.exists(self.log_file):
            with open(self.log_file, "w", encoding="utf-8") as f:
                json.dump([], f)

    def _save_log(self, entry: dict):
        try:
            with open(self.log_file, "r+", encoding="utf-8") as f:
                logs = json.load(f)
                logs.insert(0, entry)  # 最新在前
                if len(logs) > self.max_log_entries:
                    logs = logs[:self.max_log_entries]
                f.seek(0)
                f.truncate()
                json.dump(logs, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存广播日志失败: {e}")

    def _check_permission(self, event: AstrMessageEvent) -> bool:
        if not self.allowed_users:
            return True  # 未设置白名单则允许所有人
        sender_id = event.get_sender_id()
        return sender_id in self.allowed_users

    def _deny_message(self, event: AstrMessageEvent):
        return event.plain_result("❌ 无权限使用广播功能")

    def _extract_command_arg(self, message_str: str, cmd: str) -> str:
        pattern = r"^/" + re.escape(cmd) + r"\s*(.*)"
        m = re.match(pattern, message_str.strip())
        if m:
            return m.group(1).strip()
        return ""

    async def _get_all_groups(self, event: AstrMessageEvent) -> List[str]:
        """获取全部群 ID，并自动过滤黑名单"""
        group_overrides_str = self.config.get("group_overrides", "")
        group_overrides = [g.strip() for g in group_overrides_str.split(",") if g.strip()]
        if group_overrides:
            groups = group_overrides
        else:
            # 尝试自动获取
            platform = event.platform_meta.name
            groups = []
            try:
                if hasattr(self.context, "get_group_list"):
                    groups = await self.context.get_group_list(platform)
                elif hasattr(event, "get_all_groups"):
                    groups = await event.get_all_groups()
            except Exception as e:
                logger.warning(f"自动获取群列表失败: {e}")

        # 过滤黑名单
        if self.blacklist_groups:
            groups = [g for g in groups if g not in self.blacklist_groups]
        return groups

    async def _build_umo_for_group(self, event: AstrMessageEvent, group_id: str) -> str:
        umo = event.unified_msg_origin
        parts = umo.rsplit(":", 1)
        if len(parts) == 2:
            return f"{parts[0]}:{group_id}"
        return umo

    def _parse_message_chain(self, text: str) -> MessageChain:
        """
        根据文本构建消息链：
        - 如果启用 @all，开头插入 AtAll
        - 识别 [img:url] 并替换为 Image 组件
        - 如果启用 Markdown 且文本以 [MD] 开头，则用 Markdown 组件
        - 否则用 Plain 组件
        """
        chain = MessageChain()

        # @全体成员
        if self.use_at_all:
            chain.chain.append(AtAll())

        # 检测 Markdown 模式
        if self.enable_markdown and text.startswith("[MD]") and HAS_MARKDOWN:
            md_text = text[4:].strip()
            chain.chain.append(Markdown(md_text))
            return chain

        # 处理图片占位符
        # 将 [img:url] 转换为 Image 组件
        segments = re.split(r'(\[img:[^\]]+\])', text)
        for seg in segments:
            if seg.startswith("[img:") and seg.endswith("]"):
                url = seg[5:-1].strip()
                chain.chain.append(Image(url))
            else:
                if seg.strip():
                    chain.chain.append(Plain(seg))
        return chain

    async def _send_with_retry(self, umo: str, chain: MessageChain) -> Any:
        """发送消息并返回消息对象（用于获取 message_id）"""
        try:
            result = await self.context.send_message(umo, chain)
            return result
        except Exception as e:
            logger.error(f"发送广播到 {umo} 失败: {e}")
            raise

    async def _broadcast_to_groups(
        self,
        event: AstrMessageEvent,
        groups: List[str],
        text: str,
    ) -> List[dict]:
        """
        向 groups 发送广播，支持分段发送、消息记录和撤回消息 ID 存储。
        返回每个群的发送结果。
        """
        # 分段处理
        # 注意：如果消息中包含 [img] 等，分段可能破坏完整性，因此按文本长度切分（但忽略标记）
        # 实际上可先解析消息链，然而分段发送图片较复杂，我们仅对纯文本部分进行长度切分。
        # 简化处理：将文本传给 _parse_message_chain 但不分段，因为图片已经占用组件，长度限制由平台决定。
        # 所以如果文本较长且没有图片，我们分段；如果包含图片，不分段（避免错位）。这里为了稳定性，
        # 我们判断：如果 text 不含 [img: 且长度 > max_message_length，则分段；否则单条发送。
        if "[img:" not in text and len(text) > self.max_message_length:
            segments = self._split_text(text)
        else:
            segments = [text]

        results = []
        for gid in groups:
            umo = await self._build_umo_for_group(event, gid)
            group_result = {"group_id": gid, "status": "ok", "sent_messages": []}
            try:
                for idx, seg_text in enumerate(segments):
                    # 分段时添加标注 (如果多段)
                    if len(segments) > 1:
                        seg_text = f"({idx+1}/{len(segments)}) {seg_text}"
                    chain = self._parse_message_chain(seg_text)
                    msg_obj = await self._send_with_retry(umo, chain)
                    # 尝试提取 message_id 并存储
                    msg_id = self._extract_message_id(msg_obj)
                    if msg_id:
                        self._last_broadcast_msgs[gid] = {
                            "umo": umo,
                            "message_id": msg_id if len(segments) == 1 else None  # 多段时暂不支持全部撤回
                        }
                    group_result["sent_messages"].append(msg_id)
            except Exception as e:
                group_result["status"] = "fail"
                group_result["error"] = str(e)
                logger.error(f"广播到 {gid} 失败: {e}")
            results.append(group_result)

        # 记录日志
        self._save_log({
            "time": datetime.now().isoformat(),
            "text": text,
            "target_groups": groups,
            "results": results
        })
        return results

    def _extract_message_id(self, msg_obj) -> Optional[str]:
        """从发送返回的对象中提取消息ID（可能因平台而异）"""
        if msg_obj is None:
            return None
        # 常见格式：有 message_id 属性
        if hasattr(msg_obj, "message_id"):
            return msg_obj.message_id
        # 也可能是字典
        if isinstance(msg_obj, dict):
            return msg_obj.get("message_id")
        # 对于 MessageChain 返回自身？未知
        return None

    def _split_text(self, text: str) -> List[str]:
        """按最大长度分段文本，尽量在换行处切割"""
        if len(text) <= self.max_message_length:
            return [text]
        segments = []
        while len(text) > self.max_message_length:
            split_pos = text.rfind('\n', 0, self.max_message_length)
            if split_pos == -1:
                split_pos = self.max_message_length
            segments.append(text[:split_pos].rstrip())
            text = text[split_pos:].lstrip()
        if text:
            segments.append(text)
        return segments

    def _format_report(self, title: str, results: List[dict]) -> str:
        success = [r for r in results if r["status"] == "ok"]
        fail = [r for r in results if r["status"] != "ok"]
        lines = [f"📢 {title}"]
        lines.append(f"✅ 成功: {len(success)} 个群")
        if success:
            lines.append("  → " + ", ".join(r["group_id"] for r in success))
        if fail:
            lines.append(f"❌ 失败: {len(fail)} 个群")
            for r in fail:
                lines.append(f"  → {r['group_id']}: {r.get('error', '未知错误')}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 指令：广播到所有群
    # ------------------------------------------------------------------
    @filter.command("broadcast_all")
    async def cmd_broadcast_all(self, event: AstrMessageEvent):
        if not event.is_private_chat():
            return
        if not self._check_permission(event):
            yield self._deny_message(event)
            return
        text = self._extract_command_arg(event.message_str, "broadcast_all")
        if not text:
            yield event.plain_result("❌ 请提供广播内容。\n示例: /broadcast_all 大家好")
            return
        groups = await self._get_all_groups(event)
        if not groups:
            yield event.plain_result("❌ 未获取到任何群聊，请检查群列表或配置")
            return
        results = await self._broadcast_to_groups(event, groups, text)
        yield event.plain_result(self._format_report("全群广播", results))

    # ------------------------------------------------------------------
    # 指令：广播到指定群
    # ------------------------------------------------------------------
    @filter.command("broadcast_to")
    async def cmd_broadcast_to(self, event: AstrMessageEvent):
        if not event.is_private_chat():
            return
        if not self._check_permission(event):
            yield self._deny_message(event)
            return
        arg_str = self._extract_command_arg(event.message_str, "broadcast_to")
        if not arg_str:
            yield event.plain_result(
                "❌ 用法: /broadcast_to <群号1,群号2> <文本>\n示例: /broadcast_to 123456,789012 通知"
            )
            return
        parts = arg_str.split(" ", 1)
        if len(parts) != 2:
            yield event.plain_result("❌ 格式错误，请检查")
            return
        group_ids_raw, text = parts
        group_ids = [g.strip() for g in group_ids_raw.split(",") if g.strip()]
        # 过滤黑名单
        if self.blacklist_groups:
            group_ids = [g for g in group_ids if g not in self.blacklist_groups]
        if not group_ids:
            yield event.plain_result("❌ 无有效群号")
            return
        if not text:
            yield event.plain_result("❌ 请提供广播内容")
            return
        results = await self._broadcast_to_groups(event, group_ids, text)
        yield event.plain_result(
            self._format_report(f"指定群广播 → {', '.join(group_ids)}", results)
        )

    # ------------------------------------------------------------------
    # 指令：查看定时广播状态
    # ------------------------------------------------------------------
    @filter.command("broadcast_status")
    async def cmd_broadcast_status(self, event: AstrMessageEvent):
        if not event.is_private_chat():
            return
        if not self._check_permission(event):
            yield self._deny_message(event)
            return
        cron = self._cron_expr
        text = self._cron_text
        if not cron or not text:
            yield event.plain_result("⏸️ 未设置定时广播")
            return
        job = None
        if self.scheduler:
            jobs = self.scheduler.get_jobs()
            if jobs:
                job = jobs[0]
        msg = (
            f"📋 定时广播状态\n"
            f"• Cron: {cron}\n"
            f"• 内容: {text}\n"
            f"• 暂停: {'是' if self._paused else '否'}\n"
            f"• 状态: {'🟢 运行中' if job and job.next_run_time and not self._paused else '🔴 未激活'}"
        )
        if job and job.next_run_time:
            msg += f"\n• 下次执行: {job.next_run_time.strftime('%Y-%m-%d %H:%M:%S')}"
        yield event.plain_result(msg)

    # ------------------------------------------------------------------
    # 指令：暂停/恢复定时广播
    # ------------------------------------------------------------------
    @filter.command("broadcast_pause")
    async def cmd_broadcast_pause(self, event: AstrMessageEvent):
        if not event.is_private_chat():
            return
        if not self._check_permission(event):
            yield self._deny_message(event)
            return
        self._paused = True
        yield event.plain_result("⏸️ 定时广播已暂停")

    @filter.command("broadcast_resume")
    async def cmd_broadcast_resume(self, event: AstrMessageEvent):
        if not event.is_private_chat():
            return
        if not self._check_permission(event):
            yield self._deny_message(event)
            return
        self._paused = False
        yield event.plain_result("▶️ 定时广播已恢复")

    # ------------------------------------------------------------------
    # 指令：查看广播日志
    # ------------------------------------------------------------------
    @filter.command("broadcast_log")
    async def cmd_broadcast_log(self, event: AstrMessageEvent):
        if not event.is_private_chat():
            return
        if not self._check_permission(event):
            yield self._deny_message(event)
            return
        arg = self._extract_command_arg(event.message_str, "broadcast_log")
        try:
            limit = int(arg) if arg else 3
        except:
            limit = 3
        try:
            with open(self.log_file, "r", encoding="utf-8") as f:
                logs = json.load(f)
        except:
            logs = []
        if not logs:
            yield event.plain_result("📭 暂无广播历史")
            return
        recent = logs[:limit]
        lines = [f"📜 最近 {len(recent)} 条广播记录:"]
        for log in recent:
            time = log.get("time", "?")
            text = log.get("text", "")[:50]
            targets = log.get("target_groups", [])
            success = sum(1 for r in log.get("results", []) if r.get("status") == "ok")
            lines.append(f"• {time} | 群数:{len(targets)} 成功:{success} | {text}")
        yield event.plain_result("\n".join(lines))

    # ------------------------------------------------------------------
    # 指令：撤回最近广播
    # ------------------------------------------------------------------
    @filter.command("broadcast_recall")
    async def cmd_broadcast_recall(self, event: AstrMessageEvent):
        if not event.is_private_chat():
            return
        if not self._check_permission(event):
            yield self._deny_message(event)
            return
        arg = self._extract_command_arg(event.message_str, "broadcast_recall")
        if not arg:
            yield event.plain_result("❌ 用法: /broadcast_recall <群号>")
            return
        gid = arg.strip()
        if gid not in self._last_broadcast_msgs or self._last_broadcast_msgs[gid]["message_id"] is None:
            yield event.plain_result(f"❌ 未找到可撤回的消息，请确认群号 {gid} 最近广播存在且未过期")
            return
        info = self._last_broadcast_msgs[gid]
        umo = info["umo"]
        msg_id = info["message_id"]
        try:
            await self.context.recall_message(umo, msg_id)
            yield event.plain_result(f"✅ 已尝试撤回群 {gid} 的消息")
        except Exception as e:
            logger.error(f"撤回失败: {e}")
            yield event.plain_result(f"❌ 撤回失败: {e}")

    # ------------------------------------------------------------------
    # 指令：帮助
    # ------------------------------------------------------------------
    @filter.command("broadcast_help")
    async def cmd_broadcast_help(self, event: AstrMessageEvent):
        if not event.is_private_chat():
            return
        help_text = (
            "📢 广播插件 v2.0\n"
            "指令 (仅私聊):\n"
            "/broadcast_all <内容> — 广播到所有群\n"
            "/broadcast_to <群号> <内容> — 广播到指定群\n"
            "/broadcast_status — 查看定时广播状态\n"
            "/broadcast_pause — 暂停定时广播\n"
            "/broadcast_resume — 恢复定时广播\n"
            "/broadcast_log [条数] — 查看广播历史\n"
            "/broadcast_recall <群号> — 撤回最近广播\n"
            "/broadcast_help — 显示帮助\n\n"
            "高级功能:\n"
            "• 内容前加 [MD] 使用 Markdown (需平台支持)\n"
            "• 插入 [img:url] 发送图片\n"
            "• 如需 @全体成员，在 WebUI 开启 use_at_all"
        )
        yield event.plain_result(help_text)

    # ------------------------------------------------------------------
    # 定时广播核心
    # ------------------------------------------------------------------
    def _start_scheduler(self):
        if self.scheduler:
            self.scheduler.shutdown(wait=False)
        self.scheduler = AsyncIOScheduler()
        try:
            trigger = CronTrigger.from_crontab(self._cron_expr)
        except Exception as e:
            logger.error(f"无效 cron 表达式: {e}")
            return
        self.scheduler.add_job(
            self._scheduled_broadcast,
            trigger=trigger,
            id="broadcast_cron_job",
            replace_existing=True,
        )
        self.scheduler.start()
        logger.info(f"定时广播已启动: cron={self._cron_expr}")

    async def _scheduled_broadcast(self):
        if self._paused:
            logger.info("定时广播已暂停，跳过执行")
            return
        text = self.config.get("cron_text", "")
        if not text:
            return
        # 获取目标群
        groups = []
        if self._cron_target_groups:
            groups = self._cron_target_groups
        else:
            # 尝试从配置或自动获取 (这里无法获取 event，只能依赖静态配置)
            group_overrides_str = self.config.get("group_overrides", "")
            groups = [g.strip() for g in group_overrides_str.split(",") if g.strip()]
            if not groups:
                logger.warning("定时广播未配置目标群且无法自动获取，跳过")
                return

        # 过滤黑名单
        if self.blacklist_groups:
            groups = [g for g in groups if g not in self.blacklist_groups]

        platform_name = self.config.get("platform_name", "aiocqhttp")
        results = []
        for gid in groups:
            umo = f"{platform_name}:GroupMessage:{gid}"
            try:
                chain = self._parse_message_chain(text)
                msg_obj = await self._send_with_retry(umo, chain)
                msg_id = self._extract_message_id(msg_obj)
                if msg_id:
                    self._last_broadcast_msgs[gid] = {"umo": umo, "message_id": msg_id}
                results.append({"group_id": gid, "status": "ok"})
            except Exception as e:
                results.append({"group_id": gid, "status": "fail", "error": str(e)})

        self._save_log({
            "time": datetime.now().isoformat(),
            "text": text,
            "target_groups": groups,
            "results": results
        })
        logger.info(f"[定时广播] 完成: {sum(1 for r in results if r['status']=='ok')}/{len(results)}")

    async def terminate(self):
        if self.scheduler:
            self.scheduler.shutdown(wait=False)
        logger.info("广播插件已停止")