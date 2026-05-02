import json
import os
import asyncio
from datetime import datetime
from typing import List, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.all import *

# 消息组件引入
from astrbot.api.message_components import (
    Plain,
    Image,
    Video,
    File,
    At,
    Record,
)

# 私聊消息类型常量（适配器可能不同，此处以 aiocqhttp 为例）
FRIEND_MESSAGE_TYPE = "FriendMessage"


@register("astrbot_plugin_broadcast", "your_name", "广播插件", "1.0.0", "repo url")
class BroadcastPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.scheduler: Optional[AsyncIOScheduler] = None
        self._plugin_dir = os.path.dirname(os.path.abspath(__file__))
        self._config_path = os.path.join(self._plugin_dir, "_conf.json")

    # ---------- 生命周期 ----------
    async def initialize(self):
        """插件初始化时启动定时广播调度器并加载任务。"""
        logger.info("[广播插件] 插件初始化中...")
        self._start_scheduler()
        logger.info("[广播插件] 插件初始化完成。")

    async def terminate(self):
        """插件卸载/重载时关闭调度器。"""
        logger.info("[广播插件] 插件正在终止...")
        if self.scheduler:
            self.scheduler.shutdown(wait=False)
            self.scheduler = None
        logger.info("[广播插件] 插件终止完成。")

    # ---------- 工具方法 ----------

    def _get_config(self) -> dict:
        """读取 _conf_schema.json 的默认值并合并 _conf.json 的用户配置。"""
        schema_path = os.path.join(self._plugin_dir, "_conf_schema.json")
        defaults = {}
        if os.path.exists(schema_path):
            with open(schema_path, "r", encoding="utf-8") as f:
                schema = json.load(f)
            for key, val in schema.items():
                defaults[key] = val.get("default", "")

        if os.path.exists(self._config_path):
            with open(self._config_path, "r", encoding="utf-8") as f:
                user_conf = json.load(f)
            defaults.update(user_conf)
        return defaults

    def _get_admin_ids(self, config: dict) -> List[str]:
        """获取管理员 ID 列表。"""
        raw = config.get("admin_ids", "")
        if not raw:
            return []
        return [uid.strip() for uid in raw.split(",") if uid.strip()]

    def _is_admin(self, event: AstrMessageEvent, admin_ids: List[str]) -> bool:
        """检查事件发起者是否为管理员。"""
        sender_id = event.get_sender_id()
        # 兼容消息平台返回的 ID 为整型或字符串的情况
        return str(sender_id) in admin_ids

    async def _get_all_group_umos(
        self, event: AstrMessageEvent
    ) -> List[str]:
        """
        获取当前会话所在适配器下的所有群聊 unified_msg_origin 列表。
        注意：AstrBot 目前未提供标准的 "获取所有群列表" API，
        此处通过分析事件中的 session 信息，尝试获取适配器 ID 并构造 UMO。
        实际使用时，群号需要根据业务场景预先配置或通过外部数据源获取。
        """
        # 获取当前事件的 unified_msg_origin 格式为 "platform:message_type:session_id"
        current_umo = event.unified_msg_origin
        logger.info(f"[广播插件] 当前会话 UMO: {current_umo}")
        # 尝试从当前 UMO 中提取平台适配器 ID
        parts = current_umo.split(":")
        if len(parts) < 3:
            logger.warning(f"[广播插件] 无法解析 UMO 格式: {current_umo}")
            return []

        platform_id = parts[0]  # 例如 "aiocqhttp_default"
        # 从配置中获取已知群组列表（需用户在 WebUI 中预先配置）
        config = self._get_config()
        group_ids_str = config.get("group_ids", "")
        if not group_ids_str:
            logger.warning(
                "[广播插件] 未配置群组列表，请通过 WebUI 在配置中添加 group_ids 字段"
            )
            return []

        group_ids = [
            gid.strip() for gid in group_ids_str.split(",") if gid.strip()
        ]
        umos = []
        for gid in group_ids:
            # 构造群聊 UMO，格式 "平台适配器ID:群聊类型:群号"
            umos.append(f"{platform_id}:GroupMessage:{gid}")
        return umos

    def _parse_message_chain(self, chain_data: List[dict]) -> List:
        """
        将 JSON 消息链数组转换为 AstrBot 消息组件对象列表。
        
        chain_data 格式示例:
        [
            {"type": "Plain", "data": {"text": "大家好"}},
            {"type": "Image", "data": {"url": "https://example.com/pic.jpg"}},
            {"type": "Video", "data": {"url": "https://example.com/video.mp4"}},
            {"type": "File", "data": {"file": "local/file/path.txt"}}
        ]
        """
        components = []
        for item in chain_data:
            ctype = item.get("type", "")
            data = item.get("data", {})
            if ctype == "Plain":
                components.append(Plain(text=data.get("text", "")))
            elif ctype == "Image":
                # 优先使用 file 字段（本地文件），否则使用 url
                if "file" in data:
                    components.append(
                        Image.fromFileSystem(data["file"])
                    )
                elif "url" in data:
                    components.append(
                        Image.fromURL(data["url"])
                    )
            elif ctype == "Video":
                if "file" in data:
                    components.append(
                        Video.fromFileSystem(data["file"])
                    )
                elif "url" in data:
                    components.append(
                        Video.fromURL(data["url"])
                    )
            elif ctype == "File":
                components.append(
                    File(file=data.get("file", ""), name=data.get("name", ""))
                )
            elif ctype == "At":
                components.append(At(qq=data.get("qq", "")))
            elif ctype == "Record":
                if "file" in data:
                    components.append(Record(file=data["file"], url=data.get("url", "")))
                elif "url" in data:
                    components.append(Record(file="", url=data["url"]))
            else:
                logger.warning(f"[广播插件] 未知消息组件类型: {ctype}")
        return components

    async def _send_broadcast(
        self, umo_list: List[str], chain: List, event: AstrMessageEvent
    ) -> str:
        """
        向指定的 UMO 列表发送广播消息。
        返回发送结果的摘要字符串。
        """
        success = 0
        fail = 0
        for umo in umo_list:
            try:
                await self.context.send_message(umo, chain)
                success += 1
                logger.info(f"[广播插件] 已发送至 {umo}")
            except Exception as e:
                fail += 1
                logger.error(f"[广播插件] 发送至 {umo} 失败: {e}")

        result = f"广播发送完成：成功 {success} 个，失败 {fail} 个。"
        if fail > 0:
            result += "\n请检查 WebUI 控制台日志了解失败详情。"
        return result

    # ---------- 私聊指令 ----------

    @filter.command("broadcast_all")
    async def broadcast_all(self, event: AstrMessageEvent):
        """
        管理员私聊广播到所有群。
        用法: /broadcast_all <消息内容>
        通过指令后附带的消息链发送广播。
        """
        config = self._get_config()
        admin_ids = self._get_admin_ids(config)
        if not self._is_admin(event, admin_ids):
            yield event.plain_result("⛔ 您没有权限使用此指令。")
            return

        # 获取所有群的 UMO 列表
        umos = await self._get_all_group_umos(event)
        if not umos:
            yield event.plain_result("⚠️ 未找到可用的群组，请确认配置。")
            return

        # 优先使用消息链（支持图片/视频等富媒体），如果没有则回退到纯文本
        message_chain = event.message_obj.message
        if not message_chain:
            yield event.plain_result("⚠️ 消息内容为空。")
            return

        result = await self._send_broadcast(umos, message_chain, event)
        yield event.plain_result(result)

    @filter.command("broadcast_to")
    async def broadcast_to(self, event: AstrMessageEvent):
        """
        管理员私聊广播到指定群。
        用法: /broadcast_to <群号> <消息内容>
        多个群号用英文逗号分隔（不含空格），如 /broadcast_to 123456,789012 大家好
        """
        config = self._get_config()
        admin_ids = self._get_admin_ids(config)
        if not self._is_admin(event, admin_ids):
            yield event.plain_result("⛔ 您没有权限使用此指令。")
            return

        # 提取指令参数
        msg_str = event.message_str.strip()
        # 去除指令前缀 "/broadcast_to "（注意后面带一个空格）
        param_str = msg_str[len("/broadcast_to "):].strip()
        # 找到第一个空格，分割群号和消息链
        space_idx = param_str.find(" ")
        if space_idx == -1:
            yield event.plain_result(
                "❌ 格式错误。用法: /broadcast_to <群号[,群号,...]> <消息内容>"
            )
            return

        group_id_str = param_str[:space_idx].strip()
        # 群号列表（英文逗号分隔）
        target_groups = [
            gid.strip() for gid in group_id_str.split(",") if gid.strip()
        ]

        # 消息部分直接使用消息链，避免仅获取纯文本导致富媒体丢失
        # 此处通过 event.message_obj.message 获取完整消息链
        full_chain = event.message_obj.message
        if not full_chain:
            yield event.plain_result("⚠️ 消息内容为空。")
            return

        # 构建群聊 UMO
        platform_id = event.unified_msg_origin.split(":")[0]
        umos = []
        for gid in target_groups:
            umos.append(f"{platform_id}:GroupMessage:{gid}")

        result = await self._send_broadcast(umos, full_chain, event)
        yield event.plain_result(result)

    # ---------- 定时广播 ----------

    def _start_scheduler(self):
        """启动 AsyncIOScheduler 并加载定时广播任务。"""
        if self.scheduler:
            logger.warning("[广播插件] 调度器已运行，跳过重复启动。")
            return

        self.scheduler = AsyncIOScheduler()
        self._load_scheduled_jobs()
        self.scheduler.start()
        logger.info("[广播插件] 定时广播调度器已启动。")

    def _load_scheduled_jobs(self):
        """从配置中读取并注册定时广播任务。"""
        config = self._get_config()
        scheduled_str = config.get("scheduled_broadcasts", "[]")
        try:
            tasks = json.loads(scheduled_str)
        except json.JSONDecodeError:
            logger.error("[广播插件] 定时广播配置解析失败，已跳过。")
            return

        if not isinstance(tasks, list):
            logger.error("[广播插件] 定时广播配置应为 JSON 数组。")
            return

        for idx, task in enumerate(tasks):
            cron_expr = task.get("cron", "")
            groups = task.get("groups", [])
            message_data = task.get("message", [])

            if not cron_expr or not groups or not message_data:
                logger.warning(
                    f"[广播插件] 定时任务 #{idx} 配置不完整，已跳过。"
                )
                continue

            try:
                trigger = CronTrigger.from_crontab(cron_expr)
            except ValueError as e:
                logger.error(
                    f"[广播插件] 定时任务 #{idx} cron 表达式 '{cron_expr}' 无效: {e}"
                )
                continue

            # 将闭包捕获的变量通过默认参数绑定，避免 for 循环延迟引用问题
            async def job_func(g=groups, msg=message_data):
                await self._execute_scheduled_broadcast(g, msg)

            self.scheduler.add_job(
                func=job_func,
                trigger=trigger,
                id=f"broadcast_job_{idx}",
                name=f"定时广播任务 #{idx}",
                replace_existing=True,
            )
            logger.info(
                f"[广播插件] 已注册定时广播任务 #{idx}: cron='{cron_expr}', "
                f"groups={groups}"
            )

    async def _execute_scheduled_broadcast(
        self, groups: List[str], message_data: List[dict]
    ):
        """
        执行定时广播的逻辑。
        groups 中的 "all" 表示全部群，否则视为具体群号列表。
        """
        try:
            # 构建消息链
            chain = self._parse_message_chain(message_data)
            if not chain:
                logger.error("[广播插件] 定时广播消息链为空，取消发送。")
                return

            # 获取 platform_id（此处简单取第一个适配器，可根据实际情况调整）
            platform_id = "aiocqhttp_default"
            umos = []
            if "all" in groups:
                # 全群发送：从配置读取群号列表
                config = self._get_config()
                group_ids_str = config.get("group_ids", "")
                if not group_ids_str:
                    logger.error(
                        "[广播插件] 定时广播配置了 'all' 但未提供群号列表。"
                    )
                    return
                group_ids = [
                    gid.strip() for gid in group_ids_str.split(",") if gid.strip()
                ]
                for gid in group_ids:
                    umos.append(f"{platform_id}:GroupMessage:{gid}")
            else:
                # 指定群发送
                for gid in groups:
                    umos.append(f"{platform_id}:GroupMessage:{gid}")

            logger.info(
                f"[广播插件] 定时广播开始执行，目标 {len(umos)} 个群。"
            )
            for umo in umos:
                try:
                    await self.context.send_message(umo, chain)
                    logger.info(f"[广播插件] 定时广播已发送至 {umo}")
                except Exception as e:
                    logger.error(
                        f"[广播插件] 定时广播发送至 {umo} 失败: {e}"
                    )
        except Exception as e:
            logger.exception(f"[广播插件] 定时广播执行异常: {e}")