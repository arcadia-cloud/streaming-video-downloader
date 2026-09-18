import os
from tkinter import filedialog, StringVar

import customtkinter as ctk

from gui.theme import COLORS, FONTS


class SettingsView(ctk.CTkFrame):
    """设置视图。"""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.configure(fg_color=COLORS["bg"])

        container = ctk.CTkFrame(self, fg_color=COLORS["bg"])
        container.pack(fill="both", expand=True, padx=24, pady=20)

        ctk.CTkLabel(container, text="设置",
                     font=FONTS["heading"],
                     fg_color="transparent",
                     text_color=COLORS["text"]).pack(anchor="w", pady=(0, 16))

        path_frame = ctk.CTkFrame(container, fg_color=COLORS["surface"],
                                  corner_radius=8, height=50)
        path_frame.pack(fill="x", pady=(0, 10))
        path_frame.pack_propagate(False)

        ctk.CTkLabel(path_frame, text="下载目录",
                     font=FONTS["default"],
                     fg_color="transparent",
                     text_color=COLORS["text"]).pack(side="left", padx=12)

        self.path_var = StringVar(
            value=os.environ.get(
                "BILI_DOWNLOADER_DIR",
                os.path.join(os.path.expanduser("~"), "video_downloader")
            ))
        path_entry = ctk.CTkEntry(path_frame, textvariable=self.path_var,
                                  font=FONTS["mono"],
                                  fg_color=COLORS["surface_alt"],
                                  border_color=COLORS["border"])
        path_entry.pack(side="left", fill="x", expand=True, padx=8)

        ctk.CTkButton(path_frame, text="浏览",
                      font=FONTS["small"],
                      fg_color=COLORS["accent"],
                      hover_color=COLORS["accent_hover"],
                      text_color="#1e1e1e",
                      width=60,
                      command=self._browse).pack(side="right", padx=(0, 8))

        ctk.CTkButton(container, text="保存设置",
                      font=FONTS["default"],
                      fg_color=COLORS["accent"],
                      hover_color=COLORS["accent_hover"],
                      text_color="#1e1e1e",
                      height=36,
                      command=self._save).pack(anchor="w", pady=(10, 0))

        ctk.CTkLabel(container,
                     text="设置仅对当前会话生效，重启后需重新配置。",
                     font=FONTS["small"],
                     fg_color="transparent",
                     text_color=COLORS["text_dim"]).pack(anchor="w", pady=(8, 0))

    def _browse(self):
        chosen = filedialog.askdirectory(initialdir=self.path_var.get())
        if chosen:
            self.path_var.set(chosen)

    def _save(self):
        path = self.path_var.get()
        os.environ["BILI_DOWNLOADER_DIR"] = path
        self.app.download_view.add_log(f"下载目录已设为: {path}", "info")
