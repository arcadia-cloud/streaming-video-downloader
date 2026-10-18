"""抖音平台实现：视频 / 图文自动识别。

v6 在 v5 的基础上继续收紧取数与容错（每一条都对应一类真实失败）：

1. 短链跳转后重新取 aweme_id：`v.douyin.com/xxx` 打开前没有 id，
   跳转完成后用最终 URL 再解析一次，避免短链场景退化成"捡第一个包"；
2. 详情未命中时刷新重试一次：首屏偶发不发请求的情况不必人工重跑；
3. 失败时给出页面状态：风控页 / 登录墙 / 作品已删除 / 纯客户端渲染，
   而不是笼统的"页面解析也未命中"；
4. 文件名优先取作品文案（desc），比页面标题元素更稳、更可读；
5. 图片并发下载（默认 3 路），顺序仍按索引返回；
   requests.Session 改为线程局部，规避连接池竞争；
6. DOM 采集补 srcset 与 HTML 实体解码，减少"地址拿不到"的漏图；
7. 图集字段额外兼容 download_url_list。

v5 已修正（相对 v4）：
- 详情包按 aweme_id 校验；图文字段三级回退；滑屏改读 DOM；
- 去重键改为路径段、取消 [:total] 硬截断；页数只接受 1..30；
- download_addr 降级为兜底并标记 watermarked；全程 on_log 诊断。
"""

from __future__ import annotations

import html
import json
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import unquote

from core import jsonx
from core.http_client import download_file, download_media
from core.media import unique_dir, unique_file
from core.models import DownloadResult, Progress
from core.platform_base import PlatformBase, find_ele, find_eles

DETAIL_API = "aweme/detail"
IMAGE_HOST = "https://p3-pc-sign.douyinpic.com/tos-cn-i"
SLIDE_DELAY = (0.18, 0.3)
MAX_PAGES = 30
DETAIL_WAIT_SECONDS = 12.0
IMAGE_WORKERS = 3

# 图文图片在 player-container 里以 <img> 或 background-image 出现
_CONTAINER = 'xpath://div[@data-e2e="player-container"]'
_IMG_XPATH = _CONTAINER + '//img'
_BG_XPATH = _CONTAINER + '//div[contains(@style,"background-image")]'
# 图文页真正能拖动切换的是标题这个 div（翻页按钮不可点）
_TITLE_XPATH = ('xpath://div[@style="display: inline;"]'
                ' | //div[@style="display:inline"]')

_AWEME_ID = re.compile(r"/(?:video|note|slides)/(\d{6,})")
_MODAL_ID = re.compile(r"modal_id=(\d{6,})")
_IMAGE_KEY = re.compile(r"/tos-cn-i[^/]*/([^~?]+)")
_URL_PATH = re.compile(r"/([^/?]+)(?:\?|$)")
_BG_URL = re.compile(r"""url\(["']?([^"')]+)["']?\)""")

# 失败时的页面特征 -> 人话
_PAGE_MARKERS = (
    ("验证", "页面是风控/验证码页，需要人工过验证"),
    ("captcha", "页面是风控/验证码页，需要人工过验证"),
    ("扫码登录", "登录态已失效，页面停在登录入口"),
    ("作品不存在", "作品不存在或已被删除"),
    ("内容不可见", "作品不可见（私密 / 仅粉丝 / 地区限制）"),
)


class DouyinPlatform(PlatformBase):
    name = "douyin"
    display_name = "抖音"
    url_prefix = "https://www.douyin.com/"
    sub_folder = "dy_video"
    photo_sub_folder = "dy_photo"
    host_suffixes = ("douyin.com",)
    accent = "#7FE3D4"

    # --- 登录 ---------------------------------------------------------
    def login_url(self) -> str:
        return "https://www.douyin.com/"

    def is_logged_in(self, page) -> bool:
        return bool(find_ele(
            page,
            'xpath://a[@href="//www.douyin.com/user/self"]'
            '//span[@data-e2e="live-avatar"]/img',
            'xpath://a[contains(@href,"/user/self")]//img',
            timeout=1,
        ))

    # --- 元信息 -------------------------------------------------------
    def get_video_name(self, tab) -> str | None:
        for selector, timeout in (
            ('xpath://h1[@style="display: inline;"]//span', 2),
            ('xpath://div[@style="display: inline;"]'
             ' | //div[@style="display:inline"]', 1),
        ):
            elements = find_eles(tab, selector, timeout=timeout)
            for element in elements:
                text = (element.text or "").strip()
                if text:
                    return self.sanitize_filename(text)
        return None

    def _name_from_aweme(self, aweme: dict) -> str | None:
        """作品文案比页面标题元素更可靠，也更有辨识度。"""
        for key in ("desc", "caption"):
            text = (aweme.get(key) or "").strip()
            if text:
                cleaned = self.sanitize_filename(text)
                if cleaned and cleaned != "untitled":
                    return cleaned
        return None

    # --- 下载 ---------------------------------------------------------
    @staticmethod
    def _is_note_url(url: str) -> bool:
        """图文笔记的地址形如 /note/<id>（个别为 /slides/<id>）。"""
        return "/note/" in (url or "") or "/slides/" in (url or "")

    @staticmethod
    def _classify(aweme: dict) -> str:
        """判断这条作品是图文还是视频：photos / video / unknown。

        图集优先——抖音的 note 除了 images 之外，常常还带一个 video
        （封面动画 / 背景），"有视频流"不能作为判据。
        """
        if DouyinPlatform._image_nodes(aweme)[0]:
            return "photos"
        if DouyinPlatform._video_urls(aweme)[0]:
            return "video"
        return "unknown"

    def download(self, tab, url: str, headers: dict,
                 fallback_name: str, on_progress=None, on_log=None,
                 options=None) -> DownloadResult:
        log = _logger(on_log)

        # 新标签页还是空白，短链要先落地一次才知道是 /note/ 还是 /video/
        try:
            current = (getattr(tab, "url", "") or "").strip()
        except Exception:  # noqa: BLE001
            current = ""
        if current in ("", "about:blank", "data:,"):
            try:
                self._load(tab, url, log)
                current = (getattr(tab, "url", "") or "").strip()
            except Exception:  # noqa: BLE001 - 落地失败就按原链接判断
                current = url

        # 图文笔记（/note/）不需要详情接口：直接监听图片请求 + 滑动采集，
        # 和桌面脚本的做法一致。详情接口在笔记页经常拿不到，不能当入口。
        if self._is_note_url(current):
            log("链接是图文笔记（note），直接走页面采集")
            name = (self.get_video_name(tab)
                    or self.sanitize_filename(fallback_name))
            try:
                return self._download_photos_dom(tab, url, headers, name,
                                                 on_progress, log)
            except Exception as exc:  # noqa: BLE001 - 再退到详情接口
                log(f"页面采集失败（{exc}），改试详情接口", "warn")

        aweme = self._fetch_detail(tab, url, log)
        name = (self.get_video_name(tab)
                or self._name_from_aweme(aweme)
                or self.sanitize_filename(fallback_name))

        kind = self._classify(aweme)
        aweme_type = aweme.get("aweme_type")

        if kind == "photos":
            image_nodes, field = self._image_nodes(aweme)
            log(f"识别为图文（{field}，{len(image_nodes)} 张"
                + (f"，aweme_type={aweme_type}" if aweme_type is not None else "")
                + "）")
            try:
                return self._download_images_api(image_nodes, name, headers,
                                                 on_progress, log)
            except Exception as exc:  # noqa: BLE001 - 接口地址不可用就采页面
                log(f"接口图集不可用（{exc}），改用页面采集", "warn")
                try:
                    return self._download_photos_dom(tab, url, headers, name,
                                                     on_progress, log)
                except Exception as dom_exc:  # noqa: BLE001
                    raise ValueError(
                        f"图文下载失败：接口（{exc}）；页面（{dom_exc}）"
                    ) from dom_exc

        if kind == "video":
            video_urls, used_download_addr = self._video_urls(aweme)
            log("识别为视频")
            if used_download_addr:
                log("只拿到 download_addr（通常是带水印的分享版），"
                    "结果已标记 watermarked", "error")
            out = unique_file(self.folder() / f"{name}.mp4")
            download_file(video_urls[0], out, headers,
                          candidates=video_urls[1:],
                          on_progress=on_progress, max_candidates=3)
            extra = {"watermarked": True} if used_download_addr else {}
            return DownloadResult(name=name, kind="video",
                                  path=str(out), files=[str(out)], extra=extra)

        if self._is_photo_page(tab):
            log("详情结构里没有图集字段，回退到页面采集", "error")
            return self._download_photos_dom(tab, url, headers, name,
                                             on_progress, log)

        raise ValueError(
            "无法识别内容类型（既没有视频流也没有图集字段"
            + (f"，aweme_type={aweme_type}" if aweme_type is not None else "")
            + "）；把日志里这几行发我就能定位")

    def photo_folder(self):
        from core.config import download_dir

        base = download_dir()
        if base.name == self.photo_sub_folder:
            return base
        return base / self.photo_sub_folder

    # --- 数据获取 -----------------------------------------------------
    def _fetch_detail(self, tab, url: str, log) -> dict:
        """监听详情接口；未命中时刷新重试一次，再退到页面内嵌数据。"""
        aweme_id = self._aweme_id(url)
        tab.listen.start(DETAIL_API)
        try:
            self._load(tab, url, log)
            resolved = aweme_id or self._aweme_id(getattr(tab, "url", "") or "")
            if resolved and not aweme_id:
                log(f"短链跳转后解析到 aweme_id={resolved}")

            detail = self._wait_detail(tab, resolved, log)
            if detail is None:
                log("首次未命中，刷新页面重试一次", "error")
                self._load(tab, url, log, refresh=True)
                detail = self._wait_detail(tab, resolved, log)
        finally:
            tab.listen.stop()

        if detail:
            return detail

        inline = self._inline_detail(tab.html)
        if inline:
            log("页面内嵌数据命中（字段可能比接口少）")
            return inline

        raise ValueError(f"拿不到作品数据：{self._page_state(tab)}")

    @staticmethod
    def _load(tab, url: str, log, refresh: bool = False) -> None:
        try:
            if refresh:
                tab.refresh()
            else:
                tab.get(url, timeout=25)
        except Exception as exc:  # noqa: BLE001 - 导航超时仍可能有包
            action = "刷新" if refresh else "打开"
            log(f"{action}页面失败：{type(exc).__name__}: {exc}", "error")

    def _wait_detail(self, tab, aweme_id: str | None, log) -> dict | None:
        """在截止时间内持续收包，只接受 aweme_id 匹配的那一个。"""
        deadline = time.monotonic() + DETAIL_WAIT_SECONDS
        skipped: set[str] = set()

        while time.monotonic() < deadline:
            raw = tab.listen.wait(timeout=1.5)
            for packet in _packet_list(raw):
                aweme = self._aweme_of(packet, log)
                if not aweme:
                    continue
                packet_id = str(aweme.get("aweme_id") or "")
                if aweme_id and packet_id and packet_id != aweme_id:
                    if packet_id not in skipped:
                        skipped.add(packet_id)
                        log(f"丢弃非目标作品包 aweme_id={packet_id}")
                    continue
                log(f"详情包命中 aweme_id={packet_id or '未知'}")
                return aweme
        return None

    @staticmethod
    def _aweme_of(packet, log) -> dict | None:
        """从监听到的包里取出 aweme_detail，失败时说明原因。"""
        try:
            body = packet.response.body
        except Exception as exc:  # noqa: BLE001 - 缓存命中时取不到包体
            log(f"取包体失败：{type(exc).__name__}: {exc}")
            return None

        if isinstance(body, bytes):
            body = body.decode("utf-8", "ignore")
        if isinstance(body, str):
            if not body.strip():
                log("包体为空（常见于缓存命中）")
                return None
            try:
                body = json.loads(body)
            except ValueError:
                log("包体不是 JSON（可能是 protobuf 或错误页）")
                return None
        if isinstance(body, dict):
            return jsonx.find_key(body, ("aweme_detail", "awemeDetail"))
        return None

    @staticmethod
    def _inline_detail(html_text: str) -> dict | None:
        """页面内嵌数据：能命中就用，命中不了交给 _page_state 解释。"""
        match = re.search(
            r'<script[^>]+id="RENDER_DATA"[^>]*>(.*?)</script>',
            html_text or "", re.S,
        )
        if match:
            try:
                data = json.loads(unquote(match.group(1)))
                found = jsonx.find_key(data, ("aweme_detail", "awemeDetail"))
                if found:
                    return found
            except (ValueError, TypeError):
                pass

        for marker in ('"aweme_detail":', '"awemeDetail":'):
            if marker not in (html_text or ""):
                continue
            try:
                data = jsonx.json_after(html_text, marker)
            except (ValueError, json.JSONDecodeError):
                continue
            if isinstance(data, dict):
                return jsonx.find_key(
                    data, ("aweme_detail", "awemeDetail")) or data
        return None

    @staticmethod
    def _page_state(tab) -> str:
        """把"拿不到"翻译成具体原因，避免统一报超时。"""
        try:
            html_text = tab.html or ""
            current_url = getattr(tab, "url", "") or ""
        except Exception:  # noqa: BLE001
            return "读取页面内容失败（标签页可能已关闭）"

        head = html_text[:200000]
        for marker, reason in _PAGE_MARKERS:
            if marker in head:
                return reason
        snippet = current_url[:80]
        return f"页面没有作品结构（可能已改为纯客户端渲染），当前页 {snippet}"

    @staticmethod
    def _aweme_id(url: str) -> str | None:
        """从作品链接里取 aweme_id；短链拿不到时返回 None。"""
        match = _MODAL_ID.search(url or "") or _AWEME_ID.search(url or "")
        return match.group(1) if match else None

    @staticmethod
    def _video_urls(aweme: dict) -> tuple[list[str], bool]:
        """返回 (候选地址, 是否只能用水印分享版)。"""
        video = aweme.get("video") or {}
        nodes = [video.get("play_addr")]

        rates = [rate for rate in (video.get("bit_rate") or [])
                 if isinstance(rate, dict)]
        rates.sort(key=lambda rate: rate.get("bit_rate") or 0, reverse=True)
        nodes.extend(rate.get("play_addr") for rate in rates)

        urls: list[str] = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            for candidate in node.get("url_list") or []:
                if isinstance(candidate, str) and candidate:
                    urls.append(candidate)
        urls = list(dict.fromkeys(urls))
        if urls:
            return urls[:4], False

        # 只有在完全拿不到 play_addr 时才退到 download_addr
        download = video.get("download_addr")
        if isinstance(download, dict):
            for candidate in download.get("url_list") or []:
                if isinstance(candidate, str) and candidate:
                    urls.append(candidate)
        return list(dict.fromkeys(urls))[:2], bool(urls)

    @staticmethod
    def _image_nodes(aweme: dict) -> tuple[list, str | None]:
        """按可靠性依次尝试图集字段，返回 (节点列表, 命中的字段名)。"""
        for path in (("images",),
                     ("image_post_info", "images"),
                     ("image_list",),
                     ("image_post_info", "image_list")):
            node = aweme
            for key in path:
                node = node.get(key) if isinstance(node, dict) else None
            if isinstance(node, list) and node:
                return node, ".".join(path)
        return [], None

    @staticmethod
    def _is_photo_page(tab) -> bool:
        return bool(find_eles(
            tab, _CONTAINER + '//span',
            timeout=2,
        ))

    # --- 图文：接口直接给 images -------------------------------------
    def _download_images_api(self, images: list, name: str, headers: dict,
                             on_progress=None, log=None) -> DownloadResult:
        log = log or _logger(None)
        candidates: list[list[str]] = []
        for image in images:
            if isinstance(image, dict):
                urls: list[str] = []
                for key in ("url_list", "download_url_list"):
                    urls.extend(u for u in (image.get(key) or []) if u)
                candidates.append(list(dict.fromkeys(urls)))
            elif isinstance(image, str) and image:
                candidates.append([image])

        usable = [c for c in candidates if c]
        if not usable:
            # 常见于 note 的图片走了另一套字段：给出数量，便于对照结构
            keys = set()
            for image in images[:3]:
                if isinstance(image, dict):
                    keys.update(image.keys())
            raise ValueError(
                f"图集有 {len(images)} 条记录，但都没有可用地址"
                f"（字段：{'/'.join(sorted(keys)) or '非字典'}）")
        if len(usable) < len(candidates):
            log(f"{len(candidates) - len(usable)} 张图没有地址，已跳过", "warn")

        return self._save_images(candidates, name, headers, on_progress, log)

    # --- 图文：页面采集兜底 -------------------------------------------
    def _download_photos_dom(self, tab, url: str, headers: dict,
                             name: str, on_progress=None,
                             log=None) -> DownloadResult:
        log = log or _logger(None)
        tab.listen.start(IMAGE_HOST)
        order: list[str] = []
        best: dict[str, str] = {}

        def absorb(urls: list[str]) -> int:
            added = 0
            for candidate in urls:
                if not candidate or "FAVORITE" in candidate:
                    continue
                key = _image_key(candidate)
                if key not in best:
                    best[key] = candidate
                    order.append(key)
                    added += 1
                elif _quality(candidate) > _quality(best[key]):
                    best[key] = candidate
            return added

        try:
            self._load(tab, url, log)
            total = self._wait_total(tab)
            if total:
                log(f"页面标注 {total} 张，开始采集")
            else:
                log("页面没有页码文本，按 12 次拖动采集", "warn")

            absorb(self._harvest_dom(tab))

            # 拖动直到拿够为止：用页面上的 "3/9" 做反馈，拖不动就重试，
            # 不再"固定拖 N 次"或"没新增就退出"——那两种都会漏图。
            misses = 0
            last_index = 0
            limit = (total or 12) * 2 + 4
            for _step in range(limit):
                if total and len(order) >= total:
                    break
                if not self._drag_once(tab):
                    log("翻页元素不可用，停止拖动", "error")
                    break
                time.sleep(random.uniform(*SLIDE_DELAY))

                absorb(self._harvest_dom(tab))
                absorb(self._drain_packets(tab))

                index, seen_total = self._page_indicator(tab)
                if seen_total and not total:
                    total = seen_total
                if index and index == last_index:
                    misses += 1
                    if misses >= 3:
                        log("连续三次翻页无变化，停止拖动", "warn")
                        break
                else:
                    misses = 0
                    last_index = index

            # 还是不够：拖回开头再扫一遍（已缓存的图不会再发请求，回扫能补）
            if total and len(order) < total:
                log(f"只拿到 {len(order)}/{total} 张，回扫一次", "warn")
                for _ in range(total + 2):
                    if len(order) >= total or not self._drag_once(tab, back=True):
                        break
                    time.sleep(random.uniform(*SLIDE_DELAY))
                for _ in range(total + 2):
                    if len(order) >= total or not self._drag_once(tab):
                        break
                    time.sleep(random.uniform(*SLIDE_DELAY))
                    absorb(self._harvest_dom(tab))
                    absorb(self._drain_packets(tab))

            # 回扫还不够：整页重载一次再扫（两次结果取并集）。
            # 只对"某次请求丢包/超时"有效；纯懒加载不触发的图，重载也补不上。
            if total and len(order) < total:
                log(f"重载页面后再采一次（当前 {len(order)}/{total}）", "warn")
                try:
                    tab.refresh()
                except Exception:  # noqa: BLE001
                    self._load(tab, url, log, refresh=True)
                time.sleep(random.uniform(0.8, 1.4))
                absorb(self._harvest_dom(tab))
                for _ in range((total or 12) + 2):
                    if len(order) >= total or not self._drag_once(tab):
                        break
                    time.sleep(random.uniform(*SLIDE_DELAY))
                    absorb(self._harvest_dom(tab))
                    absorb(self._drain_packets(tab))

            # 等网络安静（最多三次，每次 6s），再兜底收一轮
            for _ in range(3):
                try:
                    if tab.listen.wait_silent(timeout=6, targets_only=True):
                        break
                except Exception:  # noqa: BLE001 - 老版本没有这个方法
                    break
            absorb(self._drain_packets(tab, rounds=3))
            absorb(self._harvest_dom(tab))
        finally:
            tab.listen.stop()

        if not order:
            raise ValueError("没有采集到任何图片地址")
        if total and len(order) < total:
            log(f"只采集到 {len(order)}/{total} 张（页面懒加载未触发）", "error")

        candidates = [[best[key]] for key in order]
        return self._save_images(candidates, name, headers, on_progress, log)

    _ANY_IMG_XPATH = 'xpath://img[contains(@src, "douyinpic.com")]'

    def _harvest_dom(self, tab) -> list[str]:
        """读取当前已渲染的图片地址：DOM 是事实，网络包只是线索。"""
        found: list[str] = []
        for element in find_eles(tab, _IMG_XPATH, timeout=0.5):
            src = (element.attr("src") or "").strip()
            if not src.startswith("http"):
                src = (element.attr("data-src") or "").strip()
            if not src.startswith("http"):
                srcset = (element.attr("srcset") or "").split(",")[0].strip()
                src = srcset.split(" ")[0] if srcset else ""
            if src.startswith("http"):
                found.append(html.unescape(src))
        for element in find_eles(tab, _BG_XPATH, timeout=0.5):
            match = _BG_URL.search(element.attr("style") or "")
            if match:
                candidate = html.unescape(match.group(1))
                if candidate.startswith("http"):
                    found.append(candidate)

        # 容器没命中（改版/结构不同）时，退而抓页面里所有抖音图片
        if not found:
            for element in find_eles(tab, self._ANY_IMG_XPATH, timeout=1):
                src = html.unescape((element.attr("src") or "").strip())
                if src.startswith("http") and "FAVORITE" not in src:
                    found.append(src)
        return found

    def _drag_once(self, tab, back: bool = False) -> bool:
        """拖动视图切换下一张（back=True 时往回拖）。

        优先拖标题那个 div：图文页的翻页按钮不可点，而标题 div 上拖动
        能稳定触发切换；容器拖不动时再退回容器。
        """
        delta = 300 if back else None
        for xpath in (_TITLE_XPATH, _CONTAINER):
            target = find_ele(tab, xpath, timeout=1)
            if not target:
                continue
            try:
                duration = random.uniform(0.05, 0.1)
                move_x = (delta or random.randint(300, 350)) if back \
                    else random.randint(-350, -300)
                tab.actions.move_to(target, duration=0).move(
                    -300 if not back else 300, 0, 0).hold().move(
                    move_x, 0, duration).release()
                return True
            except Exception:  # noqa: BLE001 - 换下一个可拖目标
                continue
        return False

    @staticmethod
    def _page_indicator(tab) -> tuple[int, int]:
        """读页面上的 "3/9"，返回 (当前页, 总页)；读不到返回 (0, 0)。"""
        try:
            tags = find_eles(tab, _CONTAINER + '//span', timeout=0.5)
        except Exception:  # noqa: BLE001
            return 0, 0
        text = "".join((tag.text or "") for tag in tags)
        match = re.search(r"(\d+)\s*/\s*(\d+)", text)
        if not match:
            return 0, 0
        return int(match.group(1)), int(match.group(2))

    @staticmethod
    def _drain_packets(tab, rounds: int = 2) -> list[str]:
        """把缓冲里的图片包全部抽干。

        原来是 `wait(count=total+5)`：重复请求会占满配额，后面的图被截断。
        改成"连续几轮抽不到新包才停"，不设总量上限。
        """
        urls: list[str] = []
        empty = 0
        for _ in range(40):                 # 硬上限，防止死循环
            try:
                packets = _packet_list(tab.listen.wait(
                    timeout=0.6, count=32, fit_count=False))
            except Exception:  # noqa: BLE001
                break
            batch = DouyinPlatform._collect_images(packets)
            if not batch:
                empty += 1
                if empty >= rounds:
                    break
                continue
            empty = 0
            urls.extend(batch)
        return urls

    def _wait_total(self, tab, timeout: float = 6.0) -> int:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            tags = find_eles(tab, _CONTAINER + '//span', timeout=1)
            total = self._parse_page_total([(tag.text or "") for tag in tags])
            if total:
                return total
            time.sleep(0.3)
        return 0

    # --- 保存 ---------------------------------------------------------
    @staticmethod
    def _fetch_image(url: str, target, headers: dict | None):
        """图片下载逐级降级：带 referer → 去掉 referer → 完全裸请求。

        抖音图文 CDN 对 Referer 敏感：短链（v.douyin.com）当 referer 会被拒，
        而裸请求反而能取到。桌面端脚本一直是裸 requests，这里对齐。
        """
        attempts: list[dict | None] = []
        if headers:
            attempts.append(headers)
            stripped = {k: v for k, v in headers.items()
                        if k.lower() != "referer"}
            if stripped:
                attempts.append(stripped)
        attempts.append(None)

        last: Exception | None = None
        for attempt in attempts:
            try:
                return download_media(url, target, attempt)
            except Exception as exc:  # noqa: BLE001 - 换下一种头
                last = exc
        raise last or RuntimeError("图片下载失败")

    def _save_images(self, candidates: list[list[str]], name: str,
                     headers: dict, on_progress=None,
                     log=None) -> DownloadResult:
        """并发保存图片；返回的 files 始终按图片序号排列。"""
        log = log or _logger(None)
        folder = unique_dir(self.photo_folder() / name)
        folder.mkdir(parents=True, exist_ok=True)

        total = len(candidates)
        saved: dict[int, str] = {}
        lock = threading.Lock()
        finished = 0

        def report(done: int) -> None:
            if on_progress is None:
                return
            try:
                on_progress(Progress(done=done, total=total, unit="items"))
            except Exception:  # noqa: BLE001 - 进度回调不能影响下载
                pass

        def work(index: int, urls: list[str]) -> None:
            nonlocal finished
            for candidate in _order_candidates(urls):
                try:
                    path = self._fetch_image(candidate,
                                             folder / f"{index:02d}", headers)
                except Exception as exc:  # noqa: BLE001 - 换下一个地址
                    log(f"第 {index} 张候选取失败：{type(exc).__name__}")
                    continue
                with lock:
                    saved[index] = str(path)
                    finished += 1
                    done = finished
                report(done)
                return

            log(f"第 {index} 张所有候选都失败，已跳过", "error")
            with lock:
                finished += 1
                done = finished
            report(done)

        report(0)
        with ThreadPoolExecutor(max_workers=max(1, IMAGE_WORKERS)) as pool:
            for index, urls in enumerate(candidates, 1):
                pool.submit(work, index, urls)

        files = [saved[index] for index in sorted(saved)]
        if not files:
            raise RuntimeError("所有图片下载均失败")
        if len(files) < total:
            log(f"图片不完整：{len(files)}/{total}", "error")
        return DownloadResult(name=name, kind="photos", path=str(folder),
                              files=files,
                              extra={"expected": total, "saved": len(files)})

    @staticmethod
    def _collect_images(packets: list) -> list[str]:
        """按捕获顺序分组去重，每组挑画质最好的一张（不截断）。"""
        groups: dict[str, list[str]] = {}
        order: list[str] = []
        for packet in packets:
            image_url = getattr(packet, "url", "") or ""
            if not image_url or "FAVORITE" in image_url:
                continue
            key = _image_key(image_url)
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(image_url)
        return [max(groups[key], key=_quality) for key in order]

    @staticmethod
    def _parse_page_total(texts: list[str]) -> int:
        joined = " ".join(texts)
        match = re.search(r"(\d+)\s*/\s*(\d+)", joined)
        if match:
            total = int(match.group(2))
            if total > 0:
                return min(total, MAX_PAGES)

        # 没有 a/b 形式时，只接受合理范围内的数字，
        # 避免 "999+"、时长 "00:15" 之类把页数放大到上限
        numbers = [int(n) for n in re.findall(r"\d+", joined)]
        plausible = [n for n in numbers if 0 < n <= MAX_PAGES]
        return max(plausible) if plausible else 0


def _packet_list(raw) -> list:
    """listen.wait 可能返回单个包、列表或空值，统一成列表。"""
    if not raw:
        return []
    return raw if isinstance(raw, list) else [raw]


def _image_key(url: str) -> str:
    """同一张图的不同变体共享一个 key（tos-cn-i 后面的路径段）。"""
    match = _IMAGE_KEY.search(url)
    if match:
        return match.group(1)
    match = _URL_PATH.search(url)
    return match.group(1) if match else url


def _order_candidates(urls: list[str]) -> list[str]:
    """同一条目的多个地址按画质降序，保持同画质内的原始顺序。"""
    return sorted(dict.fromkeys(urls), key=_quality, reverse=True)


def _quality(url: str) -> int:
    """原图 > 未压缩 > 其它 > q75 预览图。"""
    if "~noop" in url:
        return 3
    if "~tplv" not in url:
        return 2
    if "q75" in url:
        return 0
    return 1


def _logger(on_log):
    """把 on_log 归一成 emit(message, level="info")，兼容单参回调。"""
    if on_log is None:
        return lambda *_args, **_kwargs: None

    def emit(message, level="info"):
        try:
            on_log(message, level)
        except TypeError:
            try:
                on_log(message)
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001 - 日志不能影响下载
            pass

    return emit
