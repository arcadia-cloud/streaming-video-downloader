"""插件基类。

生命周期（现已全部真正接入主程序）：
    on_init(browser)                      启动时
    on_url_input(url) -> url              解析到链接后，逐条过滤
    on_download_start(url)                单条开始
    on_download_complete(result, ok)      单条结束
    get_settings_widget(parent)           设置页追加控件（可选）
    on_shutdown()                         退出
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from core.models import DownloadResult

if TYPE_CHECKING:
    from core.browser import BrowserManager


class PluginBase(ABC):
    name: str = ""
    description: str = ""
    author: str = ""
    version: str = "1.0"

    @abstractmethod
    def on_init(self, browser: "BrowserManager"):
        """初始化时调用，传入 BrowserManager 实例。"""
        ...

    def on_url_input(self, url: str) -> str:
        """返回处理后的 URL；返回空串表示丢弃这条链接。"""
        return url

    def on_download_start(self, url: str) -> None:
        ...

    def on_download_complete(self, url: str, result: DownloadResult | None,
                             success: bool) -> None:
        ...

    def get_settings_widget(self, parent):
        """返回要追加到设置页的控件，无则返回 None。"""
        return None

    def on_shutdown(self) -> None:
        ...
