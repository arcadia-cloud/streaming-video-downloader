"""平台注册表。新增平台：在这里 import 并加入 PLATFORMS 即可。"""

from __future__ import annotations

from core.platforms.bilibili import BilibiliPlatform
from core.platforms.douyin import DouyinPlatform
from core.platforms.xiaohongshu import XiaohongshuPlatform

PLATFORMS = [
    BilibiliPlatform(),
    DouyinPlatform(),
    XiaohongshuPlatform(),
]

__all__ = ["PLATFORMS"]
