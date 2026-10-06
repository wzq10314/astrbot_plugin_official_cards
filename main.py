import asyncio

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image
from astrbot.api.star import Context, Star, StarTools, register
from astrbot.core import file_token_service

from .menus import menu_page, event_is_private, FAMILIES, FAMILY_ALIASES
from .menu_image import render_menu_image
from .support import is_qq_official, set_card_hint
from .transport import CardTransport, ImagePublisher
from .image_http import ImageHeadRoute
from .keyboard_pages import HOME_BUTTON, PAGE_HINT_KEY
from .interactions import InteractionBridge
from .menu_routes import original_help_command, queue_original_help


@register("astrbot_plugin_official_cards", "wzq10314", "QQ 官方图文卡片与功能菜单", "1.0.14")
class OfficialCardsPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.transport = None
        self.image_head_route = None
        self.interaction_bridge = None

    async def initialize(self):
        if not self.config.get("enabled", True):
            return
        publisher = ImagePublisher(
            file_token_service,
            StarTools.get_data_dir("astrbot_plugin_official_cards") / "published_images",
            self.config.get("public_base_url", ""),
            ttl=self.config.get("image_ttl_seconds", 21600),
            max_tokens=self.config.get("max_image_tokens", 256),
        )
        self.transport = CardTransport(publisher, keyboard=self.config.get("enable_keyboard", True))
        self.interaction_bridge = InteractionBridge(self.context, self.transport)
        await self.interaction_bridge.initialize()
        self.transport.callbacks_enabled = True
        self.transport.install()
        from astrbot.dashboard import server
        dashboard = getattr(getattr(server, 'APP', None), '_dashboard_server', None)
        app = getattr(dashboard, 'asgi_app', None)
        if app is not None:
            self.image_head_route = ImageHeadRoute(app, publisher)
            self.image_head_route.install()
        try:
            await self.interaction_bridge.reconnect()
        except Exception:
            await self.terminate()
            raise
        logger.info("[OfficialCards] QQ official card transport enabled.")

    @filter.command("功能菜单", alias={"官方菜单"})
    async def show_menu(self, event: AstrMessageEvent, category: str = ""):
        category = FAMILY_ALIASES.get(category.strip().lower(), category.strip())
        if category not in FAMILIES:
            category = ""
        original = original_help_command(category)
        if original:
            if queue_original_help(self.context, event, category):
                event.stop_event()
                return
            set_card_hint(event, buttons=[{'label': '打开原帮助', 'command': original, 'enter': True}])
            yield event.plain_result(f'请发送 {original} 打开原来的帮助图。').use_t2i(False).use_markdown(True)
            return
        text, buttons = menu_page(category, is_admin=event.is_admin(), is_private=event_is_private(event))
        if is_qq_official(event):
            set_card_hint(event, buttons=buttons)
        if not category.strip():
            try:
                summaries = {
                    '资讯': '每日新闻 · 热门话题', '签到': '每日签到 · 成就记录',
                    '小猪': '今日小猪 · 趣味互动', '光遇': '每日攻略 · 角色查询',
                    '小镇': '资源位置 · 每日兑换码', '王者': '战绩查询 · 营地观战',
                    '音乐': '点歌听歌 · 视频解析', 'Steam': '游戏状态 · 价格查询',
                    '表情收藏': '收藏图片 · 查找表情', '记忆': '会话记忆 · 管理员功能',
                    '学习': '学习状态 · 管理员功能', '扩展': '运行状态 · 扩展功能',
                    '群管': '成员查询 · 禁言 · 入群审核', '贴表情': '消息表情回应',
                    'Pixiv': '插画 · 画师 · 小说', 'JM': '搜索 · 章节 · 阅读',
                    'Pica': '搜索 · 收藏 · 阅读',
                }
                categories = [(name, title, summaries.get(name, description), name != '贴表情')
                              for name, (title, description, _) in FAMILIES.items()]
                path = await asyncio.to_thread(render_menu_image, categories,
                    cache_dir=StarTools.get_data_dir('astrbot_plugin_official_cards') / 'menu_images')
                yield event.chain_result([Image.fromFileSystem(str(path))]).use_t2i(False).use_markdown(True)
                return
            except (OSError, ValueError, RuntimeError):
                logger.info('[OfficialCards] Menu image unavailable; using text navigation.')
        yield event.plain_result(text).use_t2i(False).use_markdown(True)

    @filter.command("菜单翻页")
    async def show_keyboard_page(self, event: AstrMessageEvent, token: str = "", page: int = 1):
        if not is_qq_official(event):
            return
        selected = self.transport.keyboard_pages.get_page(token, page, event) if self.transport else None
        if selected is None or (selected.image_tokens
                                and not self.transport.publisher.has_tokens(selected.image_tokens)):
            set_card_hint(event, buttons=[dict(HOME_BUTTON)])
            yield event.plain_result("菜单已过期或不属于当前用户和会话，请重新发送帮助命令或打开功能菜单。").use_t2i(False).use_markdown(True)
            return
        event.set_extra(PAGE_HINT_KEY, (token, page))
        set_card_hint(event, buttons=selected.buttons)
        yield event.plain_result(selected.text).use_t2i(False).use_markdown(True)

    async def terminate(self):
        if self.interaction_bridge is not None:
            self.interaction_bridge.close()
            self.interaction_bridge = None
        if self.image_head_route is not None:
            self.image_head_route.close()
            self.image_head_route = None
        if self.transport is not None:
            self.transport.close()
            self.transport = None

    @filter.command("按钮用法")
    async def show_button_usage(self, event: AstrMessageEvent, token: str = ""):
        if not is_qq_official(event):
            return
        text = self.transport.button_prompts.get(token, event) if self.transport else None
        if text is None:
            text = "这个按钮已过期或不属于当前会话，请重新发送帮助命令，再点一次吧～"
        set_card_hint(event, buttons=[dict(HOME_BUTTON)])
        yield event.plain_result(text).use_t2i(False).use_markdown(True)
