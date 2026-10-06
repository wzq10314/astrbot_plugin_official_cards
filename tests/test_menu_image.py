"""Image delivery, layout bounds and cache contracts without AstrBot imports."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFont


MODULE_PATH = Path(__file__).resolve().parents[1] / "menu_image.py"
SPEC = importlib.util.spec_from_file_location("official_cards_menu_image", MODULE_PATH)
menu_image = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(menu_image)
NAMES = ["资讯", "签到", "小猪", "光遇", "小镇", "王者", "音乐", "Steam", "表情收藏",
         "记忆", "学习", "扩展", "群管", "贴表情", "Pixiv", "JM", "Pica"]
CATEGORIES = [(name, name + "功能", "发现你喜欢的内容，点击下方按钮查看。", name not in ("群管", "贴表情"))
              for name in NAMES]


class MenuImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.font_path = menu_image._choose_font("".join(NAMES))
        except RuntimeError as exc:
            raise unittest.SkipTest(str(exc))

    def test_complete_menu_dimensions_webp_and_cache_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            rendered_text = []
            original_text = ImageDraw.ImageDraw.text
            def capture_text(draw, xy, text, *args, **kwargs):
                rendered_text.append(text)
                return original_text(draw, xy, text, *args, **kwargs)
            with patch.object(ImageDraw.ImageDraw, "text", capture_text):
                first = menu_image.render_menu_image(CATEGORIES, cache_dir=directory)
            with Image.open(first) as picture:
                self.assertEqual(picture.format, "WEBP")
                self.assertEqual(Image.MIME[picture.format], "image/webp")
                self.assertEqual(picture.size, (1080, 1350))
                picture.load()
            for name in NAMES:
                self.assertIn(name, rendered_text)
            self.assertEqual(rendered_text.count("暂不可用"), 2)
            self.assertIn("点击下方按钮，打开对应功能", rendered_text)
            first_time = first.stat().st_mtime_ns
            with patch.object(menu_image, "_render", side_effect=AssertionError("cache hit rendered again")):
                second = menu_image.render_menu_image(CATEGORIES, cache_dir=directory)
            self.assertEqual(first, second)
            self.assertEqual(first.stat().st_mtime_ns, first_time)
            altered = [*CATEGORIES]
            altered[0] = ("资讯", "最新资讯", "每日新鲜内容。", True)
            third = menu_image.render_menu_image(altered, cache_dir=directory)
            self.assertNotEqual(first, third)
            self.assertEqual(len(list(Path(directory).glob("menu-*.webp"))), 2)
            self.assertEqual(list(Path(directory).glob(".menu-*")), [])

    def test_long_descriptions_wrap_and_clip_within_two_lines(self):
        font = ImageFont.truetype(str(self.font_path), 42)
        draw = ImageDraw.Draw(Image.new("RGB", (20, 20)))
        for value in ("查看最新资讯与排行" * 30, "https://example.test/" + "x" * 250):
            lines = menu_image._fit_lines(draw, value, font, 548, 2)
            self.assertEqual(len(lines), 2)
            self.assertTrue(lines[-1].endswith("…"))
            self.assertTrue(all(draw.textlength(line, font=font) <= 548 for line in lines))

    def test_pruning_only_removes_owned_cache_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            unrelated = root / "menu-important.webp"
            unrelated.write_bytes(b"user file")
            for number in range(10):
                (root / f"menu-{number:064x}.webp").write_bytes(b"old generated image")
            current = menu_image.render_menu_image(CATEGORIES, cache_dir=root)
            owned = [file for file in root.iterdir() if menu_image._CACHE_NAME.fullmatch(file.name)]
            self.assertEqual(len(owned), 8)
            self.assertTrue(current.exists())
            self.assertEqual(unrelated.read_bytes(), b"user file")

    def test_missing_chinese_font_raises_for_text_fallback(self):
        with patch.object(menu_image, "_font_candidates", return_value=[]):
            with self.assertRaisesRegex(RuntimeError, "Chinese font"):
                menu_image.render_menu_image(CATEGORIES, cache_dir="unused-menu-cache")

    def test_empty_categories_are_rejected_before_writing(self):
        with self.assertRaises(ValueError):
            menu_image.render_menu_image([], cache_dir="unused-menu-cache")

    def test_command_page_contains_exactly_matching_buttons(self):
        buttons = [{"label": f"光遇命令{index:02d}", "command": f"/光遇命令{index:02d} <角色>"}
                   for index in range(69)]
        seen = []
        original_text = ImageDraw.ImageDraw.text
        def capture_text(draw, xy, value, *args, **kwargs):
            seen.append(value)
            return original_text(draw, xy, value, *args, **kwargs)
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(ImageDraw.ImageDraw, "text", capture_text):
                path = menu_image.render_command_menu("光遇菜单", "查看每日攻略与角色信息", buttons,
                                                       cache_dir=directory, page=2)
            with Image.open(path) as picture:
                self.assertEqual(picture.format, "WEBP")
                self.assertEqual(picture.width, 1080)
                picture.load()
            self.assertIn("第2/9页", seen)
            for index in range(69):
                self.assertEqual(f"光遇命令{index:02d}" in seen, 8 <= index < 16)
                self.assertEqual(f"/光遇命令{index:02d} <角色>" in seen, 8 <= index < 16)
            with patch.object(menu_image, "_render_commands", side_effect=AssertionError("cache rendered")):
                self.assertEqual(path, menu_image.render_command_menu("光遇菜单", "查看每日攻略与角色信息",
                                 buttons, cache_dir=directory, page=2))
            other = menu_image.render_command_menu("光遇菜单", "查看每日攻略与角色信息", buttons,
                                                   cache_dir=directory, page=3)
            self.assertNotEqual(path, other)

    def test_command_menu_accepts_ten_buttons_and_rejects_outside_pages(self):
        buttons = [{"label": f"功能{index}", "command": f"/功能{index}"} for index in range(10)]
        with tempfile.TemporaryDirectory() as directory:
            path = menu_image.render_command_menu("功能帮助", "", buttons, cache_dir=directory, page_size=10)
            self.assertTrue(path.is_file())
            for page, page_size in ((0, 10), (2, 10), (1, 11), (1, 0)):
                with self.assertRaises(ValueError):
                    menu_image.render_command_menu("功能帮助", "", buttons, cache_dir=directory,
                                                   page=page, page_size=page_size)

    def test_command_and_plain_text_wrapping_never_discards_content(self):
        command = "/查询 " + "长参数"*100 + " https://example.test/" + "x"*200
        _, cards, _, _ = menu_image._command_layout("功能菜单", "",
                         [{"label": "完整命令", "command": command}], self.font_path)
        self.assertEqual("".join(cards[0][1]), command)
        font = ImageFont.truetype(str(self.font_path), 54)
        draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        original = "第一行\n\n最后一行\n"
        self.assertEqual(menu_image._wrap_all(draw, original, font, 1860), original.split("\n"))
        lines = menu_image._wrap_all(draw, command, font, 1860)
        self.assertEqual("".join(lines), command)
        self.assertTrue(all(draw.textlength(line, font=font) <= 1860 for line in lines))

    def test_all_original_help_lines_survive_multiple_images(self):
        source_lines = [f"/光遇功能{index:02d} <参数>：完整使用说明" for index in range(69)]
        source_lines.insert(4, "")
        source_lines.extend(["", "最后一条说明", ""])
        body = "\n".join(source_lines)
        seen_lines = []
        original_render = menu_image._render_help_page
        def capture_page(title, lines, font_path, page, pages):
            seen_lines.extend(lines)
            return original_render(title, lines, font_path, page, pages)
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(menu_image, "_render_help_page", capture_page):
                paths = menu_image.render_text_menu("光遇完整帮助", body, cache_dir=directory)
            self.assertIsInstance(paths, tuple)
            self.assertGreater(len(paths), 1)
            self.assertEqual(seen_lines, source_lines)
            for path in paths:
                with Image.open(path) as picture:
                    self.assertEqual(picture.width, 1080)
                    self.assertLessEqual(picture.height, 1800)
                    self.assertEqual(picture.format, "WEBP")
                    picture.load()
            with patch.object(menu_image, "_render_help_page", side_effect=AssertionError("cache rendered")):
                self.assertEqual(paths, menu_image.render_text_menu("光遇完整帮助", body, cache_dir=directory))
            changed = menu_image.render_text_menu("光遇完整帮助", body+"新增说明", cache_dir=directory)
            self.assertNotEqual(paths, changed)
            self.assertTrue(all(path.is_file() for path in paths))

    def test_help_cache_pruning_preserves_every_page_of_current_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for revision in range(10):
                for page in range(2):
                    (root / f"help-{revision:064x}-{page+1:03d}.webp").write_bytes(b"old image")
            unrelated = root / "help-not-generated.webp"
            unrelated.write_bytes(b"keep")
            current = f"{9:064x}"
            menu_image._prune_page_cache(root, "help", current)
            generated = [path for path in root.iterdir() if menu_image._PAGE_CACHE_NAME.fullmatch(path.name)]
            self.assertEqual(len(generated), 16)
            self.assertTrue((root / f"help-{current}-001.webp").exists())
            self.assertTrue((root / f"help-{current}-002.webp").exists())
            self.assertEqual(unrelated.read_bytes(), b"keep")


if __name__ == "__main__":
    unittest.main()
