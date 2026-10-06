"""Complete navigation for the installed Sky plugin; this module never dispatches."""
from __future__ import annotations

import re


_USAGE = {}


def _button(label, command, *, enter=False, syntax='', example='', description='',
            admin_only=False, private_only=False, group_only=False):
    result = {'label': label, 'command': command, 'enter': enter}
    for name, enabled in (('admin_only', admin_only), ('private_only', private_only),
                          ('group_only', group_only)):
        if enabled:
            result[name] = True
    if syntax:
        _USAGE[command.casefold().strip()] = (syntax, example or syntax, description)
    return result


_BUTTONS = [
    # Keep the first four useful for ordinary-result quick navigation.
    _button('光遇帮助', '/光遇帮助', enter=True),
    _button('每日任务', '/每日任务', enter=True),
    _button('光遇状态', '/光遇状态', enter=True),
    _button('光遇ID列表', '/光遇ID列表', enter=True),
    _button('明日任务', '/明日任务', enter=True),
    _button('活动货币位置', '/活动货币位置', enter=True),
    _button('今日魔法', '/今日魔法', enter=True),
    _button('季蜡', '/季蜡', enter=True),
    _button('大蜡烛', '/大蜡烛', enter=True),
    _button('任务图', '/任务图', enter=True),
    _button('季节任务', '/季节任务', enter=True),
    _button('今日碎石', '/今日碎石', enter=True),
    _button('本月碎石', '/本月碎石', enter=True),
    _button('指定月份碎石', '/YYYY年M月碎石', syntax='/YYYY年M月碎石',
            example='/2026年9月碎石', description='把 YYYY 和 M 换成实际年份与月份，查询该月碎石日历。'),
    _button('碎石路线说明', '/碎石路线图', enter=True),
    _button('碎石规律说明', '/碎石规律说明', enter=True),
    _button('光遇公告', '/光遇公告', enter=True),
    _button('光翼统计', '/光翼统计', enter=True),
    _button('光遇进度', '/光遇进度', enter=True),
    _button('游戏进度', '/游戏进度', enter=True),
    _button('季节进度', '/季节进度', enter=True),
    _button('活动进度', '/活动进度', enter=True),
    _button('季节列表', '/季节列表', enter=True),
    _button('季节多久未复刻', '/XX季多久未复刻', syntax='/<季节名>季多久未复刻',
            example='/追光季多久未复刻', description='填写实际季节名称；不要直接发送 XX 占位符。'),
    _button('全图鉴参考', '/全图鉴参考', enter=True),
    _button('指定年份复刻记录', '/YYYY年复刻记录', syntax='/YYYY年复刻记录',
            example='/2026年复刻记录', description='把 YYYY 换成要查询的年份，也支持两位年份。'),
    _button('全部年复刻记录', '/全部年复刻记录', enter=True),
    _button('指定年份复刻日历', '/YYYY年复刻日历', syntax='/YYYY年复刻日历',
            example='/2026年复刻日历', description='填写要查询的年份，查看该年复刻日历。'),
    _button('光遇本月日历', '/光遇本月日历', enter=True),
    _button('光遇下载', '/光遇下载', enter=True),
    _button('绑定光遇短ID', '/光遇绑定', syntax='/光遇绑定 <游戏短ID>',
            description='填写自己的游戏数字短ID；本次只显示用法，不会创建绑定。'),
    _button('切换光遇账号', '/光遇切换', syntax='/光遇切换 <序号>',
            description='先查看光遇ID列表，再填写要使用的账号序号。'),
    _button('删除光遇账号', '/光遇删除', syntax='/光遇删除 <序号>',
            description='先查看光遇ID列表，确认要删除的账号序号后手动发送。'),
    _button('光翼查询', '/光翼查询', enter=True),
    _button('光翼详情', '/光翼详情', enter=True),
    _button('绑定好友码查身高', '/光遇绑定好友码', syntax='/光遇绑定好友码 <好友码>',
            example='/光遇绑定好友码 ABCD-EFGH-IJKL', description='填写自己的好友码，沿用原插件的账号绑定规则。'),
    _button('绑定游戏长ID', '/光遇绑定长ID', syntax='/光遇绑定长ID <游戏长ID>',
            description='填写自己的游戏长ID，不使用其他用户的账号信息。'),
    _button('光遇身高查询', '/光遇身高查询', enter=True),
    _button('光遇历史身高', '/光遇历史身高', enter=True),
    _button('光遇身高排行榜', '/光遇身高排行榜', enter=True),
    _button('光遇绘画分享', '/光遇绘画分享', enter=True),
    _button('存入好友盲盒', '/存入盲盒', private_only=True,
            syntax='/存入盲盒<好友码>*<国服/国际服/测试服>',
            example='/存入盲盒ABCD-EFGH-IJKL*国服', description='只能私聊操作；填写自己愿意公开分享的好友码和服务器。'),
    _button('随机好友', '/随机好友', enter=True),
    _button('Token绑定帮助', '/光遇token帮助', enter=True),
    _button('私聊绑定Token', '/绑定token', private_only=True,
            syntax='/绑定token <完整链接或token>', description='只在私聊中手动发送自己的完整链接或token；不要发到群里。'),
    _button('私聊解绑Token', '/解绑token', private_only=True,
            syntax='/解绑token', description='确认解除自己的token绑定后，在私聊中手动发送此命令。'),
    _button('Token绑定状态', '/token绑定状态', enter=True),
    _button('蜡烛变化查询', '/蜡烛变化查询', enter=True),
    _button('季节蜡烛查询', '/季节蜡烛查询', enter=True),
    _button('爱心变化查询', '/爱心变化查询', enter=True),
    _button('升华蜡烛查询', '/升华蜡烛查询', enter=True),
    _button('点赞爱心查询', '/点赞爱心查询', enter=True),
    _button('魔法变化查询', '/魔法变化查询', enter=True),
    _button('代币变化查询', '/代币变化查询', enter=True),
    _button('我的光遇ID', '/我的光遇id', enter=True),
    _button('礼包查询帮助', '/礼包查询帮助', enter=True),
    _button('绑定国服礼包账号', '/国服id绑定', syntax='/国服id绑定 <好友码或长ID>',
            description='独角兽来源填写好友码，t1qq来源填写长ID；沿用管理员配置的接口来源。'),
    _button('国服ID列表', '/国服id列表', enter=True),
    _button('切换国服礼包账号', '/国服id切换', syntax='/国服id切换 <序号>',
            description='先查看国服id列表，再填写要使用的账号序号。'),
    _button('删除国服礼包账号', '/国服id删除', syntax='/国服id删除 <序号>',
            description='确认要移除的账号序号后手动发送；本次只显示用法。'),
    _button('国服礼包查询', '/国服礼包查询', enter=True),
]

for _name in ('每日任务推送', '老奶奶干饭提醒', '献祭刷新提醒', '碎石提醒'):
    for _action in ('开启', '关闭'):
        _BUTTONS.append(_button(_action + _name, '/' + _action + _name,
                                enter=True, admin_only=True, group_only=True))
_BUTTONS.extend([
    _button('光遇推送状态', '/光遇推送状态', enter=True, admin_only=True, group_only=True),
    _button('光遇接口状态', '/光遇接口状态', enter=True, admin_only=True),
    _button('光遇更新说明', '/光遇更新', enter=True, admin_only=True),
])

SKY_FAMILY = ('光遇完整菜单',
    '攻略、信息、光翼、身高、好友、在线资产和礼包；参数按钮先显示填写用法。'
    '账号凭据和盲盒存入只在私聊操作，群提醒继续检查原插件的管理员权限。', _BUTTONS)


def sky_buttons(*, is_admin=False, is_private=False):
    return [dict(button) for button in _BUTTONS
            if (is_admin or not button.get('admin_only'))
            and (is_private or not button.get('private_only'))
            and (not is_private or not button.get('group_only'))]


def sky_help_family(command):
    return isinstance(command, str) and bool(re.fullmatch(
        r'[#/]?(?:光遇|sky)(?:帮助|菜单|娱乐菜单)', command.strip(), re.I))


def sky_usage(command):
    if not isinstance(command, str):
        return None
    text = command.strip()
    if not text or any(ord(char) < 32 for char in text):
        return None
    normalized = '/' + text.lstrip('/#')
    key = normalized.casefold()
    return _USAGE.get(key) or next((value for prefix, value in _USAGE.items()
        if key.startswith(prefix + ' ')), None)
