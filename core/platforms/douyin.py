"""抖音平台实现。支持视频和图文下载，自动识别内容类型。"""

import os
import re
import json
import time
import random

from core.platform_base import PlatformBase
from core.http_client import http_get


DOUYIN_HOME = "https://www.douyin.com/jingxuan"
DOUYIN_DOMAIN = "douyin.com"
SHARE_URL_PATTERN = r'https?://v\.douyin\.com/[^\s|,]+'

ENV_DIR_KEY = "BILI_DOWNLOADER_DIR"
DEFAULT_DIR = os.path.join(os.path.expanduser("~"), "video_downloader")

API_TIMEOUT = 15
IMAGE_DOWNLOAD_DELAY = (0.3, 0.5)


class DouyinPlatform(PlatformBase):
    name = "douyin"
    display_name = "抖音"
    url_prefix = "https://www.douyin.com/"
    sub_folder = "dy_video"
    photo_sub_folder = "dy_photo"

    def match_url(self, url: str) -> bool:
        return DOUYIN_DOMAIN in url

    def normalize_url(self, url: str) -> str:
        match = re.search(SHARE_URL_PATTERN, url)
        if match:
            return match.group(0)
        if not url.startswith("http"):
            return "https://" + url
        return url

    def parse_urls(self, text: str) -> list[str]:
        matches = re.findall(SHARE_URL_PATTERN, text)
        seen: set[str] = set()
        urls: list[str] = []
        for m in matches:
            if m not in seen:
                seen.add(m)
                urls.append(m)
        return urls

    def login_url(self) -> str:
        return DOUYIN_HOME

    def is_logged_in(self, page) -> bool:
        tag = page.ele(
            'xpath://a[@href="//www.douyin.com/user/self"]'
            '/span[@data-e2e="live-avatar"]/img'
        )
        return bool(tag)

    def get_video_name(self, tab) -> str | None:
        time.sleep(2)
        name_tag = tab.eles(
            'xpath://h1[@style="display: inline;"]//span'
        )
        if name_tag:
            texts = [n.text.strip() for n in name_tag
                     if n.text and n.text.strip()]
            if texts:
                return self.sanitize_filename(texts[0])

        name_tag = tab.eles(
            'xpath://div[@style="display: inline;"]'
            ' | //div[@style="display:inline"]'
        )
        if name_tag:
            texts = [n.text.strip() for n in name_tag
                     if n.text and n.text.strip()]
            if texts:
                return self.sanitize_filename(texts[0])
        return None

    def download(self, tab, headers: dict, video_name: str):
        """自动识别视频/图文并下载。"""
        tab.listen.start("aweme/detail")
        tab.get(tab.url)

        packet = tab.listen.wait(timeout=API_TIMEOUT)
        tab.listen.stop()

        if not packet:
            raise ValueError("API 监听超时，未捕获到 aweme/detail 响应")

        json_dict = packet.response.body
        if not json_dict:
            raise ValueError("API 返回空数据")

        if isinstance(json_dict, str):
            json_dict = json.loads(json_dict)

        aweme = json_dict.get("aweme_detail", {})
        if not aweme:
            raise ValueError("API 响应中缺少 aweme_detail 字段")

        video_urls = (aweme.get("video", {})
                      .get("play_addr", {})
                      .get("url_list"))
        if video_urls:
            self._download_video(headers, video_name, video_urls)
            return

        images = aweme.get("images")
        if images:
            self._download_photos(headers, video_name, images)
            return

        raise ValueError("无法识别内容类型（非视频/图文）")

    def _download_video(self, headers: dict, video_name: str,
                        video_urls: list):
        """下载视频文件，逐个尝试 CDN 地址。"""
        folder = os.path.join(
            os.environ.get(ENV_DIR_KEY, DEFAULT_DIR), self.sub_folder
        )
        os.makedirs(folder, exist_ok=True)

        out_path = os.path.join(folder, f"{video_name}.mp4")
        errors = []
        for v_url in video_urls:
            try:
                res, _ = http_get(
                    url=v_url, headers=headers,
                    timeout=30, parse_html=False,
                )
                with open(out_path, "wb") as f:
                    f.write(res.content)
                return
            except Exception as e:
                errors.append(str(e))
                continue

        raise RuntimeError(
            f"所有视频 CDN 地址下载均失败: {'; '.join(errors)}"
        )

    def _download_photos(self, headers: dict, video_name: str,
                         images: list):
        """下载图文图片，每张尝试多个 URL 取最高画质。"""
        folder = os.path.join(
            os.environ.get(ENV_DIR_KEY, DEFAULT_DIR), self.photo_sub_folder
        )
        os.makedirs(folder, exist_ok=True)

        photo_folder = os.path.join(folder, video_name)
        os.makedirs(photo_folder, exist_ok=True)

        index = 1
        for img in images:
            url_list = img.get("url_list", [])
            if not url_list:
                continue

            downloaded = False
            for img_url in reversed(url_list):
                try:
                    res, _ = http_get(
                        url=img_url, headers=headers,
                        timeout=30, parse_html=False,
                    )
                    path = os.path.join(photo_folder, f"{index}.jpg")
                    with open(path, "wb") as f:
                        f.write(res.content)
                    downloaded = True
                    break
                except Exception:
                    continue

            if downloaded:
                index += 1
                time.sleep(random.uniform(*IMAGE_DOWNLOAD_DELAY))

        if index == 1:
            raise RuntimeError("所有图片下载均失败")
