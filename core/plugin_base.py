from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.browser import BrowserManager


class PluginBase(ABC):
    """插件基类，新功能继承此类即可接入主程序。"""

    name: str = ""
    description: str = ""
    author: str = ""
    version: str = "1.0"

    @abstractmethod
    def on_init(self, browser: "BrowserManager"):
        """初始化时调用，传入 BrowserManager 实例。"""
        pass

    def on_url_input(self, url: str) -> str:
        """URL 输入时拦截处理，返回处理后的 URL。"""
        return url

    def on_download_start(self, url: str):
        """下载开始时调用。"""
        pass

    def on_download_complete(self, url: str, video_path: str, success: bool):
        """下载完成时调用。"""
        pass

    def get_settings_widget(self, parent):
        """返回设置页面的自定义控件，无则返回 None。"""
        return None

    def on_shutdown(self):
        """程序退出时调用，用于清理资源。"""
        pass
