"""关于页（v4）。"""

from __future__ import annotations

import webbrowser

import customtkinter as ctk

from gui.theme import COLORS, FONTS, RADIUS
from gui.widgets import Card, ScrollArea, wrap_to_width

GITHUB_URL = "https://github.com/arcadia-cloud/streaming-video-downloader"
FEATURES = ["批量解析", "音视频合并", "图文下载", "插件扩展"]


class AboutView(ctk.CTkFrame):
    PAGE_TITLE = "关于"
    PAGE_SUBTITLE = "一个基于浏览器自动化的多平台下载器"

    def __init__(self, master, app, version: str):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.version = version

        self.body = ScrollArea(self)
        self.body.pack(fill="both", expand=True)

        self._build_brand()
        self._build_info()

    def _build_brand(self):
        card = Card(self.body)
        card.pack(fill="x", pady=(0, 14))

        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", padx=18, pady=18)

        top = ctk.CTkFrame(body, fg_color="transparent")
        top.pack(fill="x")

        logo = ctk.CTkFrame(top, width=54, height=54, corner_radius=15,
                            fg_color=COLORS["accent"])
        logo.pack(side="left")
        logo.pack_propagate(False)
        ctk.CTkLabel(logo, text="▶", font=(FONTS["glyph"][0], 16),
                     text_color=COLORS["on_accent"]).place(
            relx=0.5, rely=0.5, anchor="center")

        names = ctk.CTkFrame(top, fg_color="transparent")
        names.pack(side="left", padx=(16, 0))
        row = ctk.CTkFrame(names, fg_color="transparent")
        row.pack(anchor="w")
        ctk.CTkLabel(row, text="Video Downloader", font=FONTS["page"],
                     text_color=COLORS["text"]).pack(side="left")
        ctk.CTkLabel(row, text=f"v{self.version}", font=FONTS["tiny"],
                     text_color=COLORS["text_faint"]).pack(
            side="left", padx=(8, 0), pady=(6, 0))
        ctk.CTkLabel(names, text="Bilibili · 抖音 · 小红书（即将支持）",
                     font=FONTS["tiny"],
                     text_color=COLORS["text_faint"]).pack(anchor="w", pady=(4, 0))

        description = ctk.CTkLabel(
            body,
            text=("自动识别链接所属平台，批量下载视频。Bilibili 分离下载音视频流后"
                  "本地合并，抖音支持视频与图文，图片按页面顺序保存。"),
            font=FONTS["body"], text_color=COLORS["text_dim"],
            justify="left", anchor="w",
        )
        description.pack(fill="x", pady=(20, 0))
        wrap_to_width(description)

        chips = ctk.CTkFrame(body, fg_color="transparent")
        chips.pack(fill="x", pady=(16, 0))
        for text in FEATURES:
            chip = ctk.CTkFrame(chips, fg_color=COLORS["surface_2"],
                                corner_radius=8)
            chip.pack(side="left", padx=(0, 8))
            ctk.CTkLabel(chip, text=text, font=FONTS["tiny"],
                         text_color=COLORS["text_dim"]).pack(padx=10, pady=4)

    def _build_info(self):
        card = Card(self.body)
        card.pack(fill="x")
        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", padx=18, pady=16)

        self._info_row(body, "技术栈", "Python · DrissionPage · ffmpeg · CustomTkinter")
        self._info_row(body, "开源协议", "MIT License")
        self._info_row(body, "项目主页", GITHUB_URL, link=True)

        disclaimer = ctk.CTkLabel(
            body,
            text=("仅供技术交流与学习。下载需要登录对应平台账号，使用存在账号风险，"
                  "请遵守各平台用户协议，勿用于商业用途。"),
            font=FONTS["tiny"], text_color=COLORS["text_faint"],
            justify="left", anchor="w",
        )
        disclaimer.pack(fill="x", pady=(18, 0))
        wrap_to_width(disclaimer)

    def _info_row(self, parent, label: str, value: str,
                  link: bool = False) -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=5)

        ctk.CTkLabel(row, text=label, width=76, anchor="w",
                     font=FONTS["tiny"],
                     text_color=COLORS["text_faint"]).pack(side="left")

        widget = ctk.CTkLabel(
            row, text=value, anchor="w", font=FONTS["small"],
            text_color=COLORS["accent"] if link else COLORS["text_dim"],
            cursor="hand2" if link else "arrow",
        )
        widget.pack(side="left")
        if link:
            widget.bind("<Button-1>", lambda _e: webbrowser.open(GITHUB_URL))
