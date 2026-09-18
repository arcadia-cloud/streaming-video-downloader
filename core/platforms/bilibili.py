"""Bilibili 平台实现。"""

import os
import re
import json
import uuid
import subprocess

import imageio_ffmpeg

from core.platform_base import PlatformBase
from core.http_client import http_get

BILI_HOME = "https://www.bilibili.com/"
BILI_PREFIX = "https://www.bilibili.com/"
LOGIN_TIMEOUT = 40
LOGIN_WARN_COUNTDOWN = 10

# 覆盖自定义目录的环境变量名
ENV_DIR_KEY = "BILI_DOWNLOADER_DIR"
DEFAULT_DIR = r"D:\data"


class BilibiliPlatform(PlatformBase):
    name = "bilibili"
    display_name = "Bilibili"
    url_prefix = BILI_PREFIX
    sub_folder = "bili_video"

    def match_url(self, url: str) -> bool:
        return url.startswith(BILI_PREFIX)

    def parse_urls(self, text: str) -> list[str]:
        text = text.replace("\n", "|").replace("\r", "")
        parts = [p.strip() for p in text.split("|") if p.strip()]
        seen = set()
        urls = []
        for p in parts:
            if p.startswith(BILI_PREFIX) and p not in seen:
                seen.add(p)
                urls.append(p)
        return urls

    def login_url(self) -> str:
        return BILI_HOME

    def is_logged_in(self, page) -> bool:
        tag = page.ele('xpath://div[@class="header-login-entry"]')
        return not tag

    def get_video_name(self, tab) -> str | None:
        name_tag = tab.ele(
            'xpath://div[@class="video-info-title-inner"]/h1'
        )
        title = name_tag.attr('title') if name_tag else None
        return self.sanitize_filename(title) if title else None

    def download(self, tab, headers: dict, video_name: str):
        html = tab.html
        folder = os.path.join(
            os.environ.get(ENV_DIR_KEY, DEFAULT_DIR), self.sub_folder
        )
        os.makedirs(folder, exist_ok=True)

        vid = self._extract_media_url(html, "video", "audio")
        aud = self._extract_media_url(html, "audio", "dolby")

        task_id = uuid.uuid4().hex[:8]
        v_path = os.path.join(folder, f"vid_{task_id}.mp4")
        a_path = os.path.join(folder, f"aud_{task_id}.mp3")

        try:
            self._download_file(vid, v_path, headers)
            self._download_file(aud, a_path, headers)
            out_path = os.path.join(folder, f"{video_name}.mp4")
            self._merge_audio_video(v_path, a_path, out_path)
        finally:
            for p in (v_path, a_path):
                if os.path.exists(p):
                    os.remove(p)

    @staticmethod
    def _extract_media_url(html: str, key: str, next_key: str) -> str:
        pattern = rf'"{key}"\s*:\s*(\[.+?])(?=\s*,\s*"{next_key}")'
        match = re.findall(pattern, html, flags=re.S)
        if not match:
            raise ValueError(f"未找到 {key} 链接")
        return json.loads(match[0])[0]["baseUrl"]

    @staticmethod
    def _download_file(url: str, path: str, headers: dict):
        res, _ = http_get(
            url=url, headers=headers, timeout=30, parse_html=False
        )
        with open(path, "wb") as f:
            f.write(res.content)

    @staticmethod
    def _merge_audio_video(v_path: str, a_path: str, out_path: str):
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        cmd = [
            ffmpeg, "-y",
            "-i", v_path,
            "-i", a_path,
            "-c:v", "copy",
            "-c:a", "aac",
            "-strict", "experimental",
            out_path,
        ]
        subprocess.run(
            cmd, check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
