import json
import os
from typing import List, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.message_components import (
    Plain,
    Image,
    Video,
    File,
    At,
    Record,
)

FRIEND_MSG_TYPES = ("FriendMessage", "PrivateMessage")


@register("astrbot_plugin_broadcast", "Care", "群广播功能支持定时，特定群聊广播", "1.2.0", "https://github.com/Care0721")
class BroadcastPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.scheduler: Optional[AsyncIOScheduler] = None
        self._plugin_dir = os.path.dirname(os.path.abspath(__file__))
        self._config_path = os.path.join(self._plugin_dir, "_conf.json")

    # ---------- 生命周期 ----------
    async def initialize(self):
        logger.info("[广播插件] 初始化...")
        self._start_scheduler()
        logger.info("[广播插件] 初始化完成")

    async def terminate(self):
        logger.info("[广播插件] 正在停止...")
        if self.scheduler:
            self.scheduler.shutdown(wait=False)
            self.scheduler = None
        logger.info("[广播插件] 已停止")

    # ---------- 配置工具 ----------
    def _get_config(self) -> dict:
        """读取默认配置并合并用户保存的 _conf.json"""
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
        raw = config.get("admin_ids", "")
        if not raw:
            return []
        # 兼容中英文逗号、空格等
        import re
        return [uid.strip() for uid in re.split(r'[，,;；\s]+', raw) if uid.strip()]

    def _is_admin(self, event: AstrMessageEvent, admin_ids: List[str]) -> bool:
        """检查权限并输出日志方便排查"""
        sender_id = event.get_sender_id()
        # 日志打印实际获取到的 id，方便管理员核对
        logger.info(f"[广播插件] 发送者ID: {sender_id}，管理员列表: {admin_ids}")
        return str(sender_id) in admin_ids

    def _get_adapter_id(self, event: AstrMessageEvent) -> str:
        """从 unified_msg_origin 中提取平台适配器 ID"""
        umo = event.unified_msg_origin
        parts = umo.split(":")
        return parts[0] if len(parts) >= 1 else "unknown"

    async def _get_all_group_umos(self, event: AstrMessageEvent) -> List[str]:
        """获取配置中所有群聊的 unified_msg_origin"""
        config = self._get_config()
        group_ids_str = config.get("group_ids", "")
        if not group_ids_str:
            logger.warning("[广播插件] 未配置 group_ids，请在 WebUI 中填写所有群号")
            return []

        group_ids = [gid.strip() for gid in group_ids_str.split(",") if gid.strip()]
        adapter_id = self._get_adapter_id(event)
        return [f"{adapter_id}:GroupMessage:{gid}" for gid in group_ids]

    def _parse_message_chain(self, chain_data: List[dict]) -> List:
        """将 JSON 消息链数组转为 AstrBot 组件对象"""
        components = []
        for item in chain_data:
            ctype = item.get("type", "")
            data = item.get("data", {})
            if ctype == "Plain":
                components.append(Plain(text=data.get("text", "")))
            elif ctype == "Image":
                if "file" in data:
                    components.append(Image.fromFileSystem(data["file"]))
                elif "url" in data:
                    components.append(Image.fromURL(data["url"]))
            elif ctype == "Video":
                if "file" in data:
                    components.append(Video.fromFileSystem(data["file"]))
                elif "url" in data:
                    components.append(Video.fromURL(data["url"]))
            elif ctype == "File":
                components.append(File(file=data.get("file", ""), name=data.get("name", "")))
            elif ctype == "At":
                components.append(At(qq=data.get("qq", "")))
            elif ctype == "Record":
                if "file" in data:
                    components.append(Record(file=data["file"], url=data.get("url", "")))
                elif "url" in data:
                    components.append(Record(file="", url=data["url"]))
            else:
                logger.warning(f"[广播插件] 未知组件类型: {ctype}")
        return components

    async def _send_broadcast(self, umo_list: List[str], chain: List) -> str:
        """向一组 UMO 发送消息，返回结果文本"""
        success = 0
        fail = 0
        for umo in umo_list:
            try:
                await self.context.send_message(umo, chain)
                success += 1
                logger.info(f"[广播插件] 发送成功: {umo}")
            except Exception as e:
                fail += 1
                logger.error(f"[广播插件] 发送失败 {umo}: {e}")
        msg = f"广播发送完成：成功 {success} 个，失败 {fail} 个。"
        if fail > 0:
            msg += "\n请检查控制台日志排查失败原因。"
        return msg

    def _is_friend_msg(self, event: AstrMessageEvent) -> bool:
        """判断是否为私聊消息（兼容不同适配器类型名）"""
        return event.get_message_type() in FRIEND_MSG_TYPES

    # ---------- 私聊指令 ----------

    @filter.command("broadcast_all")
    async def broadcast_all(self, event: AstrMessageEvent):
        """管理员私聊向所有群广播"""
        # 温馨提示：如果是群聊，提醒只能用私聊
        if not self._is_friend_msg(event):
            yield event.plain_result("⛔ 此指令仅限私聊使用，请直接私聊机器人。")
            return

        config = self._get_config()
        admin_ids = self._get_admin_ids(config)
        if not self._is_admin(event, admin_ids):
            yield event.plain_result("⛔ 您没有权限使用此指令。\n若已配置管理员，请检查发送者ID是否匹配（查看控制台日志）。")
            return

        umos = await self._get_all_group_umos(event)
        if not umos:
            yield event.plain_result("⚠️ 未找到任何群组，请先在 WebUI 配置「group_ids」字段。")
            return

        chain = event.message_obj.message
        if not chain:
            yield event.plain_result("⚠️ 消息内容为空。")
            return

        result = await self._send_broadcast(umos, chain)
        yield event.plain_result(result)

    @filter.command("broadcast_to")
    async def broadcast_to(self, event: AstrMessageEvent):
        """管理员私聊向指定群广播（多个群号用英文逗号分隔）"""
        if not self._is_friend_msg(event):
            yield event.plain_result("⛔ 此指令仅限私聊使用，请直接私聊机器人。")
            return

        config = self._get_config()
        admin_ids = self._get_admin_ids(config)
        if not self._is_admin(event, admin_ids):
            yield event.plain_result("⛔ 您没有权限使用此指令。\n若已配置管理员，请检查发送者ID是否匹配（查看控制台日志）。")
            return

        # 解析指令参数
        msg_str = event.message_str.strip()
        # 移除指令前缀 "/broadcast_to "，注意可能有多个空格
        cmd_prefix = "/broadcast_to"
        if not msg_str.startswith(cmd_prefix):
            yield event.plain_result("❌ 指令必须以 / 开头，格式：/broadcast_to 群号 消息内容")
            return

        param_str = msg_str[len(cmd_prefix):].strip()
        # 分离群号和消息部分：找到第一个空白字符
        if not param_str:
            yield event.plain_result("❌ 格式错误。正确用法：/broadcast_to 群号[,群号,...] 消息内容")
            return

        # 智能分割：第一个空白字符前为群号部分，后面全部为消息
        space_idx = -1
        for i, ch in enumerate(param_str):
            if ch in (' ', '\t', '\u3000'):  # 空格、制表、全角空格
                space_idx = i
                break

        if space_idx == -1:
            yield event.plain_result("❌ 格式错误。请用空格分隔群号和消息。\n示例：/broadcast_to 973878128 你好")
            return

        group_id_str = param_str[:space_idx].strip()
        # 群号后面剩下的部分是消息，但消息链已从 event 中获取，这里只做校验
        if not group_id_str:
            yield event.plain_result("❌ 群号不能为空。")
            return

        target_groups = [gid.strip() for gid in group_id_str.split(",") if gid.strip()]
        if not target_groups:
            yield event.plain_result("❌ 群号格式错误。")
            return

        # 获取消息链（直接用 event 的消息对象，支持富媒体）
        chain = event.message_obj.message
        if not chain:
            yield event.plain_result("⚠️ 消息内容为空。")
            return

        adapter_id = self._get_adapter_id(event)
        umos = [f"{adapter_id}:GroupMessage:{gid}" for gid in target_groups]

        result = await self._send_broadcast(umos, chain)
        yield event.plain_result(result)

    # ---------- 定时广播 ----------
    def _start_scheduler(self):
        if self.scheduler:
            return
        self.scheduler = AsyncIOScheduler()
        self._load_scheduled_jobs()
        self.scheduler.start()
        logger.info("[广播插件] 定时调度器已启动")

    def _load_scheduled_jobs(self):
        config = self._get_config()
        scheduled_str = config.get("scheduled_broadcasts", "[]")
        try:
            tasks = json.loads(scheduled_str)
        except json.JSONDecodeError:
            logger.error("[广播插件] 定时广播配置 JSON 解析失败")
            return
        if not isinstance(tasks, list):
            logger.error("[广播插件] scheduled_broadcasts 应为 JSON 数组")
            return

        for idx, task in enumerate(tasks):
            cron_expr = task.get("cron", "")
            groups = task.get("groups", [])
            message_data = task.get("message", [])
            if not cron_expr or not groups or not message_data:
                logger.warning(f"[广播插件] 定时任务 #{idx} 配置不完整，跳过")
                continue
            try:
                trigger = CronTrigger.from_crontab(cron_expr)
            except ValueError as e:
                logger.error(f"[广播插件] 定时任务 #{idx} cron 无效 '{cron_expr}': {e}")
                continue

            async def job_func(g=groups, msg=message_data):
                await self._execute_scheduled_broadcast(g, msg)

            self.scheduler.add_job(
                func=job_func,
                trigger=trigger,
                id=f"broadcast_job_{idx}",
                name=f"定时广播 #{idx}",
                replace_existing=True,
            )
            logger.info(f"[广播插件] 已注册定时任务 #{idx}: cron='{cron_expr}', groups={groups}")

    async def _execute_scheduled_broadcast(self, groups: List[str], message_data: List[dict]):
        try:
            chain = self._parse_message_chain(message_data)
            if not chain:
                logger.error("[广播插件] 定时广播消息链为空")
                return
            config = self._get_config()
            # 获取群列表：支持 "all" 或具体群号
            if "all" in groups:
                group_ids_str = config.get("group_ids", "")
                if not group_ids_str:
                    logger.error("[广播插件] 定时广播设置了 all 但未配置 group_ids")
                    return
                target_group_ids = [gid.strip() for gid in group_ids_str.split(",") if gid.strip()]
            else:
                target_group_ids = groups

            # 尝试获取适配器 ID（从配置或者使用默认值）
            # 因为定时任务没有 event 对象，这里默认使用 "aiocqhttp_default"，
            # 如果使用其他适配器请修改此处。
            adapter_id = config.get("adapter_id", "aiocqhttp_default")
            umos = [f"{adapter_id}:GroupMessage:{gid}" for gid in target_group_ids]
            logger.info(f"[广播插件] 定时广播开始，目标 {len(umos)} 个群")
            for umo in umos:
                try:
                    await self.context.send_message(umo, chain)
                    logger.info(f"[广播插件] 定时发送成功: {umo}")
                except Exception as e:
                    logger.error(f"[广播插件] 定时发送失败 {umo}: {e}")
        except Exception as e:
            logger.exception(f"[广播插件] 定时广播执行异常: {e}")