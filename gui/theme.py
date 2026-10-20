"""视觉系统（v4）：浅色 / 深色双主题，颜色全部用 (light, dark) 元组。

CustomTkinter 的控件接受元组颜色，切换 `set_appearance_mode` 时会自动重绘，
所以换肤不需要重建界面；只有 Tk 原生对象（文本标签）需要用 `resolve()` 取当前值。
"""

from __future__ import annotations

import customtkinter as ctk

Pair = tuple[str, str]


def _pair(light: str, dark: str) -> Pair:
    return (light, dark)


COLORS: dict[str, Pair] = {
    # 背景与层次
    "bg": _pair("#F4F6FA", "#0B0D12"),
    "sidebar": _pair("#FFFFFF", "#0E1117"),
    "surface": _pair("#FFFFFF", "#151922"),
    "surface_2": _pair("#F2F5FA", "#1B2029"),
    "surface_3": _pair("#E7ECF3", "#242A35"),
    "border": _pair("#E2E7EF", "#232A36"),
    "hairline": _pair("#EBEFF5", "#1E242E"),

    # 文字
    "text": _pair("#12151A", "#E9EDF5"),
    "text_dim": _pair("#5A6373", "#98A1B2"),
    "text_faint": _pair("#8C94A3", "#5F6778"),

    # 强调色（靛蓝）
    "accent": _pair("#4F6BFF", "#7C97FF"),
    "accent_hover": _pair("#4060F5", "#92ABFF"),
    "accent_soft": _pair("#ECF0FF", "#1A2340"),
    "on_accent": _pair("#FFFFFF", "#0B0D12"),

    # 状态色
    "success": _pair("#0E8A55", "#3DD68C"),
    "success_soft": _pair("#E6F6EE", "#12281D"),
    "error": _pair("#CF4040", "#FF7B72"),
    "error_soft": _pair("#FCEBEB", "#2A1718"),
    "warning": _pair("#9A6410", "#E3B341"),

    # 平台色
    "bilibili": _pair("#D64280", "#FF86AE"),
    "douyin": _pair("#0B8F88", "#5EEAD4"),
    "xiaohongshu": _pair("#D92B3F", "#FF7A8A"),
}

FAMILY = "Microsoft YaHei UI"

FONTS = {
    "page": (FAMILY, 21, "bold"),
    "title": (FAMILY, 15, "bold"),
    "section": (FAMILY, 12),
    "body": (FAMILY, 13),
    "body_bold": (FAMILY, 13, "bold"),
    "small": (FAMILY, 12),
    "tiny": (FAMILY, 11),
    "mono": ("Consolas", 11),
    "mono_sm": ("Consolas", 10),
    "brand": ("Segoe UI Semibold", 14),
    "glyph": ("Segoe UI Symbol", 14),
}

RADIUS = {"card": 16, "inner": 12, "pill": 10}


def resolve(color) -> str:
    """取当前外观模式下的具体颜色（Tk 原生对象用）。"""
    if isinstance(color, tuple):
        return color[1] if ctk.get_appearance_mode() == "Dark" else color[0]
    return color
