"""Recognize navigation/help replies without changing ordinary query results."""
from __future__ import annotations

import re

from .menus import FAMILIES, FAMILY_ALIASES


def category_image_spec(event):
    command = event.get_message_str().strip().lstrip('/#')
    match = re.fullmatch(r'(?:功能菜单|官方菜单)\s+(.+)', command)
    if not match:
        return None
    category = match[1].strip()
    category = FAMILY_ALIASES.get(category.lower(), category)
    if category not in FAMILIES:
        return None
    title, description, _ = FAMILIES[category]
    if category in ('学习', '记忆') and not event.is_admin():
        description = '这些命令仅供原插件授权的管理员使用。'
    return title, description


HELP_COMMANDS = {
    '资讯菜单': '资讯菜单', '资讯帮助': '资讯菜单', 'dailyhub': '资讯菜单',
    '签到帮助': '签到帮助', '点赞帮助': '点赞帮助', '扩展帮助': '扩展帮助',
    'steam help': 'Steam 帮助',
    'lmem help': '长期记忆帮助', 'rhelp': '音乐与解析帮助', 'r帮助': '音乐与解析帮助',
    '光遇帮助': '光遇帮助', '光遇菜单': '光遇菜单', '光遇娱乐菜单': '光遇娱乐菜单',
    'sky帮助': '光遇帮助', 'sky菜单': '光遇菜单', 'sky娱乐菜单': '光遇娱乐菜单',
    '光遇token帮助': '光遇 Token 绑定帮助', '礼包查询帮助': '礼包查询帮助',
    '绑定token': '光遇 Token 绑定帮助', '这是我的token': '光遇 Token 绑定帮助',
    '我的token': '光遇 Token 绑定帮助',
    '王者帮助': '王者帮助', '查询战绩帮助': '战绩查询帮助',
    '营地观战帮助': '营地观战帮助', '营地消息帮助': '营地消息帮助',
    '群管帮助': 'QQ群管理 · 官方机器人', '群管菜单': 'QQ群管理 · 官方机器人',
}


def _command_lines(text, prefix):
    """Count distinct command entries, allowing Markdown bullets/backticks."""
    return len(set(re.findall(r'(?m)^[^\w\r\n]{0,8}[/#](' + prefix + r')', text, re.I)))


def text_help_title(event, hint, text):
    """Recognize the actual help body after its original handler has run.

    A command alone is insufficient: permission failures and not-ready replies
    must remain text. Known headings also cover short menus without the word
    "help". Images are excluded by the caller; hints never bypass these checks.
    """
    if not isinstance(text, str):
        return None
    raw = event.get_message_str().strip()
    if '\n' in raw or '\r' in raw:
        return None
    command = ' '.join(raw.lstrip('/#').split()).casefold()
    body = text.strip()
    if len(body.splitlines()) < 3:
        return None
    first_line = re.sub(r'^[^\w]+', '', body.splitlines()[0]).casefold()
    if first_line.startswith(('未启用', '未执行', '权限', '无权限', '拒绝', '抱歉',
                              '服务未就绪', '插件服务未就绪', '插件尚未', '请先',
                              '失败', '错误', '当前平台不支持', '未找到', '搜索',
                              'permission', 'access denied', 'not ready', 'error', 'failed')):
        return None
    title = HELP_COMMANDS.get(command)
    if command in ('群管帮助', '群管菜单'):
        return title if (first_line.startswith('qq群管理 · 官方机器人')
                         and _command_lines(body, r'群管(?:帮助|状态)|禁言(?:状态)?|解禁|群友信息|入群申请|'
                                            r'踢了|群拉黑|批准|驳回|群黑名单|解除群拉黑') >= 2) else None
    if command in ('资讯菜单', '资讯帮助', 'dailyhub'):
        return title if (body.startswith('📚 每日资讯推送 · 可用源\n')
                         and '/订阅资讯' in body and '/推送' in body) else None
    if command == '扩展帮助':
        return title if (body.startswith('状态图\n#状态') and '#状态pro' in body) else None
    if command == '点赞帮助':
        return title if (body.startswith('QQ 名片点赞\n')
                         and '#赞我' in body and '#点赞帮助' in body) else None
    if command == 'steam help':
        return title if (body.startswith('Steam状态监控插件指令：\n')
                         and _command_lines(body, r'steam\s+[a-z_]+') >= 2) else None
    if command == 'lmem help':
        # Translations are external resources (zh/en/ru); their commands are stable.
        return title if _command_lines(body, r'lmem\s+[a-z_]+') >= 2 else None
    if re.fullmatch(r'rhelp(?: .*)?|r(?:插件)?(?:命令|帮助|菜单|help|说明|功能|指令|使用说明)', command):
        return '音乐与解析帮助' if (re.match(r'RConsole v[\d.]+ · AstrBot', body)
                                  and _command_lines(body, r'[^\s/]+') >= 2) else None
    if re.fullmatch(r'(?:光遇|sky)(?:帮助|菜单|娱乐菜单)', command):
        sky_body = body.removeprefix('光遇菜单\n')
        return title if (sky_body.startswith('Tlon-Sky 光遇菜单\n')
                         and '【攻略】' in sky_body and '光遇ID列表' in sky_body) else None
    if command == '礼包查询帮助':
        return title if (body.startswith('国服id绑定 ')
                         and '\n国服id列表\n' in body and '\n国服礼包查询\n' in body) else None
    # Exact no-argument entries only: never capture submitted tokens or links.
    if command in ('光遇token帮助', '绑定token', '这是我的token', '我的token'):
        return title if (body.startswith('Token 获取与绑定\n')
                         and '私聊机器人发送「绑定token' in body) else None
    if re.fullmatch(r'王者(?:荣耀|农药)?(?:插件|plugin)?(?:帮助|help)\s*.*|'
                    r'(?:查询战绩|英雄(?:相关)?|皮肤|营地(?:id)?共享|(?:营地)?观战|'
                    r'营地消息|战绩推送|群战绩报告)帮助', command):
        return (title or '王者帮助') if (re.match(r'[📖🔍] 王者插件指令(?:\n|（关键词：)', body)
                                      and re.search(r'(?m)^#.+ —— ', body)) else None
    resource = re.fullmatch(r'(pixiv帮助|pixiv_help|pica帮助|picahelp|jm帮助|jmhelp)(?: .*)?|'
                            r'(pica|jm|jmhelp0)', command)
    if resource:
        name = resource[1] or resource[2]
        if name.startswith('pica'):
            return 'Pica 帮助' if (body.startswith('📖 哔咔漫画插件 (Pica-Comics)\n')
                                  and _command_lines(body, r'pica\w+') >= 2) else None
        if name.startswith('jm'):
            return 'JM 帮助' if (body.startswith('📖 JM漫画插件 (JMComic)\n')
                                and _command_lines(body, r'jm\w+') >= 2) else None
        # The Pixiv help text is an external, user-replaceable JSON resource.
        return 'Pixiv 帮助' if (re.search(r'pixiv.*(?:帮助|help)|(?:帮助|help).*pixiv', body.splitlines()[0], re.I)
                              and _command_lines(body, r'pixiv\w*') >= 2) else None
    return None
