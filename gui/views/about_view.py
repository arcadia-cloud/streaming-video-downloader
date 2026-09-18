import webbrowser
import customtkinter as ctk

from gui.theme import COLORS, FONTS

GITHUB_URL = "https://github.com/arcadia-cloud/streaming-video-downloader"


class AboutView(ctk.CTkFrame):
    """关于视图。"""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.configure(fg_color=COLORS["bg"])

        container = ctk.CTkFrame(self, fg_color=COLORS["bg"])
        container.pack(fill="both", expand=True, padx=24, pady=20)

        ctk.CTkLabel(container, text="Bili Downloader",
                     font=FONTS["heading"],
                     fg_color="transparent",
                     text_color=COLORS["text"]).pack(anchor="w")

        ctk.CTkLabel(container, text="v1.0.0",
                     font=FONTS["small"],
                     fg_color="transparent",
                     text_color=COLORS["text_dim"]).pack(anchor="w", pady=(2, 16))

        ctk.CTkLabel(container,
                     text=("Bilibili 视频下载工具，支持批量下载、"
                           "音画合并，基于 DrissionPage 浏览器自动化。"),
                     font=FONTS["default"],
                     fg_color="transparent",
                     text_color=COLORS["text"],
                     wraplength=400,
                     justify="left").pack(anchor="w", pady=(0, 16))

        ctk.CTkLabel(container, text="技术栈",
                     font=FONTS["subheading"],
                     fg_color="transparent",
                     text_color=COLORS["text"]).pack(anchor="w", pady=(0, 4))

        ctk.CTkLabel(container,
                     text="Python  DrissionPage  MoviePy  CustomTkinter",
                     font=FONTS["mono"],
                     fg_color="transparent",
                     text_color=COLORS["text_dim"]).pack(anchor="w", pady=(0, 16))

        link = ctk.CTkLabel(container, text=GITHUB_URL,
                           font=FONTS["default"],
                           fg_color="transparent",
                           text_color=COLORS["accent"],
                           cursor="hand2")
        link.pack(anchor="w")
        link.bind("<Button-1>", lambda e: webbrowser.open(GITHUB_URL))

        ctk.CTkLabel(container, text="MIT License",
                     font=FONTS["small"],
                     fg_color="transparent",
                     text_color=COLORS["text_dim"]).pack(anchor="w", pady=(16, 0))
