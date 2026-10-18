"""本地设置读写。

设置保存在 %APPDATA%/VideoDownloader/config.json，重启后仍然生效。
环境变量 BILI_DOWNLOADER_DIR 仍然兼容（优先级最高）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

APP_NAME = "VideoDownloader"
ENV_DIR_KEY = "BILI_DOWNLOADER_DIR"

DEFAULT_DOWNLOAD_DIR = Path.home() / "video_downloader"

DEFAULTS: dict = {
    "download_dir": str(DEFAULT_DOWNLOAD_DIR),
    "open_after_done": False,
    "appearance": "dark",          # light | dark | system
    "browser_path": "",            # 留空 = 用系统默认 Chrome；可指向 Edge 等
}


def config_path() -> Path:
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / ".config"
    return root / APP_NAME / "config.json"


_cache: dict | None = None


def load() -> dict:
    """读取配置；损坏或缺失时回退到默认值。"""
    global _cache
    if _cache is not None:
        return _cache

    data = dict(DEFAULTS)
    path = config_path()
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                data.update({k: v for k, v in loaded.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass

    _cache = data
    return data


def save(data: dict) -> None:
    global _cache
    merged = dict(DEFAULTS)
    merged.update({k: v for k, v in data.items() if k in DEFAULTS})
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    _cache = merged


def download_dir() -> Path:
    """下载根目录：环境变量 > 配置文件 > 默认。"""
    env = os.environ.get(ENV_DIR_KEY)
    if env:
        return Path(env).expanduser()
    return Path(load()["download_dir"]).expanduser()
