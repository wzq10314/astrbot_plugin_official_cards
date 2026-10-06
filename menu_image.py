"""Local Pillow artwork for the root menu; no network or AstrBot imports.

Call ``render_menu_image([(name, title, description, available), ...],
cache_dir=...)`` in a worker thread. A missing Chinese font raises RuntimeError
so the caller can retain its ordinary text menu.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Sequence

from PIL import Image, ImageDraw, ImageFilter, ImageFont, __version__ as PILLOW_VERSION


Category = tuple[str, str, str, bool]
DESIGN_VERSION = "pastel-menu-v1"
WIDTH = 1080
_SCALE = 2
_LOCK = threading.Lock()
_CACHE_NAME = re.compile(r"menu-[0-9a-f]{64}\.webp\Z")
_PALETTE = (
    ("#e8efff", "#607cd0"), ("#e5f3ee", "#4b967e"),
    ("#fbe9ef", "#c77d94"), ("#ede9fa", "#8f7bc1"),
    ("#fbefdf", "#bc9661"), ("#e3f2f6", "#5596a9"),
)


def _font_candidates() -> list[Path]:
    """Prefer CJK sans fonts shipped by common Linux and Windows hosts."""
    paths = []
    override = os.environ.get("OFFICIAL_CARDS_FONT_PATH")
    if override:
        paths.append(Path(override).expanduser())
    windows = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    paths.extend([
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf"),
        windows / "msyh.ttc", windows / "simhei.ttf", windows / "simsun.ttc",
        Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
        Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
        Path("/System/Library/Fonts/PingFang.ttc"),
    ])
    for directory in (Path("/usr/local/share/fonts"), Path.home() / ".local/share/fonts",
                      Path("/usr/share/fonts/opentype/noto"),
                      Path("/usr/share/fonts/truetype/noto")):
        if directory.is_dir():
            for pattern in ("*NotoSans*CJK*", "*NotoSans*SC*", "*SourceHanSans*", "*wqy*"):
                paths.extend(sorted(directory.glob(pattern)))
    return list(dict.fromkeys(paths))


def _choose_font(text: str) -> Path:
    required = set("功能菜单点击下方按钮打开对应暂不可用" + text)
    # An unassigned Unicode point reliably resolves to the font's missing glyph.
    # Check every requested CJK character, not just the font's filename.
    cjk = [char for char in required if "\u2e80" <= char <= "\u9fff"]
    for path in _font_candidates():
        if not path.is_file():
            continue
        try:
            font = ImageFont.truetype(str(path), 24)
            missing = font.getmask("\u0378")
            missing_key = (missing.size, bytes(missing))
            if all((mask.size, bytes(mask)) != missing_key and mask.getbbox()
                   for char in cjk for mask in (font.getmask(char),)):
                return path
        except (OSError, ValueError):
            continue
    raise RuntimeError("No usable Chinese font found; install Noto Sans CJK or set OFFICIAL_CARDS_FONT_PATH")


def _fit_lines(draw, value: str, font, width: int, count: int = 2) -> list[str]:
    """Character wrapping works for CJK and clips even an unbroken long URL."""
    value = " ".join(str(value).split())
    lines: list[str] = []
    current = ""
    for char in value:
        if current and draw.textlength(current + char, font=font) > width:
            lines.append(current)
            current = char
            if len(lines) == count:
                last = lines[-1]
                while last and draw.textlength(last + "…", font=font) > width:
                    last = last[:-1]
                lines[-1] = last + "…"
                return lines
        else:
            current += char
    if current:
        lines.append(current)
    return lines[:count]


def _draw_icon(draw, name: str, box, color: str) -> None:
    """Small vector-style line icons avoid emoji/font rendering dependencies."""
    x, y, size = box
    def point(a, b):
        return (round(x + a * size), round(y + b * size))
    def line(points, width=2.3):
        draw.line([point(*p) for p in points], fill=color, width=round(width * _SCALE), joint="curve")
    def ellipse(a, b, c, d, fill=None):
        draw.ellipse((*point(a, b), *point(c, d)), outline=color, fill=fill, width=4)
    def rectangle(a, b, c, d, radius=.06):
        draw.rounded_rectangle((*point(a, b), *point(c, d)), radius=round(radius * size), outline=color, width=4)
    if name == "资讯":
        rectangle(.12, .16, .87, .85)
        line([(.25, .33), (.73, .33)])
        line([(.25, .49), (.52, .49)])
        line([(.25, .65), (.69, .65)])
    elif name == "签到":
        rectangle(.13, .21, .87, .86)
        line([(.29, .11), (.29, .31)])
        line([(.70, .11), (.70, .31)])
        line([(.30, .57), (.45, .71), (.72, .43)])
    elif name == "小猪":
        ellipse(.13, .26, .87, .88)
        line([(.20, .39), (.19, .15), (.39, .29)])
        line([(.62, .29), (.81, .15), (.80, .39)])
        ellipse(.34, .56, .66, .77)
        ellipse(.30, .43, .32, .46, color)
        ellipse(.68, .43, .70, .46, color)
    elif name == "光遇":
        line([(.50, .10), (.62, .37), (.91, .48), (.62, .59), (.50, .89), (.38, .59), (.09, .48), (.38, .37), (.50, .10)])
    elif name == "小镇":
        line([(.11, .45), (.5, .12), (.89, .45)])
        line([(.23, .37), (.23, .86), (.77, .86), (.77, .37)])
        rectangle(.43, .57, .60, .86, 0)
    elif name == "王者":
        line([(.14, .29), (.29, .78), (.74, .78), (.87, .29), (.63, .48), (.50, .16), (.38, .48), (.14, .29)])
    elif name == "音乐":
        line([(.40, .72), (.40, .23), (.80, .13), (.80, .63)])
        ellipse(.15, .62, .40, .84)
        ellipse(.55, .53, .80, .75)
    elif name == "Steam":
        ellipse(.53, .14, .90, .51)
        ellipse(.10, .59, .39, .86)
        line([(.27, .60), (.56, .32)])
        line([(.37, .75), (.80, .48)])
    elif name in ("表情收藏", "贴表情"):
        ellipse(.13, .13, .87, .87)
        ellipse(.32, .34, .35, .40, color)
        ellipse(.65, .34, .68, .40, color)
        line([(.31, .59), (.43, .68), (.58, .68), (.71, .57)])
    elif name == "记忆":
        rectangle(.20, .17, .81, .87)
        line([(.10, .32), (.30, .32)])
        line([(.10, .53), (.30, .53)])
        line([(.10, .74), (.30, .74)])
        line([(.43, .35), (.66, .35)])
        line([(.43, .51), (.66, .51)])
    elif name in ("学习", "JM", "Pica"):
        line([(.50, .28), (.16, .16), (.16, .76), (.50, .88), (.84, .76), (.84, .16), (.50, .28), (.50, .88)])
        line([(.27, .38), (.39, .42)])
        line([(.61, .42), (.74, .38)])
    elif name == "群管":
        ellipse(.35, .11, .65, .41)
        ellipse(.08, .26, .31, .49)
        ellipse(.69, .26, .92, .49)
        line([(.13, .79), (.16, .60), (.32, .56)])
        line([(.68, .56), (.85, .61), (.89, .79)])
        draw.arc((*point(.27, .48), *point(.75, 1.08)), 180, 360, fill=color, width=4)
    elif name == "Pixiv":
        rectangle(.12, .15, .87, .87)
        ellipse(.60, .27, .75, .42)
        line([(.16, .75), (.38, .47), (.53, .67), (.63, .57), (.84, .79)])
    else:
        for a, b in ((.16, .16), (.58, .16), (.16, .58), (.58, .58)):
            rectangle(a, b, a + .26, b + .26)


def _render(categories: Sequence[Category], font_path: Path) -> Image.Image:
    rows = math.ceil(len(categories) / 3)
    height = max(650, 276 + rows * 168 + 66)
    s = _SCALE
    image = Image.new("RGB", (WIDTH * s, height * s))
    draw = ImageDraw.Draw(image)
    for y in range(height * s):
        ratio = y / (height * s - 1)
        color = tuple(round(a + (b - a) * ratio) for a, b in zip((240, 245, 255), (247, 245, 251)))
        draw.line((0, y, WIDTH * s, y), fill=color)
    for bounds, color, opacity in (
        ((680, -190, 1300, 390), (194, 219, 255), 95),
        ((-220, 340, 270, 1030), (231, 206, 245), 58),
    ):
        mask = Image.new("L", image.size)
        ImageDraw.Draw(mask).ellipse(tuple(value*s for value in bounds), fill=opacity)
        # Blur only the alpha mask, avoiding dark fringes from transparent RGB.
        image = Image.composite(Image.new("RGB", image.size, color), image,
                                mask.filter(ImageFilter.GaussianBlur(65*s)))
    draw = ImageDraw.Draw(image)
    def font(size):
        return ImageFont.truetype(str(font_path), size * s)
    def text(x, y, value, size, fill):
        draw.text((x * s, y * s), value, font=font(size), fill=fill, anchor="lt")
    navy = "#243653"
    text(50, 43, "发现一点新乐趣", 22, "#7889a4")
    text(47, 89, "功能菜单", 61, navy)
    text(51, 179, "点击下方按钮，打开对应功能", 27, "#677a97")
    # Decorative stacked cards echo the menu, without competing with its title.
    for index, (xx, yy, fill) in enumerate(((844, 55, "#dbe6ff"), (867, 82, "#e6def8"), (889, 111, "#ffffff"))):
        draw.rounded_rectangle((xx*s, yy*s, (xx+105)*s, (yy+77)*s), radius=18*s, fill=fill)
        if index == 2:
            for dx in (23, 51):
                for dy in (20, 44):
                    draw.rounded_rectangle(((xx+dx)*s, (yy+dy)*s, (xx+dx+14)*s, (yy+dy+12)*s), radius=4*s, fill="#a0b4dc")
    margin, gap, card_width, card_height = 48, 18, 316, 150
    desc_font = font(21)
    for index, (name, title, description, available) in enumerate(categories):
        x = margin + (index % 3) * (card_width + gap)
        y = 262 + (index // 3) * 168
        bg, accent = _PALETTE[index % len(_PALETTE)]
        if not available:
            bg, accent = "#edf0f4", "#929cae"
        draw.rounded_rectangle((x*s, (y+4)*s, (x+card_width)*s, (y+card_height+4)*s), radius=24*s, fill="#e5eaf3")
        draw.rounded_rectangle((x*s, y*s, (x+card_width)*s, (y+card_height)*s), radius=24*s, fill="#ffffff" if available else "#f8f9fc", outline="#edf0f6", width=s)
        draw.rounded_rectangle(((x+20)*s, (y+20)*s, (x+70)*s, (y+70)*s), radius=15*s, fill=bg)
        _draw_icon(draw, name, ((x+27)*s, (y+27)*s, 36*s), accent)
        label_font = font(28)
        while draw.textlength(name, font=label_font) > 214*s and label_font.size > 18*s:
            label_font = ImageFont.truetype(str(font_path), label_font.size - 2*s)
        draw.text(((x+83)*s, (y+28)*s), _fit_lines(draw, name, label_font, 214*s, 1)[0], font=label_font, fill=navy if available else "#7c879b", anchor="lt")
        if available:
            lines = _fit_lines(draw, description or title, desc_font, (card_width-42)*s)
            for line_index, value in enumerate(lines):
                draw.text(((x+22)*s, (y+86+28*line_index)*s), value, font=desc_font, fill="#76849a", anchor="lt")
        else:
            text(x+23, y+92, "暂不可用", 22, "#929cad")
    footer_y = 262 + rows * 168 + 16
    text(50, footer_y, f"{len(categories):02d} 个分类 · 总有你想探索的", 21, "#8997ae")
    return image.resize((WIDTH, height), Image.Resampling.LANCZOS)


def _prune_cache(cache_dir: Path, current: Path) -> None:
    # Match only files created by this renderer; never follow or remove symlinks.
    entries = [path for path in cache_dir.iterdir()
               if _CACHE_NAME.fullmatch(path.name) and not path.is_symlink() and path.is_file()]
    entries.sort(key=lambda path: (path == current, path.stat().st_mtime_ns), reverse=True)
    for path in entries[8:]:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def render_menu_image(categories: Sequence[Category], *, cache_dir: str | Path) -> Path:
    """Return a cached 1080 px WebP; preserve categories' input order."""
    values = [tuple(item) for item in categories]
    if not values or any(len(item) != 4 or not all(isinstance(value, str) for value in item[:3])
                         or not isinstance(item[3], bool) or not item[0].strip() for item in values):
        raise ValueError("categories must contain (name, title, description, available) tuples")
    font_path = _choose_font("".join("".join(item[:3]) for item in values))
    stat = font_path.stat()
    identity = [DESIGN_VERSION, PILLOW_VERSION, values, str(font_path), stat.st_size, stat.st_mtime_ns]
    digest = hashlib.sha256(json.dumps(identity, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    directory = Path(cache_dir)
    result = directory / f"menu-{digest}.webp"
    with _LOCK:
        directory.mkdir(parents=True, exist_ok=True)
        if result.is_file() and result.stat().st_size > 16:
            return result
        picture = _render(values, font_path)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(prefix=".menu-", suffix=".webp", dir=directory, delete=False) as handle:
                temporary = Path(handle.name)
                picture.save(handle, format="WEBP", quality=93, method=6)
            os.replace(temporary, result)
            temporary = None
            _prune_cache(directory, result)
        finally:
            picture.close()
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return result


_DETAIL_VERSION = "pastel-detail-v1"
_PAGE_CACHE_NAME = re.compile(r"(commands|help)-([0-9a-f]{64})-([0-9]+)\.webp\Z")


def _wrap_all(draw, value: str, font, width: int) -> list[str]:
    """Wrap without truncation, preserving source line breaks and blank lines."""
    output = []
    normalized = value.replace("\r\n", "\n").replace("\r", "\n").expandtabs(4)
    for source_line in normalized.split("\n"):
        current = ""
        for char in source_line:
            if current and draw.textlength(current + char, font=font) > width:
                output.append(current)
                current = char
            else:
                current += char
        output.append(current)
    return output


def _detail_identity(content, font_path: Path) -> str:
    stat = font_path.stat()
    identity = [_DETAIL_VERSION, PILLOW_VERSION, content, str(font_path), stat.st_size, stat.st_mtime_ns]
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _write_picture(picture: Image.Image, result: Path) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".menu-", suffix=".webp", dir=result.parent, delete=False) as handle:
            temporary = Path(handle.name)
            picture.save(handle, format="WEBP", quality=93, method=6)
        os.replace(temporary, result)
        temporary = None
    finally:
        picture.close()
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _prune_page_cache(directory: Path, kind: str, current_digest: str) -> None:
    """Keep eight complete menu revisions, so pages in one result stay valid."""
    groups: dict[str, list[Path]] = {}
    modified: dict[str, int] = {}
    for path in directory.iterdir():
        match = _PAGE_CACHE_NAME.fullmatch(path.name)
        if match and match[1] == kind and not path.is_symlink() and path.is_file():
            digest = match[2]
            groups.setdefault(digest, []).append(path)
            modified[digest] = max(modified.get(digest, 0), path.stat().st_mtime_ns)
    ordered = sorted(groups, key=lambda digest: (digest == current_digest, modified[digest]), reverse=True)
    for digest in ordered[8:]:
        for path in groups[digest]:
            path.unlink(missing_ok=True)


def _detail_canvas(height: int) -> Image.Image:
    s = _SCALE
    picture = Image.new("RGB", (WIDTH*s, height*s))
    draw = ImageDraw.Draw(picture)
    for y in range(height*s):
        ratio = y / max(1, height*s - 1)
        color = tuple(round(a+(b-a)*ratio) for a, b in zip((239, 245, 255), (248, 245, 252)))
        draw.line((0, y, WIDTH*s, y), fill=color)
    return picture


def _detail_header(draw, title: str, font_path: Path, page: int, pages: int) -> int:
    s = _SCALE
    small = ImageFont.truetype(str(font_path), 21*s)
    heading = ImageFont.truetype(str(font_path), 48*s)
    draw.text((48*s, 35*s), "功能指南", font=small, fill="#8493ab", anchor="lt")
    badge = f"第{page}/{pages}页"
    badge_width = max(130*s, math.ceil(draw.textlength(badge, font=small))+36*s)
    left = WIDTH*s - 48*s - badge_width
    draw.rounded_rectangle((left, 29*s, (WIDTH-48)*s, 72*s), radius=18*s, fill="#e4ebfb")
    draw.text((left+18*s, 40*s), badge, font=small, fill="#6c83b5", anchor="lt")
    title_lines = _wrap_all(draw, title or "功能帮助", heading, (WIDTH-96)*s)
    for index, line in enumerate(title_lines):
        draw.text((46*s, (90+index*62)*s), line, font=heading, fill="#263955", anchor="lt")
    return 102 + len(title_lines)*62


def _command_layout(title: str, description: str, selected: list[dict], font_path: Path):
    s = _SCALE
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    title_font = ImageFont.truetype(str(font_path), 48*s)
    heading_height = 102 + 62*len(_wrap_all(measure, title or "功能帮助", title_font, 984*s))
    desc_font = ImageFont.truetype(str(font_path), 23*s)
    desc_lines = _wrap_all(measure, description, desc_font, 972*s) if description else []
    top = heading_height + 32*len(desc_lines) + 26
    label_font = ImageFont.truetype(str(font_path), 29*s)
    command_font = ImageFont.truetype(str(font_path), 23*s)
    cards = []
    for button in selected:
        label_lines = _wrap_all(measure, button["label"], label_font, 364*s)
        command_lines = _wrap_all(measure, button["command"], command_font, 422*s)
        cards.append((label_lines, command_lines, max(155, 51+39*len(label_lines)+32*len(command_lines))))
    row_heights = [max(card[2] for card in cards[index:index+2]) for index in range(0, len(cards), 2)]
    return desc_lines, cards, row_heights, top


def _render_commands(title: str, description: str, selected: list[dict], font_path: Path,
                     page: int, pages: int, start_index: int) -> Image.Image:
    s = _SCALE
    desc_lines, cards, row_heights, top = _command_layout(title, description, selected, font_path)
    height = max(450, top + sum(row_heights) + 20*len(row_heights) + 81)
    picture = _detail_canvas(height)
    draw = ImageDraw.Draw(picture)
    y = _detail_header(draw, title, font_path, page, pages)
    desc_font = ImageFont.truetype(str(font_path), 23*s)
    label_font = ImageFont.truetype(str(font_path), 29*s)
    number_font = ImageFont.truetype(str(font_path), 19*s)
    for line in desc_lines:
        draw.text((50*s, y*s), line, font=desc_font, fill="#73839b", anchor="lt")
        y += 32
    row_y = top
    for row_index, row_height in enumerate(row_heights):
        for column in range(2):
            index = row_index*2+column
            if index >= len(cards):
                continue
            labels, commands, _ = cards[index]
            x = 48 + column*504
            bg, accent = _PALETTE[index % len(_PALETTE)]
            draw.rounded_rectangle((x*s, (row_y+4)*s, (x+480)*s, (row_y+row_height+4)*s), radius=23*s, fill="#e5eaf3")
            draw.rounded_rectangle((x*s, row_y*s, (x+480)*s, (row_y+row_height)*s), radius=23*s, fill="white")
            draw.rounded_rectangle(((x+24)*s, (row_y+24)*s, (x+70)*s, (row_y+66)*s), radius=13*s, fill=bg)
            number = f"{start_index+index+1:02d}"
            number_width = draw.textlength(number, font=number_font)
            draw.text(((x+47)*s-number_width/2, (row_y+35)*s), number, font=number_font, fill=accent, anchor="lt")
            for line_index, line in enumerate(labels):
                draw.text(((x+87)*s, (row_y+29+line_index*39)*s), line, font=label_font, fill="#263955", anchor="lt")
            command_y = row_y+36+39*len(labels)
            for line in commands:
                draw.text(((x+29)*s, command_y*s), line, font=desc_font, fill="#72819a", anchor="lt")
                command_y += 32
        row_y += row_height + 20
    if not cards:
        draw.text((51*s, top*s), "暂无可用命令", font=label_font, fill="#8290a6", anchor="lt")
    draw.text((50*s, (height-53)*s), "点击下方按钮，使用本页功能", font=desc_font, fill="#8b99ae", anchor="lt")
    return picture.resize((WIDTH, height), Image.Resampling.LANCZOS)


def render_command_menu(title: str, description: str, buttons: Sequence[dict], *, cache_dir: str | Path,
                        page: int = 1, page_size: int = 8) -> Path:
    """Draw one page of already-authorized buttons, in precisely their input order.

    ``page`` is one-based and ``page_size`` accepts 1–10. The caller should slice
    its displayed keyboard with the same bounds; this function never filters it.
    """
    if not isinstance(page_size, int) or isinstance(page_size, bool) or not 1 <= page_size <= 10:
        raise ValueError("page_size must be between 1 and 10")
    if not isinstance(page, int) or isinstance(page, bool):
        raise ValueError("page must be a one-based integer")
    values = [{"label": str(button.get("label", "")), "command": str(button.get("command", ""))}
              for button in buttons]
    pages = max(1, math.ceil(len(values)/page_size))
    if not 1 <= page <= pages:
        raise ValueError("page is outside the available menu pages")
    title, description = str(title), str(description)
    font_path = _choose_font(title+description+"".join(item["label"]+item["command"] for item in values))
    digest = _detail_identity(["commands", title, description, values, page_size], font_path)
    directory = Path(cache_dir)
    result = directory / f"commands-{digest}-{page:03d}.webp"
    with _LOCK:
        directory.mkdir(parents=True, exist_ok=True)
        if result.is_file() and result.stat().st_size > 16:
            return result
        start = (page-1)*page_size
        picture = _render_commands(title, description, values[start:start+page_size], font_path, page, pages, start)
        _write_picture(picture, result)
        _prune_page_cache(directory, "commands", digest)
    return result


def _render_help_page(title: str, lines: list[str], font_path: Path, page: int, pages: int) -> Image.Image:
    s = _SCALE
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    heading_font = ImageFont.truetype(str(font_path), 48*s)
    heading_height = 102+62*len(_wrap_all(measure, title or "功能帮助", heading_font, 984*s))
    top = heading_height+17
    height = max(400, top+47*len(lines)+118)
    picture = _detail_canvas(height)
    draw = ImageDraw.Draw(picture)
    _detail_header(draw, title, font_path, page, pages)
    draw.rounded_rectangle((48*s, top*s, 1032*s, (height-82)*s), radius=24*s, fill="white")
    body_font = ImageFont.truetype(str(font_path), 27*s)
    for index, line in enumerate(lines):
        color = "#5874a8" if line.lstrip().startswith(("#", "【")) else "#40536e"
        draw.text((75*s, (top+25+47*index)*s), line, font=body_font, fill=color, anchor="lt")
    footer_font = ImageFont.truetype(str(font_path), 21*s)
    draw.text((50*s, (height-47)*s), f"完整帮助 · 第{page}/{pages}页", font=footer_font, fill="#8997ad", anchor="lt")
    return picture.resize((WIDTH, height), Image.Resampling.LANCZOS)


def render_text_menu(title: str, text: str, *, cache_dir: str | Path) -> tuple[Path, ...]:
    """Render every source line, returning all pages in order, each ≤1800 px tall.

    Original line breaks and blank lines are preserved. Long lines wrap without
    ellipses; no command is removed or replaced with a shorter navigation list.
    """
    title, text = str(title), str(text)
    font_path = _choose_font(title+text)
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    body_font = ImageFont.truetype(str(font_path), 27*_SCALE)
    heading_font = ImageFont.truetype(str(font_path), 48*_SCALE)
    heading_height = 102+62*len(_wrap_all(measure, title or "功能帮助", heading_font, 984*_SCALE))
    capacity = min(24, (1800-heading_height-135)//47)
    if capacity < 1:
        raise ValueError("help title is too long to fit the image")
    lines = _wrap_all(measure, text, body_font, 930*_SCALE)
    chunks = [lines[index:index+capacity] for index in range(0, len(lines), capacity)]
    digest = _detail_identity(["help", title, text], font_path)
    directory = Path(cache_dir)
    results = tuple(directory / f"help-{digest}-{page:03d}.webp" for page in range(1, len(chunks)+1))
    with _LOCK:
        directory.mkdir(parents=True, exist_ok=True)
        for page, (chunk, result) in enumerate(zip(chunks, results), start=1):
            if not result.is_file() or result.stat().st_size <= 16:
                _write_picture(_render_help_page(title, chunk, font_path, page, len(chunks)), result)
        _prune_page_cache(directory, "help", digest)
    return results
