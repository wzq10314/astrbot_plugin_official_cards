"""Owner-bound button usage text. This module never dispatches a command."""
from __future__ import annotations

import html
import math
import re
import secrets
import time
import unicodedata
from collections import OrderedDict

from .keyboard_pages import event_owner
from .resource_menus import resource_usage
from .sky_menu import sky_usage


_USAGE = {
    "#点歌": ("#点歌 <歌曲名或歌手名>", "#点歌 晴天",
              "填写歌曲名或歌手名；收到歌曲列表后发送 #听1 选择第一首。"),
    "#rparse": ("#rparse <分享链接或BV号>", "#rparse BV1xx411c7mD",
                "填写分享链接或BV号，支持B站、抖音、小红书分享链接。"),
    "/steam price": ("/steam price <游戏名或Steam商店链接>", "/steam price 黑神话：悟空",
                     "填写游戏名或Steam商店链接；出现候选游戏列表后回复序号。"),
    "/lmem search": ("/lmem search <关键词> [数量]", "/lmem search 偏好 5",
                     "填写搜索关键词，可加返回数量；仅管理员可用，搜索当前会话记忆。"),
    "#王者对比": ("#王者对比 <对方营地ID>", "#王者对比 123456789",
                  "填写要对比的营地ID；也可用两个已绑定账号的序号，例如 #王者对比 1 2。"),
    "#查战力": ("#查战力 <英雄名>", "#查战力 孙悟空", "填写英雄的完整名称。"),
    "#查战绩": ("#查战绩 <英雄名>", "#查战绩 妲己", "填写要查看战绩的英雄名称。"),
    "#查皮肤": ("#查皮肤 <英雄名>", "#查皮肤 百里守约", "填写要查看皮肤的英雄名称。"),
    "#缺皮肤": ("#缺皮肤 [英雄名或营地ID]", "#缺皮肤 妲己",
                "可填写英雄名或营地ID；省略参数时查询当前绑定账号。"),
    "#英雄攻略": ("#英雄攻略 <英雄名>", "#英雄攻略 孙悟空", "填写英雄名，查看出装、铭文与技能攻略。"),
    "#绑定营地": ("#绑定营地 <营地ID>", "#绑定营地 123456789",
                  "填写数字营地ID；只发送 #绑定营地 可以查看ID获取教程。"),
    "#切换营地": ("#切换营地 <账号序号>", "#切换营地2",
                  "先发送 #营地ID 查看已绑定账号，再填写要使用的账号序号。"),
    "#删除营地": ("#删除营地 <账号序号>", "#删除营地2",
                  "先发送 #营地ID 查看已绑定账号，确认要移除的账号序号后再发送。"),
}


def _safe_text(value):
    return (isinstance(value, str) and bool(value.strip()) and len(value) <= 512
            and not any(unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
                        for char in value))


def _code_block(value):
    # A command containing backticks cannot close a longer fenced code block.
    fence = "`" * max(3, 1 + max((len(run) for run in re.findall(r"`+", value)), default=0))
    return f"{fence}text\n{value}\n{fence}"


def _label_text(value):
    escaped = html.escape(value, quote=False)
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|>])", r"\\\1", escaped)


def usage_text(label, command):
    """Render validated, inert instructions, never a successful-action claim."""
    if not _safe_text(label) or not _safe_text(command):
        return None
    command = command.strip()
    usage = resource_usage(command) or sky_usage(command) or next((value for prefix, value in _USAGE.items()
                  if command == prefix or command.startswith(prefix + " ")
                  or (prefix in {"#绑定营地", "#切换营地", "#删除营地"}
                      and command.removeprefix(prefix).isdigit()
                      and command.startswith(prefix))), None)
    lines = [f"{_label_text(label.strip())} · 使用方法"]
    if usage is not None:
        syntax, example, explanation = usage
        lines.extend((explanation, "命令格式：\n" + _code_block(syntax), "示例：\n" + _code_block(example)))
    else:
        lines.extend(("需要参数时请按该功能的帮助补全；确认完整命令后再手动发送。",
                      "命令：\n" + _code_block(command)))
    lines.append("本次仅显示用法，未执行操作。")
    return "\n\n".join(lines)


class ButtonPromptStore:
    def __init__(self, *, ttl=3600, max_entries=1024, clock=time.monotonic):
        ttl = float(ttl)
        if not math.isfinite(ttl):
            raise ValueError("button prompt TTL must be finite")
        self.ttl = max(1, min(ttl, 3600))
        self.max_entries = max(1, min(int(max_entries), 1024))
        self.clock = clock
        self.entries = OrderedDict()

    def clear(self):
        self.entries.clear()

    def _cleanup(self):
        now = self.clock()
        for token, entry in list(self.entries.items()):
            if entry[0] <= now:
                del self.entries[token]

    def create(self, label, command, event):
        owner = event_owner(event)
        if owner is None or not _safe_text(label) or not _safe_text(command):
            return None
        self._cleanup()
        token = secrets.token_urlsafe(18)
        # Strings and tuples form an immutable snapshot of this request.
        self.entries[token] = (self.clock() + self.ttl, owner, label, command)
        while len(self.entries) > self.max_entries:
            self.entries.popitem(last=False)
        return f"/按钮用法 {token}"

    def get(self, token, event):
        if not isinstance(token, str) or re.fullmatch(r"[A-Za-z0-9_-]{24}", token) is None:
            return None
        self._cleanup()
        entry = self.entries.get(token)
        if entry is None or event_owner(event) != entry[1]:
            return None
        return usage_text(entry[2], entry[3])
