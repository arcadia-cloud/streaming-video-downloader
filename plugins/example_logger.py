"""示例插件：把下载历史写入 history.log。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from core.models import DownloadResult
from core.plugin_base import PluginBase


class DownloadLogger(PluginBase):
    name = "下载历史记录"
    description = "把每次下载结果追加写入 history.log"
    author = "example"
    version = "1.1"

    def on_init(self, browser):
        self._path = Path.cwd() / "history.log"
        self._write("插件已加载")

    def on_download_complete(self, url: str, result: DownloadResult | None,
                             success: bool) -> None:
        status = "成功" if success else "失败"
        target = result.path if result else "-"
        self._write(f"{status} {url} -> {target}")

    def on_shutdown(self) -> None:
        self._write("插件已卸载")

    def _write(self, text: str) -> None:
        path = getattr(self, "_path", Path.cwd() / "history.log")
        try:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {text}\n")
        except OSError:
            pass
