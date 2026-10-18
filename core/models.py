"""跨模块共享的轻量数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Progress:
    """下载进度：字节（unit="bytes"）或条目（unit="items"）。"""

    done: int = 0
    total: int = 0
    unit: str = "bytes"

    @property
    def ratio(self) -> float:
        if not self.total:
            return 0.0
        return max(0.0, min(1.0, self.done / self.total))


@dataclass
class DownloadResult:
    """一次下载的结果。

    平台实现只负责产出这个对象，GUI / 插件不再自己拼路径，
    从而避免"抖音图文却被拼成 xxx.mp4"这类问题。
    """

    name: str
    kind: str = "video"                  # video | photos
    path: str = ""                       # 视频文件，或图文目录
    files: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    @property
    def is_photos(self) -> bool:
        return self.kind == "photos"

    def describe(self) -> str:
        if self.is_photos:
            return f"{self.name}（{len(self.files)} 张图片）"
        return self.name
