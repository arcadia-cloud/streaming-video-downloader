from datetime import datetime

import customtkinter as ctk

from gui.theme import COLORS, FONTS
from core.platforms import PLATFORMS


class DownloadView(ctk.CTkFrame):
    """下载视图：平台选择、URL 输入、操作按钮、日志区域。"""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.configure(fg_color=COLORS["bg"])

        self._build_url_section()
        self._build_log_section()
        self._build_stats_bar()
        self.set_state("idle")

    def _build_url_section(self):
        frame = ctk.CTkFrame(self, fg_color=COLORS["bg"])
        frame.pack(fill="x", padx=24, pady=(20, 8))

        top_row = ctk.CTkFrame(frame, fg_color="transparent")
        top_row.pack(fill="x", pady=(0, 4))

        ctk.CTkLabel(top_row, text="视频链接",
                     font=FONTS["subheading"],
                     fg_color="transparent",
                     text_color=COLORS["text"]).pack(side="left")

        platform_names = [p.display_name for p in PLATFORMS]
        self.platform_var = ctk.StringVar(value=platform_names[0])
        self.platform_menu = ctk.CTkOptionMenu(
            top_row,
            values=platform_names,
            variable=self.platform_var,
            font=FONTS["small"],
            dropdown_font=FONTS["small"],
            fg_color=COLORS["surface_alt"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_hover"],
            text_color=COLORS["text"],
            width=120, height=28,
        )
        self.platform_menu.pack(side="right")

        self.url_input = ctk.CTkTextbox(
            frame, height=80,
            font=FONTS["mono"],
            fg_color=COLORS["surface"],
            border_color=COLORS["border"],
            border_width=1,
            text_color=COLORS["text"],
        )
        self.url_input.pack(fill="x", pady=(4, 10))
        self.url_input.insert("1.0",
                              "每行一条链接，或用 | 分隔\n"
                              "支持 Bilibili / 抖音 链接")
        self.url_input.bind("<FocusIn>", self._clear_placeholder)

        self.action_btn = ctk.CTkButton(
            frame, text="启动浏览器",
            font=FONTS["default"],
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color="#1e1e1e",
            height=36,
            command=self._on_action,
        )
        self.action_btn.pack(fill="x")

    def _build_log_section(self):
        frame = ctk.CTkFrame(self, fg_color=COLORS["bg"])
        frame.pack(fill="both", expand=True, padx=24, pady=(4, 8))

        ctk.CTkLabel(frame, text="日志",
                     font=FONTS["subheading"],
                     fg_color="transparent",
                     text_color=COLORS["text"]).pack(anchor="w")

        self.log_textbox = ctk.CTkTextbox(
            frame,
            font=FONTS["mono"],
            fg_color=COLORS["surface"],
            border_color=COLORS["border"],
            border_width=1,
            text_color=COLORS["text"],
        )
        self.log_textbox.pack(fill="both", expand=True, pady=(4, 0))
        self.log_textbox.configure(state="disabled")

        self.log_textbox.tag_config("info", foreground=COLORS["text"])
        self.log_textbox.tag_config("success", foreground=COLORS["success"])
        self.log_textbox.tag_config("error", foreground=COLORS["error"])
        self.log_textbox.tag_config("dim", foreground=COLORS["text_dim"])

    def _build_stats_bar(self):
        bar = ctk.CTkFrame(self, fg_color=COLORS["surface"], height=32,
                           corner_radius=6)
        bar.pack(fill="x", padx=24, pady=(0, 16))
        bar.pack_propagate(False)

        self.status_label = ctk.CTkLabel(
            bar, text="状态: 未连接",
            font=FONTS["small"],
            fg_color="transparent",
            text_color=COLORS["text_dim"])
        self.status_label.pack(side="left", padx=12)

        self.stats_label = ctk.CTkLabel(
            bar, text="成功 0 / 失败 0",
            font=FONTS["small"],
            fg_color="transparent",
            text_color=COLORS["text_dim"])
        self.stats_label.pack(side="right", padx=12)

    def _clear_placeholder(self, event):
        full = self.url_input.get("1.0", "end-1c")
        if "每行一条链接" in full:
            self.url_input.delete("1.0", "end")

    def _on_action(self):
        state = self.app.get_state()
        if state == "idle":
            platform_name = self.platform_var.get()
            self.app.start_browser(platform_name)
        elif state == "ready":
            text = self.url_input.get("1.0", "end-1c").strip()
            if not text:
                self.add_log("请输入至少一条链接", "error")
                return
            self.app.start_download(text)

    def set_state(self, state: str):
        if state == "idle":
            self.action_btn.configure(text="启动浏览器", state="normal")
            self.url_input.configure(state="disabled")
            self._set_status("未连接")
        elif state == "launching":
            self.action_btn.configure(text="正在启动…", state="disabled")
            self._set_status("正在启动浏览器…")
        elif state == "waiting_login":
            self.action_btn.configure(text="等待登录…", state="disabled")
        elif state == "ready":
            self.action_btn.configure(text="下载", state="normal")
            self.url_input.configure(state="normal")
            self._set_status("已登录")
        elif state == "downloading":
            self.action_btn.configure(text="下载中…", state="disabled")
            self._set_status("下载中…")

    def _set_status(self, text: str):
        self.status_label.configure(text=f"状态: {text}")

    def set_login_countdown(self, seconds: int):
        self._set_status(f"等待登录… ({seconds}s)")

    def add_log(self, message: str, level: str = "info"):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_textbox.configure(state="normal")
        self.log_textbox.insert("end", f"[{ts}] {message}\n", level)
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

    def update_stats(self, success: int, fail: int):
        self.stats_label.configure(text=f"成功 {success} / 失败 {fail}")
