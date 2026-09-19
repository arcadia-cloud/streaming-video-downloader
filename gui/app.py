import os
import sys
import queue
import threading
import importlib
import pkgutil

import customtkinter as ctk

from gui.theme import COLORS, FONTS
from gui.views.download_view import DownloadView
from gui.views.settings_view import SettingsView
from gui.views.about_view import AboutView
from core.browser import BrowserManager
from core.dp_tools import DpTools
from core.platforms import PLATFORMS


class App(ctk.CTk):
    """主应用窗口。"""

    SIDEBAR_ITEMS = [
        ("download", "下载"),
        ("settings", "设置"),
        ("about", "关于"),
    ]

    def __init__(self):
        super().__init__()

        self.title("Video Downloader")
        self.geometry("860x620")
        self.minsize(700, 500)
        self.configure(fg_color=COLORS["bg"])

        ctk.set_appearance_mode("dark")

        self._state = "idle"
        self.browser = BrowserManager()
        self._log_queue: queue.Queue = queue.Queue()
        self.plugins = []

        self._build_sidebar()
        self._build_content()
        self._load_plugins()
        self._switch_view("download")

        self.after(100, self._poll_log_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_sidebar(self):
        self.sidebar = ctk.CTkFrame(
            self, width=170,
            fg_color=COLORS["sidebar"],
            corner_radius=0)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        ctk.CTkLabel(
            self.sidebar, text="Video\nDownloader",
            font=FONTS["subheading"],
            fg_color="transparent",
            text_color=COLORS["accent"],
            justify="left").pack(anchor="w", padx=20, pady=(20, 30))

        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        for key, label in self.SIDEBAR_ITEMS:
            btn = ctk.CTkButton(
                self.sidebar, text=label,
                font=FONTS["sidebar"],
                fg_color="transparent",
                hover_color=COLORS["sidebar_hover"],
                text_color=COLORS["text_dim"],
                anchor="w",
                height=38,
                corner_radius=6,
                command=lambda k=key: self._switch_view(k),
            )
            btn.pack(fill="x", padx=8, pady=2)
            self.nav_buttons[key] = btn

        platform_names = " / ".join(p.display_name for p in PLATFORMS)
        ctk.CTkLabel(
            self.sidebar, text=f"v1.2.0\n{platform_names}",
            font=FONTS["small"],
            fg_color="transparent",
            text_color=COLORS["text_dim"]).pack(
                side="bottom", padx=20, pady=16)

    def _build_content(self):
        self.content = ctk.CTkFrame(
            self, fg_color=COLORS["bg"], corner_radius=0)
        self.content.pack(side="right", fill="both", expand=True)

        self.download_view = DownloadView(self.content, self)
        self.settings_view = SettingsView(self.content, self)
        self.about_view = AboutView(self.content, self)

        self.views = {
            "download": self.download_view,
            "settings": self.settings_view,
            "about": self.about_view,
        }

    def _switch_view(self, key: str):
        for k, view in self.views.items():
            if k == key:
                view.pack(fill="both", expand=True)
            else:
                view.pack_forget()

        for k, btn in self.nav_buttons.items():
            color = COLORS["accent"] if k == key else COLORS["text_dim"]
            btn.configure(text_color=color)

    def get_state(self) -> str:
        return self._state

    def _set_state(self, state: str):
        self._state = state
        self.download_view.set_state(state)

    def start_browser(self, platform_name: str = None):
        if platform_name:
            for p in PLATFORMS:
                if p.display_name == platform_name:
                    self.browser.set_platform(p)
                    break

        self._set_state("launching")
        self.log(f"正在启动浏览器（{self.browser.platform.display_name}）…")

        def _launch():
            try:
                self.browser.launch()
                self._set_state("waiting_login")
                platform_name = self.browser.platform.display_name
                self.log(f"请在浏览器中登录 {platform_name}")
                self.browser.wait_for_login(
                    on_status=self._on_login_wait,
                    on_countdown=self._on_login_countdown,
                    on_success=self._on_login_success,
                    on_timeout=self._on_login_timeout,
                )
            except Exception as e:
                self.log(f"浏览器启动失败: {e}", "error")
                self.after(0, lambda: self._set_state("idle"))

        threading.Thread(target=_launch, daemon=True).start()

    def _on_login_wait(self, count: int):
        remaining = 40 - count
        self.after(0, lambda: self.download_view.set_login_countdown(remaining))

    def _on_login_countdown(self, seconds: int):
        self.after(0, lambda: self.download_view.set_login_countdown(seconds))

    def _on_login_success(self):
        self.log("登录成功", "success")
        self.after(0, lambda: self._set_state("ready"))

    def _on_login_timeout(self):
        self.log("登录超时，程序即将退出", "error")
        try:
            self.browser.quit()
        except Exception:
            pass
        self.after(0, self.destroy)

    def start_download(self, urls_text: str):
        urls = self.browser.parse_urls(urls_text)
        if not urls:
            supported = ", ".join(p.url_prefix for p in PLATFORMS)
            self.log(f"未检测到有效链接，支持: {supported}", "error")
            return

        self._set_state("downloading")
        self.download_view.update_stats(0, 0)
        self.log(f"共 {len(urls)} 条链接，开始下载")

        def _run():
            success = 0
            fail = 0
            for i, url in enumerate(urls):
                platform = self.browser.get_platform_for_url(url)
                self.log(f"[{i + 1}/{len(urls)}] {url}")

                for plugin in self.plugins:
                    try:
                        plugin.on_download_start(url)
                    except Exception:
                        pass

                video_page = None
                name = None
                download_ok = False
                try:
                    video_page = self.browser.page.new_tab()
                    headers = DpTools(
                        ck_dict_li=video_page.cookies(),
                        referer=url,
                        user_agent=video_page.user_agent,
                    ).simp_cookie().build_headers()

                    video_page.get(url)
                    video_page._wait_loaded()

                    name = platform.get_video_name(video_page)
                    if not name:
                        name = f"anonymous{i}"

                    platform.download(video_page, url, headers, name)

                    download_ok = True
                    success += 1
                    self.log(f"下载成功: {name}", "success")
                except Exception as e:
                    fail += 1
                    self.log(f"下载失败: {e}", "error")
                finally:
                    if video_page:
                        try:
                            video_page.close()
                        except Exception:
                            pass

                    for plugin in self.plugins:
                        try:
                            out_dir = os.environ.get(
                                "BILI_DOWNLOADER_DIR",
                                os.path.join(os.path.expanduser("~"), "video_downloader")
                            )
                            out_path = os.path.join(
                                out_dir, platform.sub_folder,
                                f"{name or 'unknown'}.mp4"
                            )
                            plugin.on_download_complete(
                                url, out_path, download_ok
                            )
                        except Exception:
                            pass

                self.after(0, lambda s=success, f=fail:
                           self.download_view.update_stats(s, f))

            self.log(f"全部完成: 成功 {success}，失败 {fail}", "info")
            self.after(0, lambda: self._set_state("ready"))

        threading.Thread(target=_run, daemon=True).start()

    def log(self, message: str, level: str = "info"):
        self._log_queue.put((message, level))

    def _poll_log_queue(self):
        try:
            while True:
                msg, level = self._log_queue.get_nowait()
                self.download_view.add_log(msg, level)
        except queue.Empty:
            pass
        self.after(100, self._poll_log_queue)

    def _load_plugins(self):
        try:
            import plugins
            from core.plugin_base import PluginBase

            for _, modname, _ in pkgutil.iter_modules(plugins.__path__):
                try:
                    module = importlib.import_module(f"plugins.{modname}")
                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        if (isinstance(attr, type) and
                                issubclass(attr, PluginBase) and
                                attr is not PluginBase):
                            plugin = attr()
                            plugin.on_init(self.browser)
                            self.plugins.append(plugin)
                            self.log(f"插件已加载: {plugin.name}", "dim")
                except Exception as e:
                    self.log(f"插件加载失败 [{modname}]: {e}", "error")
        except Exception:
            pass

    def _on_close(self):
        try:
            self.browser.quit()
        except Exception:
            pass
        for plugin in self.plugins:
            try:
                plugin.on_shutdown()
            except Exception:
                pass
        self.destroy()
