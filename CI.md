# 离线测试

本仓库的单独测试使用模拟 AstrBot 与 QQ API，以及临时图片，不需要真实机器人凭据，也不会发送或撤回实际 QQ 消息。

检出目录命名为 `astrbot_plugin_official_cards`，在父目录执行：

```text
python -m pip install -r astrbot_plugin_official_cards/requirements-dev.txt
python -B astrbot_plugin_official_cards/tests/run_unit.py
```

独立测试覆盖发送回执、图片令牌、按钮点击权限、分页和所有按钮的来源卡片撤回。它们不证明实际 QQ 账号权限或公网 HTTPS 可达性。中文菜单渲染还需要宿主中文字体。

以下集成测试另需对应源码，未纳入单仓库运行器：`test_cross_review`（AstrBot QQ 适配器）、`test_gok_help_actions`（王者插件）、`test_resource_menus`（QQ 整合插件）、`test_sky_menu`（光遇插件）、`test_text_help_images`（光遇、QQ 整合、长期记忆等插件）。完整开发环境可按各文件中的路径准备来源后运行 unittest discovery；不能在干净单仓库声称这些测试已通过。

发布只包含源码、测试和文档。账号配置、令牌索引、临时图片、下载、缓存与日志不得进入仓库。GitHub Actions 使用只读 contents 权限，不需要任何机器人 secrets。
