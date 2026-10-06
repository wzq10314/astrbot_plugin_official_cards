"""Static, reviewable navigation. No button invokes a destructive operation."""
from .support import button
from .keyboard_pages import MAX_BUTTONS
from .sky_menu import SKY_FAMILY, sky_help_family
from .resource_menus import RESOURCE_FAMILIES, resource_help_family
from .menu_routes import original_help_command


def _group_button(label, command, *, enter=False):
    return {**button(label, command, enter=enter), "group_only": True}


FAMILIES = {
    "资讯": ("每日资讯", "新闻、热榜和游戏资讯；定时推送受 QQ 官方回复窗口限制。", [
        button("资讯菜单", "/资讯菜单", enter=True), button("今日新闻", "/新闻", enter=True),
        button("免费游戏", "/epic", enter=True)]),
    "签到": ("签到与图片", "签到、成就和图片查询；涉及消费与设置的命令请自行确认发送。", [
        button("签到帮助", "/签到帮助", enter=True), button("签到状态", "/签到状态", enter=True),
        button("签到成就", "/签到成就", enter=True)]),
    "小猪": ("今日小猪", "保留抽取功能；QQ 官方未提供昵称或头像时使用中性展示。", [
        button("今日小猪", "/今日小猪", enter=True)]),
    "光遇": ("光遇", "攻略、状态和已绑定账号查询；账号凭据请只在私聊输入。", [
        button("光遇帮助", "/光遇帮助", enter=True), button("每日任务", "/每日任务", enter=True),
        button("光遇状态", "/光遇状态", enter=True), button("账号列表", "/光遇ID列表", enter=True)]),
    "小镇": ("心动小镇", "查看小镇日报、位置图和兑换码图。", [
        button("小镇日报", "/心动小镇", enter=True)]),
    "王者": ("王者营地", "查看命令帮助；账号绑定与凭据操作继续遵守原插件的私聊限制。", [
        button("王者帮助", "#王者帮助", enter=True), button("战绩帮助", "#查询战绩帮助", enter=True),
        button("观战帮助", "#营地观战帮助", enter=True), button("消息帮助", "#营地消息帮助", enter=True)]),
    "音乐": ("音乐与解析", "点击查看音乐、链接解析与下载功能；需要参数时会回复填写示例。", [
        button("音乐帮助", "#rhelp", enter=True), button("图文帮助", "#R帮助", enter=True),
        button("点歌", "#点歌 "), button("解析链接", "#rparse ")]),
    "Steam": ("Steam", "游戏状态、价格和排行榜；订阅推送仍受 QQ 官方回复窗口限制。", [
        button("Steam帮助", "/steam help", enter=True), button("游戏列表", "/steam list", enter=True),
        button("游戏价格", "/steam price ")]),
    "表情收藏": ("表情收藏", "支持图片消息的收集与查询；QQ 官方无法读取未投递给机器人的群消息。", [
        button("收藏状态", "/meme status", enter=True), button("收藏列表", "/meme list", enter=True)]),
    "记忆": ("长期记忆", "记忆与状态按原有权限检查执行。", [
        button("记忆帮助", "/lmem help", enter=True), button("搜索记忆", "/lmem search ")]),
    "学习": ("自学习", "保留学习服务；管理状态仅供原插件授权的管理员查看。", [
        button("学习状态", "/learning_status", enter=True)]),
    "扩展": ("QQ扩展与资源查询", "保留资源帮助和查询；QQ 官方接口不支持资料卡点赞。", [
        button("运行状态", "/状态", enter=True), button("扩展帮助", "/扩展帮助", enter=True), button("Pixiv帮助", "/pixiv帮助", enter=True),
        button("Pica帮助", "/pica帮助", enter=True), button("JM帮助", "/jm帮助", enter=True)]),
    "群管": ("QQ群管理", "支持成员查询、禁言、踢出、入群审核和群黑名单；需平台群管接口权限及机器人群管理员身份，未获授权会提示。原 OneBot 改名、头衔、群公告等功能仍不支持。", [
        _group_button("群管帮助", "/群管帮助", enter=True),
        _group_button("群管状态", "/群管状态", enter=True),
        _group_button("禁言状态", "/禁言状态", enter=True),
        _group_button("群友信息", "/群友信息", enter=True),
        _group_button("入群申请", "/入群申请", enter=True),
        _group_button("群黑名单", "/群黑名单", enter=True),
        _group_button("禁言成员", "/禁言 @成员 秒数"),
        _group_button("解禁成员", "/解禁 @成员"),
        _group_button("踢出成员", "/踢了 @成员"),
        _group_button("拉黑成员", "/群拉黑 @成员"),
        _group_button("批准申请", "/批准 member_openid 申请ID"),
        _group_button("驳回申请", "/驳回 member_openid 申请ID"),
        _group_button("解除群拉黑", "/解除群拉黑 member_openid")]),
    "贴表情": ("消息贴表情", "QQ 官方群聊未开放此插件依赖的 OneBot 消息表情回应接口。", []),
}

FAMILIES['光遇'] = SKY_FAMILY
FAMILIES.update(RESOURCE_FAMILIES)

FAMILY_ALIASES = {
    "sky": "光遇", "heartopia": "小镇", "rconsole": "音乐", "status": "扩展",
    "pixiv": "Pixiv", "pica": "Pica", "jm": "JM", "qq_like": "扩展",
    "gloryofkings": "王者", "dailyhub": "资讯", "get_px": "签到", "rollpig": "小猪",
    "steam": "Steam", "stealer": "表情收藏", "livingmemory": "记忆", "self_learning": "学习",
}


def event_is_private(event):
    try:
        message_type = getattr(event.message_obj, 'type', None)
        if getattr(message_type, 'name', '') == 'FRIEND_MESSAGE':
            return True
        return type(event.message_obj.raw_message).__name__ in ('C2CMessage', 'PatchedC2CMessage', 'DirectMessage')
    except AttributeError:
        return False


def visible_buttons(buttons, is_admin=True, *, is_private=False):
    return [b for b in buttons
            if (is_admin or (not b.get('admin_only')
                and not b.get("command", "").startswith("/lmem ")
                and b.get("command") not in ("/learning_status", "/affection_status")))
            and (is_private or not b.get('private_only'))
            and (not is_private or not b.get('group_only'))]


def menu_page(category: str = "", *, is_admin=True, is_private=False) -> tuple[str, list[dict]]:
    category = category.strip()
    category = FAMILY_ALIASES.get(category.lower(), category)
    if category in FAMILIES:
        title, description, buttons = FAMILIES[category]
        buttons = visible_buttons(buttons, is_admin, is_private=is_private)
        if category in ("记忆", "学习") and not is_admin:
            description = "这些命令仅供原插件授权的管理员使用。"
        text = f"# {title}\n\n{description}"
        if buttons:
            text += "\n\n" + "\n".join(f"- {b['label']}：{b['command'].strip()}" for b in buttons)
        return text, [*buttons, button("功能菜单", "/功能菜单", enter=True)]
    text = "# 功能菜单\n\n点击分类查看命令，也可输入 `/功能菜单 分类名`。\n\n"
    text += "\n".join(f"- **{name}**：{value[0]}" for name, value in FAMILIES.items())
    text += "\n\nQQ 官方已开放的能力使用图文和按钮；群管需接口权限及机器人群管理员身份，改名、头衔、群公告、资料卡点赞和群消息贴表情仍会明确提示不支持。"
    return text, [button(name, original_help_command(name) or f"/功能菜单 {name}", enter=True) for name in FAMILIES]


def infer_family(command: str) -> str:
    command = command.strip().lstrip("/#").lower()
    if command.startswith("功能菜单"):
        category = command.removeprefix("功能菜单").strip()
        return next((key for key in FAMILIES if key.lower() == category), "")
    families = (
        ("光遇", ("光遇", "每日任务", "今日魔法", "季蜡", "大蜡烛", "光翼", "sky")),
        ("小镇", ("心动小镇",)), ("王者", ("王者", "营地", "查询战绩")),
        ("资讯", ("资讯", "新闻", "60s", "epic", "微博", "it资讯", "it热搜", "金价")),
        ("签到", ("签到",)), ("小猪", ("今日小猪", "抽小猪", "我的小猪", "rollpig")),
        ("Steam", ("steam",)), ("表情收藏", ("meme",)), ("记忆", ("lmem",)),
        ("学习", ("learning_status", "affection_status")),
        ("群管", ("群管", "禁言", "解禁", "群友信息", "入群申请", "踢了", "群拉黑",
                  "批准", "驳回", "群黑名单", "解除群拉黑")),
        ("Pixiv", ("pixiv",)), ("Pica", ("pica",)), ("JM", ("jm",)),
        ("扩展", ("扩展帮助", "点赞")),
        ("音乐", ("点歌", "听歌", "音乐", "解析", "rc", "r帮助", "rhelp")),
    )
    return next((name for name, prefixes in families if command.startswith(prefixes)), "")


def buttons_for_event(event, hint: dict) -> list[dict]:
    if isinstance(hint.get("buttons"), list):
        buttons = hint["buttons"][:MAX_BUTTONS]
    else:
        family = hint.get("family") or infer_family(event.get_message_str())
        family = FAMILY_ALIASES.get(family, family)
        values = FAMILIES.get(family)
        command = event.get_message_str()
        full = (hint.get('menu') is True or resource_help_family(command)
                or sky_help_family(command) or hint.get('title') == '光遇菜单'
                or command.strip().lstrip('/#') in ('群管帮助', '群管菜单'))
        buttons = [*(values[2] if values and full else values[2][:4] if values else []),
                   button("功能菜单", "/功能菜单", enter=True)]
    return visible_buttons(buttons, event.is_admin(), is_private=event_is_private(event))
