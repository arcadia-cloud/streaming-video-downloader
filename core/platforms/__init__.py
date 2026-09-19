"""平台注册。新增平台在此 import 并加入 PLATFORMS 即可。"""

from core.platforms.bilibili import BilibiliPlatform
from core.platforms.douyin import DouyinPlatform

PLATFORMS = [
    BilibiliPlatform(),
    DouyinPlatform(),
]

__all__ = ["PLATFORMS"]
