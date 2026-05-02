"""
AstrBot 群广播插件 v1.2.0
功能：
  - 私聊发送广播到全部群 / 指定群
  - 支持图片、视频、文件等富媒体
  - 定时广播（APScheduler）
  - 网页端配置项
  - 广播日志记录
"""

import json
import os
import re
import asyncio
import datetime
import logging
from typing import List, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api.message.components import (
    Plain, Image, Video, File, At, Record
)
from astrbot.api import logger
from astrbot.api.platform import AstrBotMessage, MessageMember, MessageType

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(PLUGIN_DIR, "broadcast_log.txt")
SCHEDULE_STATE_PATH = os.path.join(PLUGIN_DIR, "schedule_state.json")


@register(
    name="astrbot_plugin_broadcast",
    desc="群广播插件：支持向全部/指定群发送富媒体广播，含定时广播",
    version="1.2.0",
    author="custom",
)
class BroadcastPlugin(Star):

    # ------------------------------------------------------------------ #
    #  初始化
    # ------------------------------------------------------------------ #
    def __init__(self, context: Context, config: dict):
        super().__init__(context, config)

        self.cfg = config

        # 解析管理员列表
        raw_admins = self.cfg.get("broadcast_admin_ids", "")
        self.admin_ids: List[str] = [
            s.strip() for s in raw_admins.split(",") if s.strip()
        ]

        # 解析黑名单
        raw_bl = self.cfg.get("blacklist_groups", "")
        self.blacklist: List[str] = [
            s.strip() for s in raw_bl.split(",") if s.strip()
        ]

        self.send_interval: float = float(self.cfg.get("broadcast_interval_seconds", 2))
        self.prefix: str = self.cfg.get("broadcast_prefix", "📢 【系统广播】\n")
        self.suffix: str = self.cfg.get("broadcast_suffix", "")
        self.enable_log: bool = bool(self.cfg.get("enable_broadcast_log", True))

        # 定时调度器
        self.scheduler = AsyncIOScheduler()
        self._load_and_register_schedules()
        self.scheduler.start()

        logger.info("[Broadcast] 插件已加载，定时任务已启动。")

    # ------------------------------------------------------------------ #
    #  权限校验
    # ------------------------------------------------------------------ #
    def _is_authorized(self, event: AstrMessageEvent) -> bool:
        """检查发送者是否有广播权限（Bot主人 or 配置中的管理员）"""
        sender_id = str(event.get_sender_id())
        # AstrBot 主人列表
        owner_ids = [str(uid) for uid in (self.context.base_config.get("admins_id") or [])]
        return sender_id in owner_ids or sender_id in self.admin_ids

    # ------------------------------------------------------------------ #
    #  获取所有群列表
    # ------------------------------------------------------------------ #
    async def _get_all_groups(self) -> List[dict]:
        """
        遍历所有平台适配器，收集 group_list。
        返回列表元素: {"platform": adapter, "group_id": str, "group_name": str}
        """
        results = []
        for platform in self.context.platforms:
            try:
                client = platform.client
                if hasattr(client, "get_group_list"):
                    groups = await client.get_group_list()
                    for g in groups:
                        gid = str(g.get("group_id", g.get("id", "")))
                        gname = g.get("group_name", g.get("name", gid))
                        if gid and gid not in self.blacklist:
                            results.append({
                                "platform": platform,
                                "group_id": gid,
                                "group_name": gname,
                            })
            except Exception as e:
                logger.warning(f"[Broadcast] 获取群列表失败（平台 {platform.name}）: {e}")
        return results

    # ------------------------------------------------------------------ #
    #  构建消息链
    # ------------------------------------------------------------------ #
    def _build_chain(self, text: str, media_urls: List[dict]) -> list:
        """
        media_urls: [{"type": "image"|"video"|"file"|"record", "url": "..."}]
        """
        chain = []
        full_text = self.prefix + text + self.suffix
        if full_text.strip():
            chain.append(Plain(full_text))

        for m in media_urls:
            t = m.get("type", "image")
            url = m.get("url", "")
            if not url:
                continue
            if t == "image":
                chain.append(Image.fromURL(url))
            elif t == "video":
                chain.append(Video.fromURL(url))
            elif t == "record":
                chain.append(Record.fromURL(url))
            elif t == "file":
                chain.append(File.fromURL(url))
        return chain

    # ------------------------------------------------------------------ #
    #  核心发送逻辑
    # ------------------------------------------------------------------ #
    async def _send_broadcast(
        self,
        text: str,
        media_urls: List[dict],
        target_group_ids: Optional[List[str]] = None,
    ) -> dict:
        """
        发送广播。
        target_group_ids=None 表示全部群。
        返回 {"success": int, "fail": int, "skipped": int}
        """
        groups = await self._get_all_groups()

        if target_group_ids:
            target_set = set(str(g) for g in target_group_ids)
            groups = [g for g in groups if g["group_id"] in target_set]

        chain = self._build_chain(text, media_urls)
        stats = {"success": 0, "fail": 0, "skipped": 0}

        for group_info in groups:
            gid = group_info["group_id"]
            platform = group_info["platform"]
            try:
                await platform.send_msg(
                    MessageType.GROUP_MESSAGE,
                    gid,
                    chain,
                )
                stats["success"] += 1
                self._write_log(
                    f"[OK] group={gid} platform={platform.name} text={text[:30]}"
                )
            except Exception as e:
                stats["fail"] += 1
                self._write_log(
                    f"[FAIL] group={gid} platform={platform.name} err={e}"
                )
                logger.warning(f"[Broadcast] 发送至群 {gid} 失败: {e}")

            await asyncio.sleep(self.send_interval)

        return stats

    # ------------------------------------------------------------------ #
    #  日志
    # ------------------------------------------------------------------ #
    def _write_log(self, msg: str):
        if not self.enable_log:
            return
        try:
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] {msg}\n")
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    #  指令：/broadcast
    # ------------------------------------------------------------------ #
    @filter.command("broadcast")
    async def cmd_broadcast(self, event: AstrMessageEvent):
        """
        私聊指令入口，格式：
          /broadcast all <文字内容>
          /broadcast group <群号1,群号2,...> <文字内容>
          /broadcast list
          /broadcast schedule add <cron> <文字内容>
          /broadcast schedule list
          /broadcast schedule remove <job_id>
          /broadcast log [n]

        富媒体：在文字后追加 [image:URL] [video:URL] [file:URL] [record:URL]
        """
        # ---- 必须私聊 ----
        if event.get_message_type() != MessageType.FRIEND_MESSAGE:
            yield event.plain_result("⚠️ 广播指令只能在私聊中使用。")
            return

        # ---- 权限 ----
        if not self._is_authorized(event):
            yield event.plain_result("❌ 你没有使用广播指令的权限。")
            return

        raw = event.get_message_str().strip()
        # 去掉指令头
        raw = re.sub(r"^/broadcast\s*", "", raw, flags=re.IGNORECASE).strip()

        # -- list：查看所有群 --
        if raw.lower() == "list":
            async for result in self._cmd_list(event):
                yield result
            return

        # -- log [n]：查看日志 --
        if raw.lower().startswith("log"):
            async for result in self._cmd_log(event, raw):
                yield result
            return

        # -- schedule 子命令 --
        if raw.lower().startswith("schedule"):
            async for result in self._cmd_schedule(event, raw):
                yield result
            return

        # -- all <内容> --
        if raw.lower().startswith("all ") or raw.lower() == "all":
            content = raw[4:].strip()
            text, media = self._parse_content(content)
            yield event.plain_result("📡 正在向所有群发送广播，请稍候……")
            stats = await self._send_broadcast(text, media)
            yield event.plain_result(
                f"✅ 广播完成！\n成功：{stats['success']} 群\n失败：{stats['fail']} 群"
            )
            return

        # -- group <群号,...> <内容> --
        if raw.lower().startswith("group "):
            rest = raw[6:].strip()
            # 提取群号部分（支持逗号/空格分隔，直到遇到非数字/非逗号）
            m = re.match(r"^([\d,\s]+?)\s+(.+)$", rest, re.DOTALL)
            if not m:
                yield event.plain_result(
                    "⚠️ 格式错误。\n用法：/broadcast group <群号1,群号2> <内容>"
                )
                return
            group_ids = [g.strip() for g in m.group(1).replace(" ", ",").split(",") if g.strip()]
            content = m.group(2).strip()
            text, media = self._parse_content(content)
            yield event.plain_result(
                f"📡 正在向指定 {len(group_ids)} 个群发送广播，请稍候……"
            )
            stats = await self._send_broadcast(text, media, target_group_ids=group_ids)
            yield event.plain_result(
                f"✅ 广播完成！\n成功：{stats['success']} 群\n失败：{stats['fail']} 群"
            )
            return

        # -- 帮助 --
        yield event.plain_result(self._help_text())

    # ------------------------------------------------------------------ #
    #  子命令：list
    # ------------------------------------------------------------------ #
    async def _cmd_list(self, event: AstrMessageEvent):
        groups = await self._get_all_groups()
        if not groups:
            yield event.plain_result("当前 Bot 未加入任何群，或获取群列表失败。")
            return
        lines = [f"📋 Bot 已加入 {len(groups)} 个群："]
        for i, g in enumerate(groups, 1):
            lines.append(f"{i}. [{g['group_id']}] {g['group_name']} ({g['platform'].name})")
        yield event.plain_result("\n".join(lines))

    # ------------------------------------------------------------------ #
    #  子命令：log
    # ------------------------------------------------------------------ #
    async def _cmd_log(self, event: AstrMessageEvent, raw: str):
        parts = raw.split()
        n = 20
        if len(parts) >= 2 and parts[1].isdigit():
            n = int(parts[1])
        if not os.path.exists(LOG_PATH):
            yield event.plain_result("暂无广播日志。")
            return
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
        tail = lines[-n:]
        yield event.plain_result(f"📜 最近 {len(tail)} 条广播日志：\n" + "".join(tail))

    # ------------------------------------------------------------------ #
    #  子命令：schedule
    # ------------------------------------------------------------------ #
    async def _cmd_schedule(self, event: AstrMessageEvent, raw: str):
        # 去掉 "schedule" 前缀
        rest = raw[8:].strip()

        # schedule list
        if rest.lower() == "list" or rest == "":
            jobs = self._load_schedule_state()
            if not jobs:
                yield event.plain_result("📅 暂无定时广播任务。")
                return
            lines = [f"📅 当前定时广播任务（{len(jobs)} 个）："]
            for j in jobs:
                target = j.get("target", "all")
                lines.append(
                    f"  ID: {j['id']}\n"
                    f"  Cron: {j['cron']}\n"
                    f"  目标: {target}\n"
                    f"  内容: {j['text'][:40]}…\n"
                    f"  媒体: {len(j.get('media', []))} 个\n"
                )
            yield event.plain_result("\n".join(lines))
            return

        # schedule remove <id>
        m = re.match(r"^remove\s+(\S+)$", rest, re.IGNORECASE)
        if m:
            job_id = m.group(1)
            removed = self._remove_scheduled_job(job_id)
            if removed:
                yield event.plain_result(f"✅ 已删除定时任务 [{job_id}]。")
            else:
                yield event.plain_result(f"❌ 未找到任务 [{job_id}]。")
            return

        # schedule add <cron> [group <群号,...>] <内容>
        # cron 格式：分 时 日 月 周  共5段
        m = re.match(
            r"^add\s+"
            r"((?:\S+\s+){4}\S+)"          # cron (5 fields)
            r"\s+"
            r"(?:group\s+([\d,\s]+?)\s+)?"  # optional group list
            r"(.+)$",                        # content
            rest,
            re.IGNORECASE | re.DOTALL,
        )
        if not m:
            yield event.plain_result(
                "⚠️ 格式错误。\n"
                "用法：/broadcast schedule add <cron5段> [group <群号,...>] <内容>\n"
                "示例：/broadcast schedule add 0 9 * * 1 早安，大家好！\n"
                "      /broadcast schedule add 0 12 * * * group 123,456 午餐提醒"
            )
            return

        cron_str = m.group(1).strip()
        group_raw = m.group(2)
        content = m.group(3).strip()

        target_groups = None
        if group_raw:
            target_groups = [g.strip() for g in group_raw.replace(" ", ",").split(",") if g.strip()]

        text, media = self._parse_content(content)

        try:
            cron_parts = cron_str.split()
            trigger = CronTrigger(
                minute=cron_parts[0],
                hour=cron_parts[1],
                day=cron_parts[2],
                month=cron_parts[3],
                day_of_week=cron_parts[4],
            )
        except Exception as e:
            yield event.plain_result(f"❌ Cron 表达式解析失败: {e}")
            return

        job_id = datetime.datetime.now().strftime("job_%Y%m%d%H%M%S")
        job_data = {
            "id": job_id,
            "cron": cron_str,
            "target": ",".join(target_groups) if target_groups else "all",
            "text": text,
            "media": media,
        }

        self.scheduler.add_job(
            self._scheduled_broadcast_task,
            trigger=trigger,
            id=job_id,
            args=[job_data],
            replace_existing=True,
        )
        self._save_scheduled_job(job_data)

        target_str = f"群 {job_data['target']}" if target_groups else "全部群"
        yield event.plain_result(
            f"✅ 定时广播已添加！\n"
            f"  任务ID: {job_id}\n"
            f"  Cron:   {cron_str}\n"
            f"  目标:   {target_str}\n"
            f"  内容:   {text[:40]}"
        )

    # ------------------------------------------------------------------ #
    #  定时任务执行函数
    # ------------------------------------------------------------------ #
    async def _scheduled_broadcast_task(self, job_data: dict):
        text = job_data.get("text", "")
        media = job_data.get("media", [])
        target = job_data.get("target", "all")

        target_groups = None
        if target != "all":
            target_groups = [g.strip() for g in target.split(",") if g.strip()]

        logger.info(f"[Broadcast] 执行定时任务 {job_data['id']} → 目标={target}")
        stats = await self._send_broadcast(text, media, target_group_ids=target_groups)
        logger.info(
            f"[Broadcast] 定时任务 {job_data['id']} 完成: "
            f"成功={stats['success']} 失败={stats['fail']}"
        )

    # ------------------------------------------------------------------ #
    #  定时任务持久化
    # ------------------------------------------------------------------ #
    def _load_schedule_state(self) -> List[dict]:
        if not os.path.exists(SCHEDULE_STATE_PATH):
            return []
        try:
            with open(SCHEDULE_STATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def _save_schedule_state(self, jobs: List[dict]):
        with open(SCHEDULE_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(jobs, f, ensure_ascii=False, indent=2)

    def _save_scheduled_job(self, job_data: dict):
        jobs = self._load_schedule_state()
        jobs = [j for j in jobs if j["id"] != job_data["id"]]
        jobs.append(job_data)
        self._save_schedule_state(jobs)

    def _remove_scheduled_job(self, job_id: str) -> bool:
        jobs = self._load_schedule_state()
        new_jobs = [j for j in jobs if j["id"] != job_id]
        if len(new_jobs) == len(jobs):
            return False
        self._save_schedule_state(new_jobs)
        try:
            self.scheduler.remove_job(job_id)
        except Exception:
            pass
        return True

    def _load_and_register_schedules(self):
        """启动时从持久化文件恢复所有定时任务"""
        jobs = self._load_schedule_state()
        for job_data in jobs:
            try:
                cron_parts = job_data["cron"].split()
                trigger = CronTrigger(
                    minute=cron_parts[0],
                    hour=cron_parts[1],
                    day=cron_parts[2],
                    month=cron_parts[3],
                    day_of_week=cron_parts[4],
                )
                self.scheduler.add_job(
                    self._scheduled_broadcast_task,
                    trigger=trigger,
                    id=job_data["id"],
                    args=[job_data],
                    replace_existing=True,
                )
                logger.info(f"[Broadcast] 已恢复定时任务: {job_data['id']} cron={job_data['cron']}")
            except Exception as e:
                logger.warning(f"[Broadcast] 恢复定时任务失败 {job_data.get('id')}: {e}")

    # ------------------------------------------------------------------ #
    #  解析内容（文字 + 媒体标记）
    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse_content(content: str):
        """
        从内容字符串中提取文字与媒体 URL。
        媒体格式：[image:URL] [video:URL] [file:URL] [record:URL]
        """
        media_pattern = re.compile(
            r"\[(image|video|file|record):([^\]]+)\]", re.IGNORECASE
        )
        media_urls = []
        for m in media_pattern.finditer(content):
            media_urls.append({"type": m.group(1).lower(), "url": m.group(2).strip()})

        text = media_pattern.sub("", content).strip()
        return text, media_urls

    # ------------------------------------------------------------------ #
    #  帮助文本
    # ------------------------------------------------------------------ #
    @staticmethod
    def _help_text() -> str:
        return (
            "📢 广播插件使用说明\n\n"
            "【向全部群广播】\n"
            "/broadcast all <内容>\n\n"
            "【向指定群广播】\n"
            "/broadcast group <群号1,群号2,...> <内容>\n\n"
            "【查看已加入的群】\n"
            "/broadcast list\n\n"
            "【查看广播日志】\n"
            "/broadcast log [条数]\n\n"
            "【定时广播】\n"
            "/broadcast schedule add <cron5段> [group <群号,...>] <内容>\n"
            "/broadcast schedule list\n"
            "/broadcast schedule remove <任务ID>\n\n"
            "【富媒体格式】在内容末尾追加：\n"
            "  [image:图片URL]\n"
            "  [video:视频URL]\n"
            "  [file:文件URL]\n"
            "  [record:语音URL]\n\n"
            "示例：\n"
            "  /broadcast all 大家好！[image:https://example.com/1.jpg]\n"
            "  /broadcast group 123456,789012 紧急通知！\n"
            "  /broadcast schedule add 0 8 * * * 早安！"
        )

    # ------------------------------------------------------------------ #
    #  插件销毁
    # ------------------------------------------------------------------ #
    async def destroy(self):
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
        logger.info("[Broadcast] 插件已卸载，定时任务已停止。")
