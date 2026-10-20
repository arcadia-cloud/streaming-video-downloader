"""主窗口（v4）：侧边导航 + 页面头部 + 双主题。

界面分三块：左侧导航（含外观切换）、顶部页头（标题 / 状态 / 快捷入口）、
内容区（下载 / 设置 / 关于）。
"""

from __future__ import annotations

import importlib
import os
import pkgutil
import queue
import re
import threading
import time
from tkinter import messagebox

import customtkinter as ctk

from core import config as app_config
from core import media
from core import urls as url_tools
from core.browser import BrowserManager
from core.platforms import PLATFORMS
from core.platforms.bilibili import page_url, parse_parts
from gui.theme import COLORS, FONTS
from gui.views.about_view import AboutView
from gui.views.download_view import DownloadView
from gui.views.settings_view import SettingsView
from gui.widgets import Hairline, NavItem, StatusPill, ThemeSwitch, ghost_button

NAV_ITEMS = (
    ("download", "下载", "↓"),
    ("settings", "设置", "⚙"),
    ("about", "关于", "ⓘ"),
)


class App(ctk.CTk):
    VERSION = "4.0.0"

    def __init__(self):
        self.config = app_config.load()
        ctk.set_appearance_mode(self.config.get("appearance", "dark"))

        super().__init__(fg_color=COLORS["bg"])
        self.title("Video Downloader")
        self._apply_initial_geometry()

        self._events: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._state = "idle"
        self._closed = False
        self._view = "download"
        self._queue: list[tuple] = []
        self._queue_lock = threading.Lock()
        self._worker_active = False

        self.browser = BrowserManager()
        self.plugins: list = []

        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_main()

        self._load_plugins()
        self._show_view("download")

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Control-Return>", lambda _e: self._shortcut_action())
        self.bind("<Escape>", lambda _e: self.stop_download())
        self.after(60, self._pump)

    # ------------------------------------------------------------------
    # 窗口
    # ------------------------------------------------------------------
    def _apply_initial_geometry(self) -> None:
        try:
            scale = float(self.tk.call("tk", "scaling")) * 72 / 96
        except Exception:  # noqa: BLE001
            scale = 1.0
        scale = scale if scale > 0 else 1.0

        screen_w = int(self.winfo_screenwidth() / scale)
        screen_h = int(self.winfo_screenheight() / scale)

        width = max(980, min(1180, screen_w - 60))
        height = max(660, min(780, screen_h - 90))
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2 - 10)

        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(min(980, width), min(660, height))

    # ------------------------------------------------------------------
    # 骨架
    # ------------------------------------------------------------------
    def _build_sidebar(self):
        bar = ctk.CTkFrame(self, width=232, corner_radius=0,
                           fg_color=COLORS["sidebar"])
        bar.grid(row=0, column=0, sticky="nsw")
        bar.grid_propagate(False)
        self.sidebar = bar

        edge = ctk.CTkFrame(bar, width=1, corner_radius=0,
                            fg_color=COLORS["border"])
        edge.place(relx=1.0, rely=0, relheight=1.0, anchor="ne")

        brand = ctk.CTkFrame(bar, fg_color="transparent")
        brand.pack(fill="x", padx=18, pady=(22, 26))

        mark = ctk.CTkFrame(brand, width=36, height=36, corner_radius=11,
                            fg_color=COLORS["accent"])
        mark.pack(side="left")
        mark.pack_propagate(False)
        ctk.CTkLabel(mark, text="▶", font=(FONTS["glyph"][0], 13),
                     text_color=COLORS["on_accent"]).place(
            relx=0.5, rely=0.5, anchor="center")

        text = ctk.CTkFrame(brand, fg_color="transparent")
        text.pack(side="left", padx=(10, 0))
        ctk.CTkLabel(text, text="Video Downloader", font=FONTS["brand"],
                     text_color=COLORS["text"]).pack(anchor="w")
        ctk.CTkLabel(text, text=f"v{self.VERSION}", font=FONTS["tiny"],
                     text_color=COLORS["text_faint"]).pack(anchor="w")

        nav = ctk.CTkFrame(bar, fg_color="transparent")
        nav.pack(fill="x", padx=12)
        self.nav_items: dict[str, NavItem] = {}
        for key, label, icon in NAV_ITEMS:
            item = NavItem(nav, label, icon, lambda k=key: self._show_view(k))
            item.pack(fill="x", pady=2)
            self.nav_items[key] = item

        ctk.CTkFrame(bar, fg_color="transparent").pack(fill="both", expand=True)

        theme_card = ctk.CTkFrame(bar, fg_color="transparent")
        theme_card.pack(fill="x", padx=18, pady=(0, 16))
        ctk.CTkLabel(theme_card, text="外观", font=FONTS["tiny"],
                     text_color=COLORS["text_faint"]).pack(anchor="w",
                                                           pady=(0, 6))
        self.theme_switch = ThemeSwitch(theme_card, self.set_appearance,
                                        width=56)
        self.theme_switch.pack(anchor="w")
        self.theme_switch.set_value(self.config.get("appearance", "dark"))

        ctk.CTkLabel(bar, text="MIT License · DrissionPage",
                     font=FONTS["tiny"], text_color=COLORS["text_faint"]).pack(
            anchor="w", padx=18, pady=(0, 18))

    def _build_main(self):
        main = ctk.CTkFrame(self, fg_color=COLORS["bg"], corner_radius=0)
        main.grid(row=0, column=1, sticky="nsew")

        header = ctk.CTkFrame(main, fg_color="transparent")
        header.pack(fill="x", padx=28, pady=(22, 0))

        left = ctk.CTkFrame(header, fg_color="transparent")
        left.pack(side="left", anchor="n")
        self.page_title = ctk.CTkLabel(left, text="下载", font=FONTS["page"],
                                       text_color=COLORS["text"])
        self.page_title.pack(anchor="w")
        self.page_subtitle = ctk.CTkLabel(
            left, text="", font=FONTS["small"],
            text_color=COLORS["text_dim"])
        self.page_subtitle.pack(anchor="w", pady=(4, 0))

        right = ctk.CTkFrame(header, fg_color="transparent")
        right.pack(side="right", anchor="ne", pady=(4, 0))
        self.status_pill = StatusPill(right, "未连接", "neutral")
        self.status_pill.pack(side="right", padx=(10, 0))
        ghost_button(right, "打开目录", self.open_download_dir,
                     width=72).pack(side="right")

        Hairline(main).pack(fill="x", padx=28, pady=(18, 0))

        self.host = ctk.CTkFrame(main, fg_color="transparent")
        self.host.pack(fill="both", expand=True, padx=28, pady=(16, 18))

        self.download_view = DownloadView(self.host, self)
        self.settings_view = SettingsView(self.host, self)
        self.about_view = AboutView(self.host, self, self.VERSION)

        self.views = {
            "download": self.download_view,
            "settings": self.settings_view,
            "about": self.about_view,
        }

    def _show_view(self, key: str) -> None:
        if key not in self.views:
            return
        for name, view in self.views.items():
            if name == key:
                view.pack(fill="both", expand=True)
            else:
                view.pack_forget()

        for name, item in self.nav_items.items():
            item.set_active(name == key)

        view = self.views[key]
        self.page_title.configure(text=view.PAGE_TITLE)
        self.page_subtitle.configure(text=view.PAGE_SUBTITLE)
        self._view = key

    # ------------------------------------------------------------------
    # 外观
    # ------------------------------------------------------------------
    def set_appearance(self, mode: str) -> None:
        if mode not in ("light", "dark", "system"):
            mode = "dark"
        ctk.set_appearance_mode(mode)
        self.theme_switch.set_value(mode)
        self.settings_view.sync_theme(mode)

        self.config = dict(self.config)
        self.config["appearance"] = mode
        try:
            app_config.save(self.config)
        except OSError as exc:
            self._log(f"外观偏好未能写入配置（{exc}），本次仍然生效", "warn")
        self.download_view.refresh_theme()
        self._log(f"外观已切换为 {_MODE_LABELS.get(mode, mode)}")

    def _set_appearance_mode(self, mode_string: str):
        super()._set_appearance_mode(mode_string)
        view = getattr(self, "download_view", None)
        if view is not None:
            view.refresh_theme()

    # ------------------------------------------------------------------
    # 事件总线
    # ------------------------------------------------------------------
    def emit(self, kind: str, payload=None) -> None:
        self._events.put((kind, payload))

    def _pump(self) -> None:
        try:
            while True:
                kind, payload = self._events.get_nowait()
                self._dispatch(kind, payload)
        except queue.Empty:
            pass
        if not self._closed:
            self.after(60, self._pump)

    def _dispatch(self, kind: str, payload) -> None:
        if kind == "log":
            self.download_view.append_log(payload["text"],
                                          payload.get("level", "info"))
        elif kind == "status":
            self.status_pill.set(payload["text"], payload.get("tone", "neutral"))
        elif kind == "state":
            self._state = payload
            self.download_view.set_state(payload)
        elif kind == "queue":
            self.download_view.set_queue(payload)
        elif kind == "queue_append":
            self.download_view.append_queue(payload)
        elif kind == "item":
            self.download_view.update_item(payload["index"], payload["state"],
                                           payload.get("note", ""))
        elif kind == "item_progress":
            self.download_view.update_item_progress(payload["index"],
                                                    payload["progress"])
        elif kind == "stats":
            self.download_view.set_stats(payload["ok"], payload["fail"])
        elif kind == "progress":
            self.download_view.set_progress(payload)
        elif kind == "dialog":
            try:
                messagebox.showwarning(payload.get("title", "提示"),
                                       payload.get("text", ""), parent=self)
            except Exception:  # noqa: BLE001 - 弹窗失败不应影响主流程
                pass

    def _log(self, text: str, level: str = "info") -> None:
        self.emit("log", {"text": text, "level": level})

    def _status(self, text: str, tone: str = "neutral") -> None:
        self.emit("status", {"text": text, "tone": tone})

    def _set_state(self, state: str) -> None:
        self._state = state
        self.emit("state", state)

    def _shortcut_action(self) -> None:
        if self._view != "download":
            self._show_view("download")
        self.download_view.trigger_action()

    # ------------------------------------------------------------------
    # 浏览器
    # ------------------------------------------------------------------
    def _open_browser_for_login(self) -> None:
        """确保有一个窗口停在登录页；已有窗口就复用，避免重新登录。"""
        had_page = self.browser.page is not None
        self.browser.ensure()      # 用户手动关掉 Chrome 后引用会失效
        if had_page and self.browser.page is None:
            self._log("检测到你已关闭浏览器，正在重新启动", "warn")
        if self.browser.page is None:
            self.browser.launch()
            self._log(f"浏览器：{self.browser.browser_label()}")
        else:
            try:
                self.browser.page.get(self.browser.platform.login_url())
            except Exception:  # noqa: BLE001 - 复用窗口失败不算致命
                pass
        # 要扫码/输密码，窗口得在前台
        self.browser.restore()

    def _login_then_download(self, tasks: list) -> None:
        """粘贴 → 点开始 → 自动开浏览器 → 登录 → 自动下载。"""
        try:
            self._open_browser_for_login()
        except Exception as exc:  # noqa: BLE001
            self._log(f"浏览器启动失败：{exc}", "error")
            self._status("启动失败", "error")
            self._set_state("idle")
            return

        self._log("请在浏览器窗口完成登录，成功后会自动开始下载", "info")
        self._set_state("waiting_login")
        self._status("等待登录", "accent")

        ok = self.browser.wait_login(
            timeout=180, on_tick=self._tick_login,
            should_stop=self._stop.is_set,
        )
        if not ok:
            if self._stop.is_set():
                self._set_state("idle")
                return
            self._log("登录未完成：链接已保留，可再次点击「开始下载」重试", "warn")
            self._status("未登录", "neutral")
            self._set_state("idle")
            return
        if self._stop.is_set():
            self._set_state("ready")
            return

        self._log("登录成功，开始下载", "success")
        self._set_state("ready")
        # 登录页留着只会让窗口越来越乱；清掉标签再最小化，别挡在前面
        self.browser.reset_tabs()
        self.browser.minimize()
        self._begin_download(tasks, reset=True)

    def _tick_login(self, seconds: int) -> None:
        self._status(f"等待登录 · {seconds}s", "accent")

    def set_platform(self, name: str) -> None:
        target = next((p for p in PLATFORMS if p.name == name), None)
        if target is None or target is self.browser.platform:
            return

        self.browser.set_platform(target)
        if self._state != "idle":
            self._set_state("idle")
            self._status("已切换平台", "warn")
            self._log(f"平台已切换为 {target.display_name}，"
                      "请再次点击「开始下载」完成登录", "warn")
        else:
            self._log(f"平台已切换为 {target.display_name}")

    # ------------------------------------------------------------------
    # 下载
    # ------------------------------------------------------------------
    def _collect_tasks(self) -> list[tuple] | None:
        """解析输入框 + 来源校验，返回 (platform, url, options)。"""
        text = self.download_view.get_text()
        if not text.strip():
            self._log("输入框是空的：先粘贴链接或分享文案", "warn")
            self._status("没有有效链接", "warn")
            return None

        # 每次点击都按当前输入重新判定：先取消待执行的防抖重建，
        # 否则刚改完链接就点击时，读到的还是上一轮的链接行
        self.download_view.flush_parts()

        urls = self._filter_plugins(self.browser.parse_urls(text))
        if urls:
            self._log(f"识别到 {len(urls)} 条链接")
        if not urls:
            self.download_view.focus_input()
            # 分清"完全没链接"和"有链接但不支持"——后者多半是域名变了
            seen = [c for c in url_tools.iter_candidates(text) if "." in c]
            if seen:
                hosts = sorted({c.split("//")[-1].split("/")[0] for c in seen})[:3]
                messagebox.showwarning(
                    "链接不在支持范围",
                    "识别到了链接，但不属于已支持的平台：\n\n"
                    + "\n".join(hosts)
                    + "\n\n目前支持 Bilibili、抖音、小红书。",
                    parent=self,
                )
                self._log(f"不支持的域名：{'、'.join(hosts)}", "warn")
                return None
            messagebox.showwarning(
                "没有识别到链接",
                "输入框里没有可识别的视频链接。\n\n"
                "可以直接粘贴分享文案，多条链接用换行或空格分开。",
                parent=self,
            )
            self._log("没有识别到链接：可以直接粘贴分享文案", "warn")
            return None

        self._report_parsing(text, urls)

        tasks: list[tuple] = []
        unrouted: list[str] = []
        for url in urls:
            platform = self.browser.resolve_platform(url, text)
            if platform is None:
                unrouted.append(url)
                continue
            tasks.append((platform, url))

        if unrouted and not tasks:
            self.download_view.focus_input()
            messagebox.showwarning(
                "链接不属于已支持的平台",
                "识别到了链接，但没有一条属于 Bilibili 或 抖音：\n\n"
                + "\n".join(item[:78] for item in unrouted[:3]),
                parent=self,
            )
            return None
        if unrouted:
            self._log(f"{len(unrouted)} 条链接不属于已支持平台，已跳过", "warn")

        if not self._confirm_platform(tasks):
            return None

        # B 站：勾选的链接按用户填的集数取分P；勾了但留空表示"全部"
        ranges = self.download_view.get_parts_ranges()
        bad: list[str] = []
        built: list[tuple] = []
        picked: list[str] = []
        for platform, url in tasks:
            options: dict = {}
            if platform.name == "bilibili" and url in ranges:
                parsed = parse_parts(ranges[url])
                if parsed is None:
                    bad.append(f"{url[:48]} → “{ranges[url]}”")
                    continue
                options = {"collect": True, "parts": parsed}
                picked.append(f"{url.rsplit('/video/', 1)[-1][:14]} → "
                              f"{ranges[url] or '全部'}")
            built.append((platform, url, options))

        if bad:
            self._status("集数范围有误", "warn")
            messagebox.showwarning(
                "集数范围无法解析",
                "下面这些链接的集数范围看不懂：\n\n"
                + "\n".join(bad[:4])
                + "\n\n可用写法：3-7 / 1,3,5 / 7-（留空表示全部）",
                parent=self,
            )
            return None

        # 把本次判定结果写进日志：改完之后到底按什么值在跑，一眼能看到
        if picked:
            self._log(f"按集数下载 {len(picked)} 条：" + "；".join(picked[:3]))

        # 合集拆成"一集一个任务"：每集在队列里独立一行、独立进度
        expanded: list[tuple] = []
        for platform, url, options in built:
            parts = options.get("parts") or []
            if options.get("collect") and parts:
                for number in parts:
                    expanded.append((platform, page_url(url, number),
                                     {"episode": number}))
            else:
                expanded.append((platform, url, options))
        return expanded

    def _confirm_platform(self, tasks: list[tuple]) -> bool:
        """链接平台与当前选择不一致时：只有一家就自动切，跨平台才问。"""
        current = self.browser.platform
        names = {platform.name for platform, _url in tasks}

        if names == {current.name}:
            return True

        # 全是同一个平台的（比如小红书分享短链 + 网页链接）：直接切，不打扰
        if len(names) == 1:
            target = next(platform for platform, _url in tasks)
            self._log(f"链接属于「{target.display_name}」，已自动切换平台")
            self.set_platform(target.name)
            return True

        others: dict[str, int] = {}
        for platform, _url in tasks:
            if platform is not current:
                others[platform.display_name] = (
                    others.get(platform.display_name, 0) + 1)
        detail = "、".join(f"{name} {count} 条" for name, count in others.items())
        return messagebox.askokcancel(
            "一次粘贴了多个平台",
            f"当前选择的是「{current.display_name}」，另外还有 {detail}。\n\n"
            "程序会按每条链接自己的平台下载，但浏览器只在当前平台完成登录，"
            "另一个平台可能取不到数据。需要的话分两批更稳。\n\n"
            "点「确定」继续，点「取消」返回修改。",
            parent=self,
        )

    def start_download(self) -> None:
        if self._state == "downloading" or self._worker_active:
            return

        tasks = self._collect_tasks()
        if not tasks:
            return

        # 任务已经定下来了，输入框立刻清空，方便继续粘下一批
        self.download_view.clear_input()
        self._stop.clear()

        if self._state == "ready" and self.browser.is_alive():
            self._begin_download(tasks, reset=True)
            return

        self._set_state("launching")
        self._status("正在启动浏览器", "accent")
        self._log(f"需要先在浏览器里登录 {self.browser.platform.display_name}，"
                  "登录完成后会自动开始下载")
        threading.Thread(target=self._login_then_download, args=(tasks,),
                         daemon=True).start()

    def enqueue_download(self) -> None:
        """下载中点了「加入队列」：清空输入，追加到当前批次之后。"""
        if not self._worker_active:
            self.start_download()
            return

        tasks = self._collect_tasks()
        if not tasks:
            return

        self.download_view.clear_input()
        self._begin_download(tasks, reset=False)

    def _begin_download(self, tasks: list, reset: bool = True) -> None:
        if reset or not self._queue:
            with self._queue_lock:
                self._queue = list(tasks)
            self.emit("queue", list(tasks))
            self.emit("stats", {"ok": 0, "fail": 0})
            self.emit("progress", 0.0)
        else:
            with self._queue_lock:
                self._queue.extend(tasks)
            self.emit("queue_append", tasks)

        with self._queue_lock:
            total = len(self._queue)
        self._set_state("downloading")
        self._status("准备下载", "accent")
        self._log(f"待下载 {total} 条")

        if not self._worker_active:
            self._worker_active = True
            threading.Thread(target=self._run_queue, daemon=True).start()

    def _report_parsing(self, text: str, urls: list[str]) -> None:
        counts = {}
        for url in urls:
            platform = self.browser.get_platform_for_url(url)
            name = platform.display_name if platform else "未知"
            counts[name] = counts.get(name, 0) + 1
        summary = " · ".join(f"{k} {v}" for k, v in counts.items())
        self._log(f"识别到 {len(urls)} 条链接（{summary}）", "info")

        lines = [line.strip() for line in re.split(r"[\n|]+", text)
                 if line.strip()]
        unknown = [line for line in lines
                   if not any(url in line or line in url for url in urls)]
        if unknown:
            preview = " / ".join(item[:32] for item in unknown[:3])
            self._log(f"另有 {len(unknown)} 行没有识别为链接：{preview}", "warn")

    def stop_download(self) -> None:
        if self._state in ("launching", "waiting_login"):
            self._stop.set()
            self._log("已取消登录：链接已保留，可再次点击「开始下载」", "warn")
            self._status("已取消", "neutral")
            self._set_state("idle")
            return
        if self._state != "downloading":
            return
        self._stop.set()
        self._log("已请求停止：当前这条结束后不再继续", "warn")
        self._status("正在停止", "warn")

    def _progress_reporter(self, index: int):
        def report(progress) -> None:
            self.emit("item_progress", {"index": index, "progress": progress})

        return report

    def _run_queue(self) -> None:
        """跑队列：每轮重新看长度，所以中途加入的任务会被接着执行。"""
        success = fail = 0
        errors: list[str] = []
        index = 0
        try:
            while True:
                with self._queue_lock:
                    if index >= len(self._queue):
                        break
                    platform, url, options = self._queue[index]
                    total = len(self._queue)

                if self._stop.is_set():
                    self.emit("item", {"index": index, "state": "skipped"})
                    index += 1
                    continue

                self.emit("item", {"index": index, "state": "running"})
                self._status(f"下载中 {index + 1}/{total}", "accent")
                self._log(f"[{index + 1}/{total}] {platform.display_name} · {url}")

                for plugin in self.plugins:
                    try:
                        plugin.on_download_start(url)
                    except Exception:  # noqa: BLE001
                        pass

                result = None
                tab = None
                started = time.monotonic()
                try:
                    # 每个任务一个干净标签页：避免上一条的 SPA 状态、HTTP 缓存
                    # 和监听残留串到这一条
                    tab = self.browser.new_tab()
                    headers = self.browser.headers(tab, url)
                    result = platform.download(
                        tab, url, headers, f"video_{index + 1}",
                        on_progress=self._progress_reporter(index),
                        on_log=self._log,
                        options=options,
                    )
                    success += 1
                    detail = result.describe()
                    if result.extra.get("quality"):
                        detail += f" · {result.extra['quality']}"
                    if result.extra.get("watermarked"):
                        detail += " · 含平台水印"
                    self.emit("item", {"index": index, "state": "success"})
                    self._log(
                        f"完成：{detail}（{time.monotonic() - started:.1f}s）",
                        "success")
                except Exception as exc:  # noqa: BLE001
                    fail += 1
                    errors.append(f"{url[:48]} → {exc}")
                    self.emit("item", {"index": index, "state": "failed",
                                       "note": str(exc)[:80]})
                    self._log(
                        f"失败：{exc}（{time.monotonic() - started:.1f}s）",
                        "error")
                finally:
                    if tab is not None:
                        try:
                            tab.close()
                        except Exception:  # noqa: BLE001
                            pass

                for plugin in self.plugins:
                    try:
                        plugin.on_download_complete(url, result, result is not None)
                    except Exception:  # noqa: BLE001
                        pass

                self.emit("stats", {"ok": success, "fail": fail})
                index += 1
                with self._queue_lock:
                    total = max(len(self._queue), 1)
                self.emit("progress", index / total)
        finally:
            self._worker_active = False
            with self._queue_lock:
                self._queue = []
            self._finish_batch(success, fail, errors)

    def _finish_batch(self, success: int, fail: int,
                      errors: list[str]) -> None:
        stopped = self._stop.is_set()
        summary = f"全部结束：成功 {success} · 失败 {fail}"
        self._log(summary + ("（已停止）" if stopped else ""),
                  "warn" if stopped else "info")

        if self.config.get("open_after_done") and success:
            self.open_download_dir()

        if self.browser.is_alive():
            self.browser.reset_tabs()
            self.browser.minimize()      # 下载完别把浏览器留在前台
            self._status("已登录", "success")
            self._set_state("ready")
        else:
            self._status("未连接", "neutral")
            self._set_state("idle")

        if fail and errors and not stopped:
            self.emit("dialog", {
                "title": "部分链接下载失败",
                "text": (f"共 {fail} 条失败：\n\n"
                         + "\n".join(errors[:4])
                         + "\n\n常见原因：平台选错、链接失效、登录态过期、"
                           "合集勾选与链接不匹配。"),
            })

    def _filter_plugins(self, urls: list[str]) -> list[str]:
        result: list[str] = []
        for url in urls:
            for plugin in self.plugins:
                try:
                    url = plugin.on_url_input(url)
                except Exception:  # noqa: BLE001
                    pass
                if not url:
                    break
            if url:
                result.append(url)
        return result

    # ------------------------------------------------------------------
    # 配置 / 插件 / 收尾
    # ------------------------------------------------------------------
    def open_download_dir(self) -> None:
        try:
            media.open_folder(app_config.download_dir())
        except OSError as exc:
            self._log(f"打开目录失败：{exc}", "error")

    def reload_config(self) -> None:
        self.config = app_config.load()
        self._log(f"设置已更新，下载目录：{app_config.download_dir()}", "success")

    def _load_plugins(self) -> None:
        from core.plugin_base import PluginBase

        try:
            import plugins as plugins_pkg
        except Exception as exc:  # noqa: BLE001
            self._log(f"插件目录不可用：{exc}", "warn")
            return

        for _finder, name, _ispkg in pkgutil.iter_modules(plugins_pkg.__path__):
            try:
                module = importlib.import_module(f"plugins.{name}")
            except Exception as exc:  # noqa: BLE001
                self._log(f"插件 {name} 导入失败：{exc}", "error")
                continue

            for attr in vars(module).values():
                if not isinstance(attr, type):
                    continue
                if attr is PluginBase or not issubclass(attr, PluginBase):
                    continue
                if getattr(attr, "__module__", "") != module.__name__:
                    continue
                try:
                    plugin = attr()
                    plugin.on_init(self.browser)
                except Exception as exc:  # noqa: BLE001
                    self._log(f"插件 {name} 初始化失败：{exc}", "error")
                    continue
                self.plugins.append(plugin)
                self._log(f"插件已加载：{plugin.name or attr.__name__}")

        if self.plugins:
            self.settings_view.set_plugins(self.plugins)

    def _on_close(self) -> None:
        self._closed = True
        self._stop.set()
        try:
            self.browser.quit()
        except Exception:  # noqa: BLE001
            pass
        for plugin in self.plugins:
            try:
                plugin.on_shutdown()
            except Exception:  # noqa: BLE001
                pass
        self.destroy()


_MODE_LABELS = {"light": "浅色", "dark": "深色", "system": "跟随系统"}
