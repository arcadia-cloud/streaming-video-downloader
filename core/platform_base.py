"""平台基类：新增平台只需继承它并实现 4 个方法。

与原实现相比：
- URL 识别从"子串包含域名"改为按 hostname 后缀匹配，避免误路由；
- parse_urls 收敛成基类的通用实现，不再要求每个平台重复抄一遍；
- download() 返回 DownloadResult，GUI / 插件拿到的路径一定是真实路径。
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from core import urls as url_tools
from core.models import DownloadResult

if TYPE_CHECKING:
    from DrissionPage import ChromiumPage

_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


class PlatformBase(ABC):
    """平台基类。子类需要实现 login_url / is_logged_in / get_video_name / download。"""

    name: str = ""
    display_name: str = ""
    url_prefix: str = ""
    sub_folder: str = ""
    host_suffixes: tuple[str, ...] = ()
    accent: str = "#8AB4F8"          # 界面里给平台标签用的颜色

    # --- 路由 ---------------------------------------------------------
    def match_url(self, url: str) -> bool:
        host = _hostname(url_tools.normalize(url))
        if not host:
            return False
        return any(host == s or host.endswith("." + s) for s in self.host_suffixes)

    def normalize_url(self, url: str) -> str:
        return url_tools.normalize(url)

    def parse_urls(self, text: str) -> list[str]:
        """按出现顺序提取属于本平台的链接并去重。"""
        seen: set[str] = set()
        result: list[str] = []
        for candidate in url_tools.iter_candidates(text):
            if not self.match_url(candidate):
                continue
            full = self.normalize_url(candidate)
            if full not in seen:
                seen.add(full)
                result.append(full)
        return result

    # --- 登录 / 元信息 ------------------------------------------------
    @abstractmethod
    def login_url(self) -> str:
        ...

    def click_login(self, page) -> bool:
        """需要点一下才弹出登录框时覆盖此方法。"""
        return False

    @abstractmethod
    def is_logged_in(self, page: "ChromiumPage") -> bool:
        ...

    @abstractmethod
    def get_video_name(self, tab) -> str | None:
        ...

    @abstractmethod
    def download(self, tab, url: str, headers: dict,
                 fallback_name: str, on_progress=None,
                 on_log=None, options: dict | None = None) -> DownloadResult:
        """执行下载，返回下载结果。

        on_progress 接收 core.models.Progress，用于界面显示百分比/速度。
        on_log(message, level="info") 接收诊断信息，用于把"断在哪一步"
        暴露到界面日志；不传时应完全静默。
        options 是平台特有开关（例如 Bilibili 的 {"collect": True}）。
        """
        ...

    # --- 通用工具 -----------------------------------------------------
    def folder(self) -> Path:
        from core.config import download_dir

        base = download_dir()
        # 用户把目录直接选成了 bili_video 时，不要再套一层 bili_video
        if base.name == self.sub_folder:
            return base
        return base / self.sub_folder

    @staticmethod
    def sanitize_filename(name: str | None, max_length: int = 90) -> str:
        """清洗成 Windows 可用的文件名。"""
        text = (name or "").strip()
        text = _ILLEGAL.sub("_", text)
        text = re.sub(r"\s+", " ", text).strip(" .")
        if not text:
            return "untitled"

        stem = text.split(".")[0].upper()
        if stem in _WINDOWS_RESERVED:
            text = "_" + text

        if len(text) > max_length:
            text = text[:max_length].rstrip(" .")
        return text or "untitled"


def _hostname(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def find_ele(tab, *selectors: str, timeout: float = 2):
    """依次尝试多个定位器，返回第一个命中的元素（失败返回 None）。"""
    for selector in selectors:
        try:
            element = tab.ele(selector, timeout=timeout)
        except Exception:  # noqa: BLE001 - 页面结构变化时不要炸穿下载流程
            element = None
        if element:
            return element
    return None


def find_eles(tab, *selectors: str, timeout: float = 2) -> list:
    for selector in selectors:
        try:
            elements = tab.eles(selector, timeout=timeout)
        except Exception:  # noqa: BLE001
            elements = None
        if elements:
            return list(elements)
    return []


def make_logger(on_log):
    """把 on_log 归一成 emit(message, level)，兼容只收一个参数的回调。"""
    if on_log is None:
        return lambda *_args, **_kwargs: None

    def emit(message: str, level: str = "info") -> None:
        try:
            on_log(message, level)
        except TypeError:
            try:
                on_log(message)
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001 - 日志不能影响下载
            pass

    return emit

