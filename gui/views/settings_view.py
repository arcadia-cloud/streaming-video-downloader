"""设置页（v4）：外观、下载、插件三块卡片。"""

from __future__ import annotations

from datetime import datetime
from tkinter import StringVar, filedialog

import customtkinter as ctk

from core import config as app_config
from core import media
from gui.theme import COLORS, FONTS, RADIUS
from gui.widgets import (Card, Hairline, ScrollArea, ThemeSwitch,
                         ghost_button, primary_button, text_button)


class SettingsView(ctk.CTkFrame):
    PAGE_TITLE = "设置"
    PAGE_SUBTITLE = "外观、下载位置与插件"

    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app

        self.body = ScrollArea(self)
        self.body.pack(fill="both", expand=True)

        self._build_appearance()
        self._build_download()
        self._build_plugins()

    # ------------------------------------------------------------------
    def _section(self, title: str, hint: str) -> tuple[Card, ctk.CTkFrame]:
        card = Card(self.body)
        card.pack(fill="x", pady=(0, 14))

        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", padx=18, pady=16)

        ctk.CTkLabel(body, text=title, font=FONTS["title"],
                     text_color=COLORS["text"]).pack(anchor="w")
        ctk.CTkLabel(body, text=hint, font=FONTS["tiny"],
                     text_color=COLORS["text_faint"]).pack(anchor="w",
                                                           pady=(4, 14))
        return card, body

    def _build_appearance(self):
        _, body = self._section("外观", "浅色、深色，或跟随 Windows 系统主题")
        self.theme_switch = ThemeSwitch(body, self.app.set_appearance,
                                        width=78)
        self.theme_switch.pack(anchor="w")
        self.theme_switch.set_value(app_config.load().get("appearance", "dark"))

    def _build_download(self):
        _, body = self._section("下载", "视频与图文会按平台分到不同子目录")

        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill="x")

        self.path_var = StringVar(value=str(app_config.download_dir()))
        self.entry = ctk.CTkEntry(
            row, textvariable=self.path_var, height=38, corner_radius=10,
            border_width=1, border_color=COLORS["border"],
            fg_color=COLORS["surface_2"], text_color=COLORS["text"],
            font=FONTS["mono"],
        )
        self.entry.pack(side="left", fill="x", expand=True)

        ghost_button(row, "浏览", self._browse, width=58).pack(
            side="left", padx=(8, 0))
        ghost_button(row, "打开", self._open, width=58).pack(
            side="left", padx=(8, 0))

        hint = ctk.CTkFrame(body, fg_color="transparent")
        hint.pack(fill="x", pady=(8, 0))
        ctk.CTkLabel(
            hint, text="视频 → bili_video / dy_video，图文 → dy_photo/<标题>/",
            font=FONTS["tiny"], text_color=COLORS["text_faint"],
        ).pack(side="left")

        Hairline(body).pack(fill="x", pady=(16, 0))

        row2 = ctk.CTkFrame(body, fg_color="transparent")
        row2.pack(fill="x", pady=(14, 0))
        ctk.CTkLabel(row2, text="下载完成后自动打开文件夹", font=FONTS["small"],
                     text_color=COLORS["text_dim"]).pack(side="left")
        self.auto_open = ctk.CTkSwitch(
            row2, text="", width=46, height=22,
            switch_width=38, switch_height=20,
            progress_color=COLORS["accent"],
            button_color=("#FFFFFF", "#FFFFFF"),
            button_hover_color=("#F3F6FA", "#F3F6FA"),
            fg_color=COLORS["surface_3"],
        )
        self.auto_open.pack(side="left", padx=(12, 0))
        if app_config.load().get("open_after_done"):
            self.auto_open.select()

        Hairline(body).pack(fill="x", pady=(14, 0))

        row3 = ctk.CTkFrame(body, fg_color="transparent")
        row3.pack(fill="x", pady=(12, 0))
        ctk.CTkLabel(row3, text="配置文件", font=FONTS["tiny"],
                     text_color=COLORS["text_faint"]).pack(side="left")
        ctk.CTkLabel(row3, text=str(app_config.config_path()),
                     font=FONTS["mono_sm"],
                     text_color=COLORS["text_dim"]).pack(
            side="left", padx=(10, 0))

        foot = ctk.CTkFrame(body, fg_color="transparent")
        foot.pack(fill="x", pady=(18, 0))
        primary_button(foot, "保存设置", self._save, width=108).pack(side="left")
        self.save_hint = ctk.CTkLabel(foot, text="", font=FONTS["tiny"],
                                      text_color=COLORS["success"])
        self.save_hint.pack(side="left", padx=(12, 0))

    def _build_plugins(self):
        _, body = self._section("插件", "plugins/ 目录下的插件会在启动时自动加载")

        self.plugin_meta = ctk.CTkLabel(body, text="", font=FONTS["tiny"],
                                        text_color=COLORS["text_faint"])
        self.plugin_meta.pack(anchor="w")

        self.plugin_host = ctk.CTkFrame(body, fg_color="transparent")
        self.plugin_host.pack(fill="x", pady=(8, 0))

        self.plugin_empty = ctk.CTkLabel(
            self.plugin_host, text="没有启用的插件",
            font=FONTS["small"], text_color=COLORS["text_faint"],
        )
        self.plugin_empty.pack(anchor="w")

    # ------------------------------------------------------------------
    def sync_theme(self, mode: str) -> None:
        self.theme_switch.set_value(mode)

    def set_plugins(self, plugins: list) -> None:
        self.plugin_meta.configure(text=f"已加载 {len(plugins)} 个")
        if not plugins:
            return
        self.plugin_empty.pack_forget()

        for plugin in plugins:
            line = ctk.CTkFrame(self.plugin_host, fg_color="transparent")
            line.pack(fill="x", pady=(12, 0))

            text = ctk.CTkFrame(line, fg_color="transparent")
            text.pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(text, text=plugin.name or plugin.__class__.__name__,
                         font=FONTS["small"], text_color=COLORS["text"],
                         anchor="w").pack(anchor="w")
            ctk.CTkLabel(text, text=plugin.description or "无描述",
                         font=FONTS["tiny"], text_color=COLORS["text_faint"],
                         anchor="w").pack(anchor="w", pady=(2, 0))

            ctk.CTkLabel(line, text=f"v{plugin.version}", font=FONTS["tiny"],
                         text_color=COLORS["text_faint"]).pack(side="right")

            widget = None
            try:
                widget = plugin.get_settings_widget(line)
            except Exception:  # noqa: BLE001
                widget = None
            if widget is not None:
                widget.pack(side="right", padx=(0, 10))

            Hairline(self.plugin_host).pack(fill="x", pady=(12, 0))

    # ------------------------------------------------------------------
    def _browse(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.path_var.get())
        if chosen:
            self.path_var.set(chosen)

    def _open(self) -> None:
        try:
            media.open_folder(app_config.download_dir())
        except OSError as exc:
            self._hint(f"打开失败：{exc}", COLORS["error"])

    def _save(self) -> None:
        path = self.path_var.get().strip()
        if not path:
            self._hint("目录不能为空", COLORS["error"])
            return
        try:
            app_config.save({
                "download_dir": path,
                "open_after_done": bool(self.auto_open.get()),
                "appearance": app_config.load().get("appearance", "dark"),
            })
        except OSError as exc:
            self._hint(f"保存失败：{exc}", COLORS["error"])
            return

        self.app.reload_config()
        self._hint(f"已保存 · {datetime.now():%H:%M:%S}", COLORS["success"])

    def _hint(self, text: str, color) -> None:
        self.save_hint.configure(text=text, text_color=color)
