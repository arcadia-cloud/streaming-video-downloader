from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from DrissionPage import ChromiumPage


class PlatformBase(ABC):
    """平台基类。每个平台（Bilibili / 抖音 / 小红书）继承此类。

    子类需要实现：
    - match_url: 判断 URL 是否属于该平台（支持简化链接）
    - normalize_url: 将简化链接补全为完整 URL
    - parse_urls: 从用户输入中提取该平台的合法链接
    - login_url: 登录页 URL
    - is_logged_in: 检测是否已登录
    - get_video_name: 从标签页提取视频标题
    - download: 执行下载逻辑

    在 core/platforms/ 下新建文件并继承本类即可，
    主程序通过 match_url 自动路由，无需修改其他代码。
    """

    name: str = ""
    display_name: str = ""
    url_prefix: str = ""
    sub_folder: str = ""

    @abstractmethod
    def match_url(self, url: str) -> bool:
        """判断 URL 是否属于该平台（支持简化的无前缀链接）。"""
        ...

    def normalize_url(self, url: str) -> str:
        """将简化链接补全为完整 https:// URL。

        默认实现：如果缺少协议头，补上 https://。
        子类可覆盖以处理更复杂的简化场景（如去掉的 www 前缀）。
        """
        if not url.startswith("http://") and not url.startswith("https://"):
            return "https://" + url
        return url

    @abstractmethod
    def parse_urls(self, text: str) -> list[str]:
        """从用户输入中提取该平台的合法链接，保持顺序去重。"""
        ...

    @abstractmethod
    def login_url(self) -> str:
        """返回登录页 URL。"""
        ...

    def click_login(self, page) -> bool:
        """点击登录按钮（如需要）。子类可覆盖。"""
        return False

    @abstractmethod
    def is_logged_in(self, page: ChromiumPage) -> bool:
        """检测是否已登录。"""
        ...

    @abstractmethod
    def get_video_name(self, tab) -> str | None:
        """从标签页提取视频标题，返回 None 表示未找到。"""
        ...

    @abstractmethod
    def download(self, tab, headers: dict, video_name: str):
        """执行下载。"""
        ...

    @staticmethod
    def sanitize_filename(name: str) -> str:
        """替换文件名中的非法字符。"""
        if not name:
            return "anonymous"
        for c in r'\/:*?"<>|':
            name = name.replace(c, "_")
        return name
