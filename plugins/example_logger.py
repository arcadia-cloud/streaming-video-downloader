from core.plugin_base import PluginBase


class DownloadLogger(PluginBase):
    """记录下载历史到日志文件的示例插件。"""

    name = "下载历史记录"
    description = "将每次下载结果写入 history.log"
    author = "example"
    version = "1.0"

    def on_init(self, browser):
        from datetime import datetime
        self._log_path = "history.log"
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] 插件已加载\n")

    def on_download_complete(self, url: str, video_path: str, success: bool):
        from datetime import datetime
        status = "成功" if success else "失败"
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%H:%M:%S}] {status} {url} -> {video_path}\n")

    def on_shutdown(self):
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write("插件已卸载\n")
