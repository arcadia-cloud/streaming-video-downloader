"""小红书平台实现（待实现）。

实现步骤：
1. 继承 PlatformBase，完成所有 abstractmethod
2. 在 core/platforms/__init__.py 中导入并加入 PLATFORMS
3. 主程序会自动通过 match_url 路由到该平台
"""

# from core.platform_base import PlatformBase
#
#
# class XiaohongshuPlatform(PlatformBase):
#     name = "xiaohongshu"
#     display_name = "小红书"
#     url_prefix = "https://www.xiaohongshu.com/"
#     sub_folder = "xhs_video"
#
#     def match_url(self, url: str) -> bool:
#         ...
#
#     def parse_urls(self, text: str) -> list[str]:
#         ...
#
#     def login_url(self) -> str:
#         return "https://www.xiaohongshu.com/"
#
#     def is_logged_in(self, page) -> bool:
#         ...
#
#     def get_video_name(self, tab) -> str | None:
#         ...
#
#     def download(self, tab, headers: dict, video_name: str):
#         ...
