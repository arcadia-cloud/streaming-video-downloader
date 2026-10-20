"""下载页（v4）：输入卡片 + 任务卡片列表 + 底部进度。"""

from __future__ import annotations

from datetime import datetime
import tkinter as tk

import customtkinter as ctk

from core.platforms import PLATFORMS
from gui.theme import COLORS, FAMILY, FONTS, RADIUS, resolve
from gui.widgets import (Card, EmptyState, QueueRow, Segmented, primary_button,
                         text_button)

PLACEHOLDER_DEFAULT = "粘贴视频链接，每行一条；多条可以换行或空格分开"
PLACEHOLDER_BY_PLATFORM = {
    "bilibili": "粘贴 Bilibili 链接；合集可勾选并填 3-7 / 1,3,5 选择要下的分P",
    "douyin": "粘贴抖音链接，每行一条；也可以直接粘分享文案",
    "xiaohongshu": "粘贴小红书笔记链接，每行一条；图文会按页面张数逐张下载",
}


class DownloadView(ctk.CTkFrame):
    PAGE_TITLE = "下载"
    PAGE_SUBTITLE = "粘贴链接，批量下载 Bilibili / 抖音 / 小红书 的内容"

    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.rows: list[QueueRow] = []
        self._state = "idle"
        self._placeholder_on = False
        self._placeholder_text = ""
        self._input_enabled = False
        self._log_visible = False
        self._platform_name = PLATFORMS[0].name if PLATFORMS else ""
        self._parts_signature: tuple[str, ...] = ()
        self._parts_checked: set[str] = set()
        self._parts_ranges: dict[str, str] = {}
        self._parts_rows: dict[str, tuple] = {}
        self._parts_urls: list[str] = []
        self._parts_timer = None

        self._build_footer()
        self._build_composer()
        self._build_queue()
        self.set_state("idle")

    # ------------------------------------------------------------------
    # 布局
    # ------------------------------------------------------------------
    def _build_composer(self):
        card = Card(self)
        card.pack(fill="x")
        self.composer = card

        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", padx=16, pady=14)

        head = ctk.CTkFrame(body, fg_color="transparent")
        head.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(head, text="视频链接", font=FONTS["small"],
                     text_color=COLORS["text_dim"]).pack(side="left")
        ctk.CTkLabel(head, text="支持分享文案 · 自动去重",
                     font=FONTS["tiny"],
                     text_color=COLORS["text_faint"]).pack(side="right")

        self.textbox = ctk.CTkTextbox(
            body, height=96, corner_radius=RADIUS["inner"], border_width=0,
            fg_color=COLORS["surface_2"], text_color=COLORS["text"],
            font=FONTS["body"], wrap="word",
            scrollbar_button_color=COLORS["surface_3"],
        )
        self.textbox.pack(fill="x")
        self.textbox.bind("<FocusIn>", self._on_focus_in)
        self.textbox.bind("<FocusOut>", self._on_focus_out)
        self.textbox.bind("<Key>", self._on_key)
        self.textbox.bind("<<Paste>>", self._on_paste)
        self.textbox.bind("<KeyRelease>", lambda _e: self._update_counter())
        # 登录说明：顺序是"先粘贴、后登录"，用户必须先知道这一步
        ctk.CTkLabel(
            body,
            text=("需要登录：点「开始下载」后会打开浏览器，完成登录即自动开始；"
                  "链接会保留，可反复重试。"),
            font=FONTS["tiny"], text_color=COLORS["text_dim"],
            justify="left", anchor="w", wraplength=620,
        ).pack(fill="x", pady=(8, 0))
        ctk.CTkLabel(
            body, text="仅供个人学习使用，请遵守各平台用户协议并尊重版权。",
            font=FONTS["tiny"], text_color=COLORS["text_faint"],
            justify="left", anchor="w",
        ).pack(fill="x", pady=(2, 0))

        # 合集 / 分P：先由总开关决定"要不要按集数"，勾了才展开明细
        self.parts_frame = ctk.CTkFrame(body, fg_color="transparent")
        self.parts_toggle = ctk.CTkCheckBox(
            self.parts_frame,
            text="这些链接是合集 / 分P，我要按集数下载（仅 Bilibili）",
            font=FONTS["tiny"], text_color=COLORS["text_dim"],
            fg_color=COLORS["accent"], checkbox_width=16, checkbox_height=16,
            command=self._on_parts_master,
        )
        self.parts_toggle.pack(anchor="w")
        self.parts_hint = ctk.CTkLabel(
            self.parts_frame,
            text="勾选后选哪几条链接要选集，再填集数：18-20 / 1,3,5 / 7-；"
                 "留空表示该合集全部。不勾这里的链接只下当前这一集。",
            font=FONTS["tiny"], text_color=COLORS["text_faint"],
            justify="left", anchor="w", wraplength=580,
        )
        self.parts_hint.pack(anchor="w", pady=(2, 0))

        self.parts_body = ctk.CTkFrame(self.parts_frame,
                                       fg_color="transparent")
        self.parts_host = ctk.CTkScrollableFrame(
            self.parts_body, height=96, fg_color=COLORS["surface_2"],
            corner_radius=RADIUS["inner"],
            scrollbar_button_color=COLORS["surface_3"],
        )
        self.parts_host.pack(fill="x")

        bottom = ctk.CTkFrame(body, fg_color="transparent")
        bottom.pack(fill="x", pady=(12, 0))

        self.platform_seg = Segmented(
            bottom,
            [(p.display_name, p.name) for p in PLATFORMS],
            self._on_platform_change,
        )
        self.platform_seg.pack(side="left")

        ctk.CTkLabel(
            bottom, text="换行 / 空格 / 连写均可",
            font=FONTS["tiny"], text_color=COLORS["text_faint"],
        ).pack(side="left", padx=(12, 0))

        self.action_btn = primary_button(bottom, "开始下载", self._on_action)
        self.action_btn.pack(side="right")

        self.clear_btn = text_button(bottom, "清空", self._on_clear, 48)
        self.clear_btn.pack(side="right", padx=(0, 4))

        self.counter = ctk.CTkLabel(bottom, text="", font=FONTS["tiny"],
                                    text_color=COLORS["text_faint"])
        self.counter.pack(side="right", padx=(0, 10))

        self._show_placeholder()

    def _build_queue(self):
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", pady=(20, 10))

        self.section_title = ctk.CTkLabel(bar, text="队列",
                                          font=FONTS["body_bold"],
                                          text_color=COLORS["text"])
        self.section_title.pack(side="left")
        self.meta = ctk.CTkLabel(bar, text="共 0 条", font=FONTS["tiny"],
                                 text_color=COLORS["text_faint"])
        self.meta.pack(side="left", padx=(10, 0))

        self.log_tab = text_button(bar, "日志", lambda: self.toggle_log(), 44)
        self.log_tab.pack(side="right")
        self.list_tab = text_button(bar, "列表", lambda: self.toggle_log(False), 44)
        self.list_tab.pack(side="right", padx=(0, 2))
        self._sync_tabs()

        self.list_host = ctk.CTkFrame(self, fg_color="transparent")
        self.list_host.pack(fill="both", expand=True)

        self.scroll = ctk.CTkScrollableFrame(
            self.list_host, height=120, fg_color="transparent", corner_radius=0,
            scrollbar_fg_color="transparent",
            scrollbar_button_color=COLORS["surface_3"],
        )
        self.scroll.pack(fill="both", expand=True)

        self.empty = EmptyState(self.scroll, "队列是空的",
                                "在上方粘贴链接后点击「开始下载」")
        self.empty.pack(fill="x", pady=(6, 0))

        self.log_box = ctk.CTkTextbox(
            self.list_host, corner_radius=RADIUS["inner"], border_width=0,
            fg_color=COLORS["surface_2"], font=FONTS["mono"],
            text_color=COLORS["text_dim"],
            scrollbar_button_color=COLORS["surface_3"],
        )
        self.log_box.configure(state="disabled")
        self._sync_empty()

    def _build_footer(self):
        self.footer = ctk.CTkFrame(self, fg_color="transparent")
        self.footer.pack(side="bottom", fill="x", pady=(14, 0))

        self.progress = ctk.CTkProgressBar(
            self.footer, height=4, corner_radius=2,
            progress_color=COLORS["accent"], fg_color=COLORS["surface_3"],
        )
        self.progress.pack(fill="x")
        self.progress.set(0)

        row = ctk.CTkFrame(self.footer, fg_color="transparent")
        row.pack(fill="x", pady=(10, 0))

        self.stats = ctk.CTkLabel(row, text="成功 0  ·  失败 0",
                                  font=FONTS["tiny"],
                                  text_color=COLORS["text_faint"])
        self.stats.pack(side="left")

        ctk.CTkLabel(row, text="Ctrl+Enter 开始 · Esc 停止",
                     font=FONTS["tiny"],
                     text_color=COLORS["text_faint"]).pack(side="left",
                                                           padx=(16, 0))

        self.stop_btn = ctk.CTkButton(
            row, text="停止", width=60, height=28, corner_radius=8,
            fg_color="transparent", hover_color=COLORS["error_soft"],
            text_color=COLORS["error"], font=FONTS["tiny"],
            command=self._on_stop, state="disabled",
        )
        self.stop_btn.pack(side="right")

    # ------------------------------------------------------------------
    # 状态
    # ------------------------------------------------------------------
    def set_state(self, state: str) -> None:
        self._state = state
        if state == "idle":
            # 先粘贴、再登录：输入框从一开始就可编辑
            self._set_action("开始下载", True)
            self._set_input_enabled(True)
            self.platform_seg.set_enabled(True)
            self.stop_btn.configure(state="disabled")
        elif state == "launching":
            self._set_action("正在启动…", False)
            self._set_input_enabled(False)
            self.platform_seg.set_enabled(False)
            self.stop_btn.configure(state="normal")
        elif state == "waiting_login":
            self._set_action("等待登录…", False)
            self._set_input_enabled(False)
            self.platform_seg.set_enabled(False)
            self.stop_btn.configure(state="normal")
        elif state == "ready":
            self._set_action("开始下载", True)
            self._set_input_enabled(True)
            self.platform_seg.set_enabled(True)
            self.stop_btn.configure(state="disabled")
        elif state == "downloading":
            # 允许边下边粘下一批：按钮会在有内容时变成「加入队列」
            self._set_input_enabled(True)
            self.platform_seg.set_enabled(False)
            self.stop_btn.configure(state="normal")
            self._sync_action()

        # 启动/登录/下载期间禁用「清空」，避免误清掉正在排队的链接
        self.clear_btn.configure(
            state="normal" if state in ("idle", "ready") else "disabled")

    def refresh_theme(self) -> None:
        """Tk 原生文本标签不吃元组颜色，换肤后手动刷一遍。"""
        for level, key in (("info", "text_dim"), ("success", "success"),
                           ("error", "error"), ("warn", "warning")):
            self.log_box.tag_config(level, foreground=resolve(COLORS[key]))
        if self._placeholder_on:
            self.textbox.tag_config("placeholder",
                                    foreground=resolve(COLORS["text_faint"]))

    def _set_action(self, text: str, enabled: bool) -> None:
        self.action_btn.configure(
            text=text, state="normal" if enabled else "disabled")

    def _sync_action(self) -> None:
        """下载中：有内容就允许「加入队列」，没有就显示进度文案。"""
        if self._state != "downloading":
            return
        has_text = not self._is_empty()
        self._set_action("加入队列" if has_text else "下载中…", has_text)

    def _set_input_enabled(self, enabled: bool) -> None:
        self._input_enabled = enabled
        self.textbox.configure(state="normal" if enabled else "disabled")
        if enabled and self._is_empty():
            self._show_placeholder()

    # ------------------------------------------------------------------
    # 队列 / 日志
    # ------------------------------------------------------------------
    def set_queue(self, tasks: list) -> None:
        if self._log_visible:
            self.toggle_log(False)

        for row in self.rows:
            row.destroy()
        self.rows.clear()
        self.empty.pack_forget()

        for index, (platform, url, *rest) in enumerate(tasks, 1):
            row = QueueRow(self.scroll, index, _task_label(url, rest), platform)
            row.pack(fill="x", pady=(0, 8))
            self.rows.append(row)

        if not tasks:
            self.empty.pack(fill="x", pady=(6, 0))
            self.meta.configure(text="共 0 条")
        else:
            self._sync_meta()
        self._sync_empty()

    def append_queue(self, tasks: list) -> None:
        """新一批任务接在现有列表后面，索引继续往下排。"""
        if self._log_visible:
            self.toggle_log(False)
        base = len(self.rows)
        for offset, (platform, url, *rest) in enumerate(tasks, 1):
            row = QueueRow(self.scroll, base + offset, _task_label(url, rest),
                           platform)
            row.pack(fill="x", pady=(0, 8))
            self.rows.append(row)
        self.empty.pack_forget()
        self._sync_meta()
        self._sync_empty()

    def clear_input(self) -> None:
        """清空输入框并回到占位状态，但保持可编辑。"""
        self.textbox.delete("1.0", "end")
        self._placeholder_on = False
        self._show_placeholder()
        if not self._input_enabled:
            self.textbox.configure(state="disabled")

    def update_item(self, index: int, state: str, note: str = "") -> None:
        if 0 <= index < len(self.rows):
            self.rows[index].set_state(state, note)

    def update_item_progress(self, index: int, progress) -> None:
        if 0 <= index < len(self.rows):
            self.rows[index].set_progress(progress)

    def set_stats(self, success: int, fail: int) -> None:
        self.stats.configure(text=f"成功 {success}  ·  失败 {fail}")

    def set_progress(self, value: float) -> None:
        self.progress.set(max(0.0, min(1.0, value)))

    def toggle_log(self, show: bool | None = None) -> None:
        show = (not self._log_visible) if show is None else show
        if show == self._log_visible:
            return
        self._log_visible = show

        if show:
            self.scroll.pack_forget()
            self.log_box.pack(fill="both", expand=True)
            self.section_title.configure(text="运行日志")
        else:
            self.log_box.pack_forget()
            self.scroll.pack(fill="both", expand=True)
            self.section_title.configure(text="队列")
        self._sync_tabs()
        self._sync_meta()
        self._sync_empty()

    def _sync_tabs(self) -> None:
        self.log_tab.configure(
            text_color=COLORS["accent"] if self._log_visible
            else COLORS["text_faint"])
        self.list_tab.configure(
            text_color=COLORS["text_faint"] if self._log_visible
            else COLORS["accent"])

    def _sync_meta(self) -> None:
        if self._log_visible:
            self.meta.configure(text="最近 500 行")
        else:
            self.meta.configure(text=f"共 {len(self.rows)} 条")

    def _sync_empty(self) -> None:
        try:
            bar = self.scroll._scrollbar
            if len(self.rows) > 5:
                bar.grid()
            else:
                bar.grid_remove()
        except Exception:  # noqa: BLE001
            pass

    def append_log(self, message: str, level: str = "info") -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"{stamp}   {message}\n", level)
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

        try:
            lines = int(self.log_box.index("end-1c").split(".")[0])
            if lines > 500:
                self.log_box.configure(state="normal")
                self.log_box.delete("1.0", "120.0")
                self.log_box.configure(state="disabled")
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # 输入
    # ------------------------------------------------------------------
    def _show_placeholder(self) -> None:
        self.textbox.configure(state="normal")
        self.textbox.delete("1.0", "end")
        hint = PLACEHOLDER_BY_PLATFORM.get(self._platform_name,
                                           PLACEHOLDER_DEFAULT)
        self.textbox.insert("1.0", hint, "placeholder")
        self.textbox.tag_config("placeholder",
                                foreground=resolve(COLORS["text_faint"]))
        self._placeholder_on = True
        self._placeholder_text = hint
        self._update_counter()

    def _on_focus_in(self, _event=None) -> None:
        self._clear_placeholder()
        self._update_counter()          # 拿到焦点就按当前内容重算一次
        self._update_counter()

    def _on_key(self, event):
        """占位提示在第一次真正输入时消失，而不是只能靠点击焦点。"""
        if self._placeholder_on:
            if event.char and event.char.isprintable():
                self._clear_placeholder()
            elif event.keysym in ("BackSpace", "Delete"):
                return "break"      # 占位文本不该被退格吃掉
        self._update_counter()
        return None

    def _on_paste(self, _event=None) -> None:
        if self._placeholder_on:
            self._clear_placeholder()
        self.after_idle(self._update_counter)

    def _clear_placeholder(self) -> None:
        if not self._placeholder_on:
            return
        self.textbox.delete("1.0", "end")
        self._placeholder_on = False
        self.textbox.configure(text_color=COLORS["text"])

    def _on_focus_out(self, _event=None) -> None:
        if self._input_enabled and self._is_empty():
            self._show_placeholder()

    def _is_empty(self) -> bool:
        return not self._real_text()

    def _real_text(self) -> str:
        """读输入框真实内容，并把"占位状态"与内容对齐。

        占位标记一旦和控件内容脱节（例如消息框抢焦点、Ctrl+A 删除后重贴），
        旧逻辑会让 `get_text()` 永远返回空串——用户明明贴了链接，程序却说没有。
        这里以控件内容为准自愈。
        """
        raw = self.textbox.get("1.0", "end-1c")
        text = raw.strip()
        if self._placeholder_on:
            if not text or text == (self._placeholder_text or "").strip():
                return ""
            self._placeholder_on = False          # 有真实内容：退出占位状态
            self.textbox.configure(text_color=COLORS["text"])
        return text

    def get_text(self) -> str:
        return self._real_text()

    def focus_input(self) -> None:
        """把光标还给输入框（弹过提示框之后用）。"""
        try:
            self.textbox.focus_set()
        except Exception:  # noqa: BLE001
            pass

    def _update_counter(self) -> None:
        text = self._real_text()
        urls = self.app.browser.parse_urls(text) if text else []
        self.counter.configure(
            text=f"{len(urls)} 条" if urls else "",
            text_color=COLORS["accent"] if urls else COLORS["text_faint"],
        )
        self._schedule_parts(urls)
        self._sync_action()

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------
    def trigger_action(self) -> None:
        self._on_action()

    def _on_action(self) -> None:
        # 一个按钮走完全程：未登录自动开浏览器；下载中则加入队列
        if self._state == "downloading":
            if not self._is_empty():
                self.app.enqueue_download()
            return
        if self._state in ("idle", "ready"):
            self.app.start_download()

    def _on_clear(self) -> None:
        self.textbox.configure(state="normal")
        self.textbox.delete("1.0", "end")
        self._placeholder_on = False
        self._show_placeholder()
        if not self._input_enabled:
            self.textbox.configure(state="disabled")

    def _on_stop(self) -> None:
        self.app.stop_download()
        self.stop_btn.configure(state="disabled")

    def _on_platform_change(self, name: str) -> None:
        self._platform_name = name
        if self._placeholder_on:
            self._show_placeholder()        # 提示词要跟着平台换
        text = "" if self._placeholder_on else self.textbox.get("1.0", "end-1c")
        urls = self.app.browser.parse_urls(text) if text.strip() else []
        self.refresh_parts(urls, force=True)
        self.app.set_platform(name)

    # ------------------------------------------------------------------
    # 合集 / 分P
    # ------------------------------------------------------------------
    def flush_parts(self) -> None:
        """取消待执行的防抖重建，立刻按当前输入重建一次。

        每次点击「开始下载 / 加入队列」前都要调它：否则用户刚改完链接就点击，
        350ms 的防抖还没跑，拿到的还是上一轮的链接行。
        """
        if self._parts_timer is not None:
            try:
                self.after_cancel(self._parts_timer)
            except Exception:  # noqa: BLE001
                pass
            self._parts_timer = None

        text = self._real_text()
        urls = self.app.browser.parse_urls(text) if text.strip() else []
        self.refresh_parts(urls)

    def _schedule_parts(self, urls: list[str]) -> None:
        """输入停顿 350ms 再重建，避免每敲一个字符就重排控件。"""
        if self._parts_timer is not None:
            try:
                self.after_cancel(self._parts_timer)
            except Exception:  # noqa: BLE001
                pass
        self._parts_timer = self.after(350, lambda: self.refresh_parts(urls))

    def refresh_parts(self, urls: list[str], force: bool = False) -> None:
        self._parts_timer = None
        if self._platform_name != "bilibili":
            urls = []
        signature = tuple(urls)
        if signature == self._parts_signature and not force:
            return
        self._parts_signature = signature
        self._parts_urls = list(urls)

        # 重建前先把已填的范围读进缓存，避免输入内容丢失
        for url, (_var, entry) in self._parts_rows.items():
            self._parts_ranges[url] = entry.get().strip()
        self._parts_rows.clear()
        for child in self.parts_host.winfo_children():
            child.destroy()
        self._parts_checked &= set(urls)

        if not urls:
            self.parts_frame.pack_forget()
            return

        self.parts_frame.pack(fill="x", pady=(10, 0))
        if not self.parts_toggle.get():
            self.parts_body.pack_forget()       # 没开总开关就不展开明细
            return

        if not self._parts_checked:
            self._parts_checked.add(urls[0])    # 默认第一条

        for index, url in enumerate(urls, 1):
            row = ctk.CTkFrame(self.parts_host, fg_color="transparent")
            row.pack(fill="x", padx=6, pady=2)

            var = tk.BooleanVar(value=url in self._parts_checked)
            ctk.CTkCheckBox(
                row, text="按集数", variable=var, width=64,
                font=FONTS["tiny"], text_color=COLORS["text_dim"],
                fg_color=COLORS["accent"], checkbox_width=16,
                checkbox_height=16,
                command=lambda u=url: self._on_part_toggle(u),
            ).pack(side="left")
            ctk.CTkLabel(
                row, text=f"{index}. {_shorten_url(url, 40)}",
                font=FONTS["tiny"], text_color=COLORS["text_faint"],
            ).pack(side="left", padx=(6, 0))

            entry = ctk.CTkEntry(
                row, width=92, height=24, font=FONTS["tiny"],
                fg_color=COLORS["surface_3"], border_width=0,
                placeholder_text="18-20", text_color=COLORS["text"],
            )
            entry.pack(side="right")
            entry.insert(0, self._parts_ranges.get(url, ""))
            entry.configure(state="normal" if var.get() else "disabled")
            self._parts_rows[url] = (var, entry)

        self.parts_body.pack(fill="x", pady=(6, 0))

    def _on_parts_master(self) -> None:
        if not self.parts_toggle.get():
            self.parts_body.pack_forget()
            return

        if not self._parts_rows and self._parts_urls:
            # 明细还没建过（开关此前是关的），这里补建一次
            self.refresh_parts(self._parts_urls, force=True)
        elif not self._parts_checked and self._parts_rows:
            first = next(iter(self._parts_rows))
            var, _entry = self._parts_rows[first]
            var.set(True)
            self._on_part_toggle(first)

        self.parts_body.pack(fill="x", pady=(6, 0))

    def _on_part_toggle(self, url: str) -> None:
        row = self._parts_rows.get(url)
        if row is None:
            return
        var, entry = row
        if var.get():
            self._parts_checked.add(url)
            entry.configure(state="normal")
        else:
            self._parts_checked.discard(url)
            self._parts_ranges[url] = entry.get().strip()
            entry.configure(state="disabled")

    def get_parts_ranges(self) -> dict[str, str]:
        """勾选的链接 -> 用户填的集数范围（空串表示该合集全部）。"""
        if self._platform_name != "bilibili":
            return {}
        if not self.parts_toggle.get():     # 总开关没开就一律按单集下
            return {}
        ranges: dict[str, str] = {}
        for url, (var, entry) in self._parts_rows.items():
            if var.get():
                ranges[url] = entry.get().strip()
        return ranges


def _task_label(url: str, rest: list) -> str:
    """合集拆出来的单集任务，把 P 号放最前面，缩略后也不会被截掉。"""
    options = rest[0] if rest else {}
    episode = options.get("episode") if isinstance(options, dict) else None
    return f"P{episode} · {url}" if episode is not None else url


def _shorten_url(url: str, limit: int = 56) -> str:
    """检查项里只显示去协议头、限定长度的链接。"""
    text = (url or "").split("://", 1)[-1]
    return text if len(text) <= limit else text[:limit - 1] + "…"
