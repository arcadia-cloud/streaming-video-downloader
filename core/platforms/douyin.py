"""抖音平台实现。支持视频和图文下载，自动识别内容类型。

图文下载保留原始滑动逻辑：通过滑动触发懒加载，监听所有图片请求，
再去重、过滤压缩图、保留最高画质。
"""

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

API_TIMEOUT = 30
IMAGE_DOWNLOAD_DELAY = (0.3, 0.5)
SLIDE_DELAY = (0.2, 0.3)
SILENCE_CHECK_TIMEOUT = 6
SILENCE_CHECK_RETRIES = 3


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

    def download(self, tab, url: str, headers: dict, video_name: str) -> str:
        """自动识别视频/图文并下载。返回实际使用的视频名。

        严格还原原始流程：new_tab() 空标签页 → listen.start → get(url) → listen.wait
        确保监听在导航前启动，API 响应才能被捕获。
        """
        tab.listen.start("aweme/detail")
        tab.get(url)

        packet = tab.listen.wait(timeout=API_TIMEOUT)
        tab.listen.stop()

        json_dict = None
        if packet and packet.response.body:
            body = packet.response.body
            if isinstance(body, bytes):
                body = body.decode("utf-8")
            if isinstance(body, str):
                json_dict = json.loads(body)
            elif isinstance(body, dict):
                json_dict = body

        if not json_dict:
            json_dict = self._extract_from_html(tab.html)

        if not json_dict:
            raise ValueError(
                "无法获取视频数据：API 监听超时且 HTML 解析失败"
            )

        aweme = json_dict.get("aweme_detail", {})
        if not aweme:
            raise ValueError("API 响应中缺少 aweme_detail 字段")

        name = self.get_video_name(tab) or video_name

        video_urls = (aweme.get("video", {})
                      .get("play_addr", {})
                      .get("url_list"))
        if video_urls:
            self._download_video(headers, name, video_urls)
            return name

        images = aweme.get("images")
        if images:
            self._download_photos_api(headers, name, images)
            return name

        if self._is_photo_page(tab):
            self._download_photos_slide(tab, url, headers, name)
            return name

        raise ValueError("无法识别内容类型（非视频/图文）")

    @staticmethod
    def _is_photo_page(tab) -> bool:
        """检测当前页面是否为图文类型。"""
        page_tag_list = tab.eles(
            'xpath://div[@data-e2e="player-container"]//span'
        )
        return bool(page_tag_list)

    def _download_photos_slide(self, tab, url: str, headers: dict,
                               video_name: str):
        """图文下载：滑动加载所有页 → 监听图片请求 → 去重 → 过滤。

        保留原始滑动逻辑：抖音图文是懒加载，不滑动只能拿到部分图片。
        """
        tab.listen.start("https://p3-pc-sign.douyinpic.com/tos-cn-i")
        tab.get(url)

        page_tag_list = tab.eles(
            'xpath://div[@data-e2e="player-container"]//span'
        )
        if not page_tag_list:
            tab.listen.stop()
            raise ValueError("无法分析图文总页数")

        prepro_list = [tag.text.strip() for tag in page_tag_list]
        try:
            total_page = int(
                re.findall(r'/\s*(.{1,3})', "".join(prepro_list))[0]
            )
        except (ValueError, IndexError):
            tab.listen.stop()
            raise ValueError("解析图文总页数失败")

        for _ in range(total_page):
            se = random.uniform(0.05, 0.1)
            x = random.randint(-350, -300)
            tab.actions.move_to(
                'xpath://div[@style="display: inline;"]'
                ' | //div[@style="display:inline"]',
                duration=0,
            ).move(-300, 0, 0).hold().move(x, 0, se).release()
            time.sleep(random.uniform(*SLIDE_DELAY))

        for _ in range(SILENCE_CHECK_RETRIES):
            silence_check = tab.listen.wait_silent(
                timeout=SILENCE_CHECK_TIMEOUT, targets_only=True,
            )
            if silence_check:
                break

        packet_list = tab.listen.wait(
            timeout=3, count=total_page + 5, fit_count=False,
        )
        tab.listen.stop()

        if not packet_list:
            raise ValueError("图文 API 监听未捕获到任何数据包")

        raw_pic_url_set = {pkt.url for pkt in packet_list}
        pic_url_set = {
            u for u in raw_pic_url_set if "FAVORITE" not in u
        }

        diction: dict[str, str] = {}
        dup_set: set[str] = set()
        for pic_url in pic_url_set:
            match = re.findall(
                r'/tos-cn-i.*?/(.*?)(?=~tplv|~noop)', pic_url,
            )
            if match:
                pic_unitag = match[0]
                if pic_unitag in diction:
                    dup_set.add(diction[pic_unitag])
                    dup_set.add(pic_url)
                else:
                    diction[pic_unitag] = pic_url

        remove_set = {
            dup_url for dup_url in dup_set if "q75.webp?" in dup_url
        }
        pic_url_list = list(pic_url_set - remove_set)

        folder = os.path.join(
            os.environ.get(ENV_DIR_KEY, DEFAULT_DIR),
            self.photo_sub_folder,
        )
        os.makedirs(folder, exist_ok=True)
        photo_folder = os.path.join(folder, video_name)
        os.makedirs(photo_folder, exist_ok=True)

        index = 1
        for pic_url in pic_url_list:
            try:
                res, _ = http_get(
                    url=pic_url, headers=headers,
                    timeout=30, parse_html=False,
                )
                path = os.path.join(photo_folder, f"{index}.jpg")
                with open(path, "wb") as f:
                    f.write(res.content)
                index += 1
                time.sleep(random.uniform(*IMAGE_DOWNLOAD_DELAY))
            except Exception:
                continue

        if index == 1:
            raise RuntimeError("所有图片下载均失败")

    @staticmethod
    def _extract_from_html(html: str):
        """从页面 HTML 中提取视频数据（降级方案）。"""
        patterns = [
            r'"awemeDetail"\s*:\s*(\{.+?\})\s*[,}]',
            r'"aweme_detail"\s*:\s*(\{.+?\})\s*[,}]',
        ]
        for pattern in patterns:
            match = re.search(pattern, html, flags=re.S)
            if match:
                try:
                    data = json.loads(match.group(1))
                    if "aweme_detail" not in data:
                        return {"aweme_detail": data}
                    return data
                except (json.JSONDecodeError, IndexError):
                    continue

        video_url_match = re.search(
            r'"url_list"\s*:\s*\["(https?://[^"]+)"', html
        )
        if video_url_match:
            return {"aweme_detail": {"video": {"play_addr": {
                "url_list": [video_url_match.group(1)]
            }}}}
        return None

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

    def _download_photos_api(self, headers: dict, video_name: str,
                             images: list):
        """当 API 直接返回 images 字段时的图片下载。"""
        folder = os.path.join(
            os.environ.get(ENV_DIR_KEY, DEFAULT_DIR),
            self.photo_sub_folder,
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
