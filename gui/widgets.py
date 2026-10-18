"""界面部件（v4）：双主题、卡片式列表、统一的按钮层级。"""

from __future__ import annotations

import time

import customtkinter as ctk

from gui.theme import COLORS, FAMILY, FONTS, RADIUS, resolve


class Card(ctk.CTkFrame):
    """白/深色卡片：1px 描边 + 大圆角。"""

    def __init__(self, master, **kwargs):
        kwargs.setdefault("fg_color", COLORS["surface"])
        kwargs.setdefault("corner_radius", RADIUS["card"])
        kwargs.setdefault("border_width", 1)
        kwargs.setdefault("border_color", COLORS["border"])
        super().__init__(master, **kwargs)


class SoftPanel(ctk.CTkFrame):
    """卡片内部的浅色分区。"""

    def __init__(self, master, **kwargs):
        kwargs.setdefault("fg_color", COLORS["surface_2"])
        kwargs.setdefault("corner_radius", RADIUS["inner"])
        super().__init__(master, **kwargs)


class Hairline(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        kwargs.setdefault("height", 1)
        kwargs.setdefault("fg_color", COLORS["hairline"])
        kwargs.setdefault("corner_radius", 0)
        super().__init__(master, **kwargs)


_TONES = {
    "neutral": ("surface_2", "text_dim"),
    "accent": ("accent_soft", "accent"),
    "success": ("success_soft", "success"),
    "error": ("error_soft", "error"),
    "warn": ("accent_soft", "warning"),
}


class StatusPill(ctk.CTkFrame):
    def __init__(self, master, text: str = "未连接", tone: str = "neutral"):
        super().__init__(master, fg_color=COLORS["surface_2"],
                         corner_radius=14, height=26)
        self._dot = ctk.CTkLabel(self, text="●", width=8,
                                 font=(FAMILY, 8),
                                 text_color=COLORS["text_faint"])
        self._dot.pack(side="left", padx=(10, 6))
        self._label = ctk.CTkLabel(self, text=text, font=FONTS["tiny"],
                                   text_color=COLORS["text_dim"])
        self._label.pack(side="left", padx=(0, 10))
        self.set(text, tone)

    def set(self, text: str, tone: str = "neutral") -> None:
        bg, fg = _TONES.get(tone, _TONES["neutral"])
        self.configure(fg_color=COLORS[bg])
        self._dot.configure(text_color=COLORS[fg])
        self._label.configure(text=text, text_color=COLORS[fg])


class Chip(ctk.CTkLabel):
    """平台小标签。"""

    def __init__(self, master, text: str, color_key: str):
        super().__init__(master, text=text, font=FONTS["tiny"],
                         fg_color=COLORS["surface_2"], corner_radius=7,
                         text_color=COLORS[color_key], width=58, height=22)


class Segmented(ctk.CTkFrame):
    """平台切换。"""

    def __init__(self, master, options: list[tuple[str, str]], command):
        super().__init__(master, fg_color=COLORS["surface_3"], corner_radius=10)
        self._command = command
        self._buttons: dict[str, ctk.CTkButton] = {}
        self._value = options[0][1] if options else ""

        for label, value in options:
            button = ctk.CTkButton(
                self, text=label, width=62, height=26, corner_radius=8,
                fg_color="transparent", hover_color=COLORS["surface_2"],
                text_color=COLORS["text_dim"],
                text_color_disabled=COLORS["text_faint"],
                font=FONTS["tiny"],
                command=lambda v=value: self.select(v),
            )
            button.pack(side="left", padx=2, pady=2)
            self._buttons[value] = button
        self._restyle()

    @property
    def value(self) -> str:
        return self._value

    def select(self, value: str, notify: bool = True) -> None:
        if value not in self._buttons:
            return
        self._value = value
        self._restyle()
        if notify and self._command:
            self._command(value)

    def set_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for button in self._buttons.values():
            button.configure(state=state)

    def _restyle(self) -> None:
        for value, button in self._buttons.items():
            active = value == self._value
            button.configure(
                fg_color=COLORS["surface"] if active else "transparent",
                text_color=COLORS["text"] if active else COLORS["text_dim"],
            )


class ThemeSwitch(ctk.CTkFrame):
    """浅色 / 深色 / 跟随系统。"""

    OPTIONS = (("light", "浅色"), ("dark", "深色"), ("system", "自动"))

    def __init__(self, master, command, width: int = 62):
        super().__init__(master, fg_color=COLORS["surface_2"], corner_radius=10)
        self._command = command
        self._buttons: dict[str, ctk.CTkButton] = {}
        for mode, label in self.OPTIONS:
            button = ctk.CTkButton(
                self, text=label, width=width, height=26, corner_radius=8,
                fg_color="transparent", hover_color=COLORS["surface_3"],
                text_color=COLORS["text_faint"], font=FONTS["tiny"],
                command=lambda m=mode: self._command(m),
            )
            button.pack(side="left", padx=2, pady=2)
            self._buttons[mode] = button
        self._value = "dark"

    def set_value(self, mode: str) -> None:
        self._value = mode if mode in self._buttons else "system"
        for name, button in self._buttons.items():
            active = name == self._value
            button.configure(
                fg_color=COLORS["surface"] if active else "transparent",
                text_color=COLORS["accent"] if active else COLORS["text_faint"],
            )


class NavItem(ctk.CTkButton):
    """侧边栏导航项。"""

    def __init__(self, master, label: str, icon: str, command):
        super().__init__(
            master, text=f"  {icon}   {label}", anchor="w", height=40,
            corner_radius=10, fg_color="transparent",
            hover_color=COLORS["surface_2"], text_color=COLORS["text_dim"],
            font=FONTS["body"], command=command,
        )

    def set_active(self, active: bool) -> None:
        self.configure(
            fg_color=COLORS["accent_soft"] if active else "transparent",
            text_color=COLORS["accent"] if active else COLORS["text_dim"],
        )


_STATE_TEXT = {
    "pending": ("等待", "text_faint"),
    "running": ("下载中", "accent"),
    "success": ("完成", "success"),
    "failed": ("失败", "error"),
    "skipped": ("已停止", "text_dim"),
}


class QueueRow(ctk.CTkFrame):
    """一条任务：卡片 + 内嵌进度线。"""

    def __init__(self, master, index: int, url: str, platform):
        super().__init__(master, fg_color=COLORS["surface"],
                         corner_radius=12, border_width=1,
                         border_color=COLORS["border"], height=64)
        self.pack_propagate(False)
        self._raw_url = url
        self._last = (0.0, 0)
        self._speed = 0.0

        head = ctk.CTkFrame(self, fg_color="transparent", height=36)
        head.pack(fill="x", padx=14, pady=(8, 0))
        head.pack_propagate(False)

        ctk.CTkLabel(head, text=f"{index:02d}", width=26,
                     font=FONTS["mono_sm"],
                     text_color=COLORS["text_faint"]).pack(side="left")

        Chip(head, platform.display_name,
             platform.name if platform.name in COLORS else "text_dim").pack(
            side="left", padx=(8, 12))

        self._state = ctk.CTkLabel(head, text="等待", width=104, anchor="e",
                                   font=FONTS["tiny"],
                                   text_color=COLORS["text_faint"])
        self._state.pack(side="right")

        self._url = ctk.CTkLabel(head, text=_shorten(url), anchor="w",
                                 font=FONTS["small"],
                                 text_color=COLORS["text_dim"])
        self._url.pack(side="left", fill="x", expand=True)

        self._bar = ctk.CTkProgressBar(
            self, height=3, corner_radius=2,
            fg_color=COLORS["surface_3"], progress_color=COLORS["accent"],
        )
        self._bar.pack(fill="x", padx=14, pady=(7, 8))
        self._bar.set(0)

    def set_state(self, state: str, note: str = "") -> None:
        text, color_key = _STATE_TEXT.get(state, _STATE_TEXT["pending"])
        self._state.configure(text=text, text_color=COLORS[color_key])
        self._last = (0.0, 0)
        self._speed = 0.0

        if state == "success":
            self._bar.configure(progress_color=COLORS["success"])
            self._bar.set(1)
        elif state == "failed":
            self._bar.configure(progress_color=COLORS["error"])
            self._bar.set(1)
        elif state == "running":
            self._bar.configure(progress_color=COLORS["accent"])
            self._bar.set(0)
        else:
            self._bar.configure(progress_color=COLORS["accent"])
            self._bar.set(0)

        if state == "failed":
            reason = (note or "下载失败").strip()
            self._url.configure(
                text=_shorten(f"{self._raw_url}   ·   {reason}", 82),
                text_color=COLORS["text_dim"])
            return

        self._url.configure(text=_shorten(self._raw_url))
        if state in ("success", "running"):
            self._url.configure(text_color=COLORS["text"])

    def set_progress(self, progress) -> None:
        if getattr(progress, "unit", "bytes") == "items":
            self._bar.set(progress.ratio)
            self._state.configure(text=f"{progress.done}/{progress.total} 张",
                                  text_color=COLORS["accent"])
            return

        self._bar.set(progress.ratio)

        now = time.monotonic()
        last_time, last_done = self._last
        if last_time and now - last_time > 0.15:
            instant = (progress.done - last_done) / (now - last_time)
            self._speed = instant if not self._speed else (
                self._speed * 0.6 + instant * 0.4)
        self._last = (now, progress.done)

        if progress.total:
            text = f"{progress.ratio * 100:.0f}%"
        else:
            text = f"{progress.done / 1048576:.0f}MB"
        if self._speed > 0:
            text += f" · {self._speed / 1048576:.1f}MB/s"
        self._state.configure(text=text, text_color=COLORS["accent"])


class EmptyState(ctk.CTkFrame):
    """队列为空时的占位。"""

    def __init__(self, master, title: str, hint: str):
        super().__init__(master, fg_color=COLORS["surface"],
                         corner_radius=RADIUS["card"], border_width=1,
                         border_color=COLORS["border"])
        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(expand=True, pady=34)

        badge = ctk.CTkFrame(inner, width=46, height=46, corner_radius=23,
                             fg_color=COLORS["surface_2"])
        badge.pack()
        badge.pack_propagate(False)
        ctk.CTkLabel(badge, text="↓", font=(FAMILY, 18),
                     text_color=COLORS["text_faint"]).place(
            relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(inner, text=title, font=FONTS["body_bold"],
                     text_color=COLORS["text_dim"]).pack(pady=(12, 3))
        ctk.CTkLabel(inner, text=hint, font=FONTS["tiny"],
                     text_color=COLORS["text_faint"]).pack()


class ScrollArea(ctk.CTkScrollableFrame):
    def __init__(self, master, **kwargs):
        kwargs.setdefault("fg_color", "transparent")
        kwargs.setdefault("corner_radius", 0)
        kwargs.setdefault("scrollbar_fg_color", "transparent")
        kwargs.setdefault("scrollbar_button_color", COLORS["surface_3"])
        super().__init__(master, **kwargs)
        try:
            self._scrollbar.grid_remove()
        except Exception:  # noqa: BLE001
            pass


def _shorten(text: str, limit: int = 72) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def primary_button(master, text: str, command, width: int = 118) -> ctk.CTkButton:
    return ctk.CTkButton(
        master, text=text, width=width, height=40, corner_radius=10,
        fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
        text_color=COLORS["on_accent"], text_color_disabled=COLORS["on_accent"],
        font=FONTS["body_bold"], command=command,
    )


def ghost_button(master, text: str, command, width: int = 64) -> ctk.CTkButton:
    return ctk.CTkButton(
        master, text=text, width=width, height=32, corner_radius=9,
        fg_color="transparent", hover_color=COLORS["surface_2"],
        border_width=1, border_color=COLORS["border"],
        text_color=COLORS["text_dim"], font=FONTS["small"],
        command=command,
    )


def text_button(master, text: str, command, width: int = 52) -> ctk.CTkButton:
    return ctk.CTkButton(
        master, text=text, width=width, height=28, corner_radius=8,
        fg_color="transparent", hover_color=COLORS["surface_2"],
        text_color=COLORS["text_dim"], font=FONTS["tiny"],
        command=command,
    )


def wrap_to_width(label: ctk.CTkLabel, padding: int = 8) -> None:
    def _resize(event) -> None:
        width = max(240, event.width - padding)
        if getattr(label, "_wrap_width", None) != width:
            label._wrap_width = width
            label.configure(wraplength=width)

    label.bind("<Configure>", _resize)
