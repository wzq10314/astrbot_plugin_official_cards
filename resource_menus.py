"""Navigation metadata for existing qq_like commands; no resource dispatch."""
from __future__ import annotations


_USAGE = {}


def _button(label, command, *, enter=False, syntax="", example="", description="",
            admin_only=False, private_only=False):
    item = {"label": label, "command": command, "enter": enter}
    if admin_only:
        item["admin_only"] = True
    if private_only:
        item["private_only"] = True
    if syntax:
        _USAGE[command.strip().split()[0].casefold()] = (syntax, example, description)
    return item


RESOURCE_FAMILIES = {
    "Pixiv": ("Pixiv 功能", "插画、画师、小说、订阅与下载管理；查询沿用原插件配置。", [
        _button("Pixiv帮助", "/pixiv帮助", enter=True),
        _button("搜索插画", "/pixiv", syntax="/pixiv <标签或关键词>",
                example="/pixiv 风景", description="填写标签或关键词；多个标签用逗号分隔。"),
        _button("最新插画", "/pixiv最新 illust", enter=True),
        _button("推荐插画", "/pixiv推荐", enter=True),
        _button("组合搜索", "/pixiv组合", syntax="/pixiv组合 <标签1>,<标签2>",
                example="/pixiv组合 风景,星空", description="填写需要同时满足的标签。"),
        _button("作品ID查询", "/pixivpid", syntax="/pixivpid <作品ID>",
                example="/pixivpid <作品ID>", description="填写要查询的数字作品ID。"),
        _button("每日排行", "/pixiv排行 day", enter=True),
        _button("相关作品", "/pixiv相关", syntax="/pixiv相关 <作品ID>",
                example="/pixiv相关 <作品ID>", description="填写参考作品的数字ID。"),
        _button("深度搜索", "/pixiv深搜", syntax="/pixiv深搜 <标签1>,<标签2>",
                example="/pixiv深搜 风景,星空", description="填写搜索标签，翻页数量沿用后台配置。"),
        _button("作品评论", "/pixiv评论", syntax="/pixiv评论 <作品ID> [偏移量]",
                example="/pixiv评论 <作品ID> 0", description="填写作品ID；偏移量可省略。"),
        _button("特辑详情", "/pixiv特辑", syntax="/pixiv特辑 <特辑ID>",
                example="/pixiv特辑 <特辑ID>", description="填写要查看的特辑ID。"),
        _button("搜索画师", "/pixiv搜画师", syntax="/pixiv搜画师 <画师名>",
                example="/pixiv搜画师 <画师名>", description="填写画师名称或搜索关键词。"),
        _button("画师详情", "/pixiv画师", syntax="/pixiv画师 <画师ID>",
                example="/pixiv画师 <画师ID>", description="填写画师的数字ID。"),
        _button("画师作品", "/pixiv作品", syntax="/pixiv作品 <画师ID>",
                example="/pixiv作品 <画师ID>", description="填写要查看作品的画师ID。"),
        _button("搜索小说", "/pixiv小说", syntax="/pixiv小说 <关键词>",
                example="/pixiv小说 旅行", description="填写小说标签或关键词。"),
        _button("推荐小说", "/pixiv小说推荐", enter=True),
        _button("最新小说", "/pixiv最新小说", enter=True),
        _button("小说系列", "/pixiv小说系列", syntax="/pixiv小说系列 <系列ID>",
                example="/pixiv小说系列 <系列ID>", description="填写小说系列的数字ID。"),
        _button("小说评论", "/pixiv小说评论", syntax="/pixiv小说评论 <小说ID> [偏移量]",
                example="/pixiv小说评论 <小说ID> 0", description="填写小说ID；偏移量可省略。"),
        _button("下载小说", "/pixiv小说下载", syntax="/pixiv小说下载 <小说ID>",
                example="/pixiv小说下载 <小说ID>", description="填写要下载的小说ID，文件格式沿用原插件。"),
        _button("订阅画师", "/pixiv订阅", syntax="/pixiv订阅 <画师ID>",
                example="/pixiv订阅 <画师ID>", description="填写画师ID，订阅保存在当前会话。"),
        _button("取消订阅", "/pixiv退订", syntax="/pixiv退订 <画师ID>",
                example="/pixiv退订 <画师ID>", description="先查看订阅列表，再填写要退订的画师ID。"),
        _button("订阅列表", "/pixiv订阅列表", enter=True),
        _button("添加推送标签", "/pixiv添加标签", syntax="/pixiv添加标签 <标签1>,<标签2>",
                example="/pixiv添加标签 风景,星空", description="为当前会话添加推送标签。"),
        _button("删除推送标签", "/pixiv删除标签", syntax="/pixiv删除标签 <序号>",
                example="/pixiv删除标签 <序号>", description="先查看标签列表，再填写要删除的序号。"),
        _button("推送标签列表", "/pixiv标签列表", enter=True),
        _button("暂停推送", "/pixiv暂停推送", enter=True),
        _button("恢复推送", "/pixiv恢复推送", enter=True),
        _button("推送状态", "/pixiv推送状态", enter=True),
        _button("立即推送", "/pixiv立即推送", enter=True),
        _button("添加推送榜单", "/pixiv添加榜单", syntax="/pixiv添加榜单 <模式> [YYYY-MM-DD]",
                example="/pixiv添加榜单 day", description="填写榜单模式，例如 day、week 或 month；日期可省略。"),
        _button("删除推送榜单", "/pixiv删除榜单", syntax="/pixiv删除榜单 <序号>",
                example="/pixiv删除榜单 <序号>", description="先查看榜单列表，再填写要删除的序号。"),
        _button("推送榜单列表", "/pixiv榜单列表", enter=True),
        _button("热门标签", "/pixiv热词", enter=True),
        _button("AI作品设置", "/pixivAI设置", admin_only=True,
                syntax="/pixivAI设置 <true或false>", example="/pixivAI设置 <true或false>",
                description="修改共享账号的AI作品显示设置，请先确认目标值。"),
        _button("插件设置", "/pixiv设置", admin_only=True,
                syntax="/pixiv设置 [参数名] [新值]", example="/pixiv设置 help",
                description="先查看设置帮助；此入口不会自动修改设置或提交凭据。"),
        _button("热度搜索", "/pixiv热门", syntax="/pixiv热门 <标签> [day|week|month|all] [页数]",
                example="/pixiv热门 风景 week 1", description="填写标签，按收藏热度搜索；时间范围和页数可省略。"),
        _button("赞助作者信息", "/pixiv赞助作者", syntax="/pixiv赞助作者 <创作者ID或主页链接> [数量]",
                example="/pixiv赞助作者 <创作者ID>", description="填写创作者ID或其主页链接。"),
        _button("赞助帖子详情", "/pixiv赞助帖子", syntax="/pixiv赞助帖子 <帖子ID或链接>",
                example="/pixiv赞助帖子 <帖子ID>", description="填写帖子ID或完整帖子链接。"),
        _button("赞助作者推荐", "/pixiv赞助推荐 5", enter=True),
        _button("搜索赞助作者", "/pixiv赞助搜索", syntax="/pixiv赞助搜索 <关键词> [数量]",
                example="/pixiv赞助搜索 <创作者名>", description="填写创作者名称或关键词。"),
        _button("赞助内容下载", "/pixiv赞助下载", syntax="/pixiv赞助下载 <创作者ID或主页链接> [选项]",
                example="/pixiv赞助下载 help", description="先查看现有下载参数，填写目标后手动提交。"),
        _button("下载进度", "/pixiv下载进度", enter=True),
        _button("停止下载", "/pixiv停止下载", admin_only=True,
                syntax="/pixiv停止下载", example="/pixiv停止下载",
                description="这会停止当前共享下载任务；确认后手动发送。"),
        _button("已下载内容", "/pixiv已下载", syntax="/pixiv已下载 <目录> [选项]",
                example="/pixiv已下载 help", description="查看原插件的目录、单帖发送与打包用法。"),
    ]),
    "JM": ("JM 功能", "帮助、检索、目录、排行和下载；访问权限沿用原插件。", [
        _button("JM帮助", "/jm帮助", enter=True),
        _button("搜索", "/jm搜索", syntax="/jm搜索 <关键词> [页码]",
                example="/jm搜索 <关键词> 1", description="填写搜索关键词；页码默认第1页。"),
        _button("月排行", "/jm月排行 1", enter=True),
        _button("总排行", "/jm总排行 1", enter=True),
        _button("作品详情", "/jm详情", syntax="/jm详情 <作品ID>",
                example="/jm详情 <作品ID>", description="填写从搜索结果获得的作品ID。"),
        _button("章节目录", "/jm章节", syntax="/jm章节 <作品ID>",
                example="/jm章节 <作品ID>", description="先查看目录，再按目录序号选择章节。"),
        _button("下载", "/jm下载", syntax="/jm下载 <作品ID> [章节序号或范围]",
                example="/jm下载 <作品ID> 1-3,7",
                description="章节可省略，也可填写单章、连续范围或逗号分隔的序号。"),
        _button("清理缓存", "/jm清理", admin_only=True,
                syntax="/jm清理 [天数]", example="/jm清理 7",
                description="填写天数只清理此前的缓存；不填会清空全部缓存，请确认后手动发送。"),
    ]),
    "Pica": ("Pica 功能", "帮助、账号、检索、目录、排行和下载；访问权限沿用原插件。", [
        _button("Pica帮助", "/pica帮助", enter=True),
        _button("搜索", "/pica搜索", syntax="/pica搜索 <关键词> [页码]",
                example="/pica搜索 <关键词> 1", description="填写搜索关键词；页码默认第1页。"),
        _button("作品详情", "/pica详情", syntax="/pica详情 <作品ID>",
                example="/pica详情 <作品ID>", description="填写从搜索结果获得的作品ID。"),
        _button("章节目录", "/pica章节", syntax="/pica章节 <作品ID>",
                example="/pica章节 <作品ID>", description="先查看章节列表，再选择章节序号。"),
        _button("下载", "/pica下载", syntax="/pica下载 <作品ID> [章节序号或范围]",
                example="/pica下载 <作品ID> 1-3,7",
                description="章节可省略，也可填写单章、连续范围或逗号分隔的序号。"),
        _button("每日排行", "/pica排行 H24", enter=True),
        _button("分区浏览", "/pica分类", syntax="/pica分类 <分区> [页码]",
                example="/pica分类 <分区名称> 1", description="先查看分区列表，再填写完整分区名。"),
        _button("分区列表", "/pica分区", enter=True),
        _button("收藏操作", "/pica收藏", syntax="/pica收藏 <作品ID>",
                example="/pica收藏 <作品ID>", description="填写作品ID；再次操作同一作品会取消收藏。"),
        _button("我的收藏", "/pica我的收藏 1", enter=True),
        _button("签到", "/pica签到", enter=True),
        _button("账号登录", "/pica登录", private_only=True,
                syntax="/pica登录 [邮箱] [密码]", example="/pica登录 <自己的邮箱> <自己的密码>",
                description="仅在私聊填写凭据；不填账号密码会绑定后台默认账号。此按钮只显示用法。"),
        _button("账号状态", "/pica状态", enter=True),
        _button("退出账号", "/pica退出", syntax="/pica退出", example="/pica退出",
                description="这会解绑当前用户的账号；确认后手动发送。"),
        _button("清理缓存", "/pica清理", admin_only=True,
                syntax="/pica清理 [天数]", example="/pica清理 7",
                description="填写天数只清理此前的缓存；不填会清空全部缓存和打包文件，请确认后手动发送。"),
    ]),
}

RESOURCE_ALIASES = {name.casefold(): name for name in RESOURCE_FAMILIES}
_HELP_ALIASES = {
    "pixiv帮助": "Pixiv", "pixiv_help": "Pixiv",
    "jm帮助": "JM", "jmhelp": "JM", "jmhelp0": "JM", "jm": "JM",
    "pica帮助": "Pica", "picahelp": "Pica", "pica": "Pica",
}
_HELP_MODES = frozenset({"图片", "菜单", "image", "文字", "完整", "text"})


def resource_buttons(family, *, is_admin=False, is_private=False):
    """Return independent buttons; flags only limit menu exposure, not handlers."""
    name = RESOURCE_ALIASES.get(str(family).casefold())
    entry = RESOURCE_FAMILIES.get(name)
    if entry is None:
        return []
    return [dict(item) for item in entry[2]
            if (is_admin or not item.get("admin_only"))
            and (is_private or not item.get("private_only"))]


def resource_help_family(command):
    """Recognize full-help invocations without treating search replies as help."""
    if not isinstance(command, str):
        return None
    parts = command.strip().lstrip("/#").casefold().split()
    if not parts or len(parts) > 2 or (len(parts) == 2 and parts[1] not in _HELP_MODES):
        return None
    return _HELP_ALIASES.get(parts[0])


def resource_usage(command):
    """Return inert syntax/example/explanation for parameter and state helpers."""
    if not isinstance(command, str) or not command.strip():
        return None
    return _USAGE.get(command.strip().split()[0].casefold())
