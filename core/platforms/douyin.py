"""抖音平台实现（待实现）。

实现步骤：
1. 继承 PlatformBase，完成所有 abstractmethod
2. 在 core/platforms/__init__.py 中导入并加入 PLATFORMS
3. 主程序会自动通过 match_url 路由到该平台
"""

# from core.platform_base import PlatformBase
#
#
# class DouyinPlatform(PlatformBase):
#     name = "douyin"
#     display_name = "抖音"
#     url_prefix = "https://www.douyin.com/"
#     sub_folder = "dy_video"
#
#     def match_url(self, url: str) -> bool:
#         ...
#
#     def parse_urls(self, text: str) -> list[str]:
#         ...
#
#     def login_url(self) -> str:
#         return "https://www.douyin.com/"
#
#     def is_logged_in(self, page) -> bool:
#         ...
#
#     def get_video_name(self, tab) -> str | None:
#         ...
#
#     def download(self, tab, headers: dict, video_name: str):
#         ...
