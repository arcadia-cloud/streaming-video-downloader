"""Bilibili 平台实现。

与旧实现最大的不同：不再用正则去 HTML 里抠 `"video":[...]`，
而是把 `window.__playinfo__` 整块 JSON 取出来解析。
旧写法要求 `"video"` 后紧邻 `"audio"`、`"audio"` 后紧邻 `"dolby"`，
字段顺序一变或数组为空就直接失败；现在按结构取值，并支持：
- 无音轨视频（只落视频文件，不调 ffmpeg）
- backupUrl 备用 CDN
- dash.audio / dolby.audio / flac.audio 三级回退

v8 增加合集 / 分P：
- 链接里的 `?p=N` 只决定从哪一集开始看，不代表整部合集；
- `options={"parts": [18, 19, 20]}` 时读 `__INITIAL_STATE__.videoData.pages`，
  只下载用户点名的分P，存到 `<标题>/18_分P标题.mp4`；
- 分P 之间只替换 URL 里的 `p=`，其余参数保持不变；
- 合集（`ugc_season`）每一集是不同 BV，用条目自带的地址；
- 点名的分P不存在只提示并跳过，不当作整条失败。
"""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path

from core import jsonx
from core.http_client import DEFAULT_UA, download_file, http_get
from core.media import merge_audio_video, unique_file
from core.models import DownloadResult, Progress
from core.platform_base import PlatformBase, find_ele, make_logger

QUALITY_LABELS = {
    127: "8K", 126: "杜比视界", 125: "HDR", 120: "4K",
    116: "1080P60", 112: "1080P+", 80: "1080P",
    74: "720P60", 64: "720P", 32: "480P", 16: "360P",
}

MAX_PARTS = 100

# 同一个 BV 只查一次接口，避免重复请求触发 412
_API_CACHE: dict[str, dict] = {}

_BARE_ID = re.compile(r"^(?:BV[0-9A-Za-z]{10}|av[0-9]{1,12})$", re.I)
_BVID = re.compile(r"(BV[0-9A-Za-z]{10})")
_PAGE_PARAM = re.compile(r"([?&])p=\d+", re.I)


class BilibiliPlatform(PlatformBase):
    name = "bilibili"
    display_name = "Bilibili"
    url_prefix = "https://www.bilibili.com/"
    sub_folder = "bili_video"
    host_suffixes = ("bilibili.com", "b23.tv")
    accent = "#FF7BA9"

    # --- 路由 ---------------------------------------------------------
    def match_url(self, url: str) -> bool:
        if _BARE_ID.match((url or "").strip()):
            return True
        return super().match_url(url)

    def normalize_url(self, url: str) -> str:
        text = (url or "").strip()
        if _BARE_ID.match(text):
            return f"https://www.bilibili.com/video/{text}"

        url = super().normalize_url(url)
        for scheme in ("https://", "http://"):
            if url.startswith(scheme + "bilibili.com"):
                return url.replace(scheme + "bilibili.com",
                                   scheme + "www.bilibili.com", 1)
        return url

    # --- 登录 ---------------------------------------------------------
    def login_url(self) -> str:
        return "https://www.bilibili.com/"

    UNLOGIN = 'xpath://div[contains(@class,"header-avatar-unlogin-entry")]'
    AVATAR = 'xpath://div[contains(@class,"header-avatar-wrap")]'

    def click_login(self, page) -> bool:
        entry = find_ele(page, self.UNLOGIN, timeout=3)
        if entry:
            try:
                entry.click()
                return True
            except Exception:  # noqa: BLE001
                return False
        return False

    def is_logged_in(self, page) -> bool:
        # 正向判定：有头像容器才算登录；找不到未登录入口不足以证明已登录
        if find_ele(page, self.AVATAR, timeout=1):
            return True
        return False

    # --- 元信息 -------------------------------------------------------
    def get_video_name(self, tab) -> str | None:
        tag = find_ele(
            tab,
            'xpath://div[contains(@class,"video-info-title")]//h1',
            'xpath://h1[contains(@class,"video-title")]',
            timeout=4,
        )
        if not tag:
            return None
        title = (tag.attr("title") or tag.text or "").strip()
        return self.sanitize_filename(title) if title else None

    # --- 下载 ---------------------------------------------------------
    def download(self, tab, url: str, headers: dict,
                 fallback_name: str, on_progress=None,
                 on_log=None, options: dict | None = None) -> DownloadResult:
        options = options or {}
        log = make_logger(on_log)

        wanted = options.get("parts") or []
        collect = bool(options.get("collect"))

        # 合集被界面拆成单集任务后，每个任务只下这一集：一次页面、一条进度
        episode = options.get("episode")
        if episode is not None:
            return self._download_episode(tab, url, headers, int(episode),
                                          fallback_name, on_progress, log)

        # 选集优先走公开接口：不开页面就能拿到标题和完整分P列表
        if collect:
            video = self._api_video(self._bvid(url))
            if video:
                episodes = self._episodes_of(video)
                if episodes:
                    log("已通过接口取得分P列表（未打开页面）")
                    name = (self.sanitize_filename(video.get("title") or "")
                            or self.sanitize_filename(fallback_name))
                    chosen = self._plan_episodes(episodes, wanted, log)
                    return self._download_pages(tab, url, headers, name,
                                                chosen, on_progress, log)

        self._open(tab, url)
        # 短链（b23.tv）跳转后才是真正的作品页；分集替换要在最终 URL 上做
        try:
            final_url = tab.url or url
        except Exception:  # noqa: BLE001
            final_url = url

        # 打开就先判断这一页是不是有效视频页，别等到解析失败才发现
        if self._page_state(tab) == "missing":
            if not (collect and wanted):
                raise ValueError("视频不存在或已被删除，请检查链接")
            log("打开的页面提示视频不存在，继续按你填的集数逐个尝试", "warn")

        name = self.get_video_name(tab) or self.sanitize_filename(fallback_name)

        if collect:
            chosen = self._plan_episodes(self._episodes(tab.html), wanted, log,
                                         hint=self._episode_hint(tab.html))
            return self._download_pages(tab, final_url, headers, name, chosen,
                                        on_progress, log)

        path, quality, cid = self._save_one(
            tab.html, headers, name, self.folder(), on_progress, log,
        )
        return DownloadResult(
            name=name, kind="video", path=str(path), files=[str(path)],
            extra={"quality": quality, "cid": cid},
        )

    # --- 选集计划 -----------------------------------------------------
    def _plan_episodes(self, episodes: list[dict], wanted: list[int],
                       log, hint: str = "") -> list[dict]:
        """决定这次下哪些集。

        有分P列表就按集数挑；没有列表但用户点了名，就直接改 p= 逐个试；
        两者都没有才报错。
        """
        request = ("全部" if not wanted else
                   "、".join(str(n) for n in wanted[:10])
                   + (f" 等 {len(wanted)} 个" if len(wanted) > 10 else ""))

        if episodes:
            total = len(episodes)
            log(f"检测到 {total} 个分P/选集，本次请求：{request}")
            chosen, missing = self._select_episodes(episodes, wanted)
            if missing:
                log("第 " + "、".join(str(n) for n in missing[:6])
                    + " 集不存在，已跳过", "warn")
            if not chosen:
                raise ValueError(f"指定的集数都不存在（该链接共 {total} 集）")
            return chosen

        if wanted:
            log("没解析到分P列表，按你填的集数直接替换 p= 逐个尝试", "warn")
            log(f"本次请求：{request}（未校验集数是否存在）")
            return [{"index": n, "title": "", "url": None} for n in wanted]

        suffix = f"（{hint}）。" if hint else "。"
        raise ValueError(
            "该链接里没有找到分P/合集列表，无法按集数下载"
            + suffix + "在右侧填上具体集数（如 18-20）就会直接按 p= 下载。")

    # --- 单集 ---------------------------------------------------------
    def _download_episode(self, tab, url: str, headers: dict, number: int,
                          fallback_name: str, on_progress, log) -> DownloadResult:
        """只下一集：换 p= → 打开 → 取标题 → 下载，全程一条进度。"""
        target = self._with_page(url, number)
        self._open(tab, target)

        if self._page_state(tab) == "missing":
            raise ValueError(f"第 {number} 集不存在（p={number}）")

        name = self.get_video_name(tab) or self.sanitize_filename(fallback_name)
        episode_title = self._episode_title(tab.html, number)
        title = self.sanitize_filename(episode_title or f"P{number}")
        stem = f"{number:02d}_{title}"
        folder = self.folder() / self.sanitize_filename(name)
        folder.mkdir(parents=True, exist_ok=True)

        path, quality, cid = self._save_one(
            tab.html, headers, stem, folder, on_progress, log,
        )
        return DownloadResult(
            name=f"{name} · P{number}", kind="video",
            path=str(path), files=[str(path)],
            extra={"quality": quality, "cid": cid},
        )

    @classmethod
    def _episode_title(cls, html: str, number: int) -> str:
        for episode in cls._episodes(html):
            if int(episode.get("index") or 0) == number:
                return episode.get("title") or ""
        return ""

    def _save_one(self, html: str, headers: dict, stem: str,
                  folder: Path, on_progress, log):
        """解析当前页的 DASH 并保存为 <folder>/<stem>.mp4。"""
        play = self._playinfo(html)
        dash = (play.get("data") or play).get("dash") or {}

        video = self._pick_video(dash.get("video") or [])
        if video is None:
            raise ValueError("解析不到视频流（可能需要登录，或该视频不可下载）")

        video_urls = _urls_of(video)
        audio = self._pick_audio(dash)
        quality = QUALITY_LABELS.get(video.get("id", 0),
                                     f"{video.get('height', '?')}P")

        folder.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex[:8]
        safe_stem = self.sanitize_filename(stem)
        video_tmp = folder / f".{safe_stem}.{token}.m4s"
        audio_tmp = folder / f".{safe_stem}.{token}.audio.m4s"
        out = unique_file(folder / f"{safe_stem}.mp4")

        try:
            download_file(video_urls[0], video_tmp, headers,
                          candidates=video_urls[1:], on_progress=on_progress)

            if audio is None:
                # 无音轨视频：直接落盘，不调用 ffmpeg
                video_tmp.replace(out)
            else:
                audio_urls = _urls_of(audio)
                download_file(audio_urls[0], audio_tmp, headers,
                              candidates=audio_urls[1:])
                merge_audio_video(video_tmp, audio_tmp, out)
        finally:
            for tmp in (video_tmp, audio_tmp):
                tmp.unlink(missing_ok=True)

        return out, quality, play.get("cid")

    # --- 合集 / 分P ---------------------------------------------------
    def _download_pages(self, tab, url: str, headers: dict, name: str,
                        episodes: list[dict], on_progress,
                        log) -> DownloadResult:
        total = min(len(episodes), MAX_PARTS)
        if len(episodes) > MAX_PARTS:
            log(f"选集过多（{len(episodes)}），只下载前 {MAX_PARTS} 集", "warn")

        folder = self.folder() / self.sanitize_filename(name)
        folder.mkdir(parents=True, exist_ok=True)

        files: list[str] = []
        failures: list[str] = []
        for index, episode in enumerate(episodes[:total], 1):
            number = int(episode.get("index") or index)
            title = self.sanitize_filename(episode.get("title") or f"P{number}")
            stem = f"{number:02d}_{title}"
            # 分P 之间只差 p= 这一个数字，换值即可，其余参数原样保留；
            # 合集里的每一集是不同 BV，用条目自带的 url
            target = episode.get("url") or self._with_page(url, number)
            log(f"[{index}/{total}] 第 {number} 集：{title}")
            self._open(tab, target)

            if self._page_state(tab) == "missing":
                failures.append(f"第{number}集 不存在")
                log(f"第 {number} 集不存在（p={number}），已跳过", "warn")
                if on_progress:
                    on_progress(Progress(done=index, total=total, unit="items"))
                continue

            try:
                path, _quality, _cid = self._save_one(
                    tab.html, headers, stem, folder, None, log,
                )
            except Exception as exc:  # noqa: BLE001 - 单集失败不放弃整部
                failures.append(f"第{number}集 {title}: {exc}")
                log(f"第 {number} 集失败：{exc}", "error")
                continue
            files.append(str(path))
            if on_progress:
                on_progress(Progress(done=index, total=total, unit="items"))

        if not files:
            raise ValueError("选集下载全部失败：" + "；".join(failures[:2]))

        summary = f"{len(files)}/{total} 集"
        if failures:
            summary += f"（{len(failures)} 集失败）"
        return DownloadResult(
            name=self.sanitize_filename(name), kind="video",
            path=str(folder), files=files, extra={"quality": summary},
        )

    @staticmethod
    def _open(tab, url: str) -> None:
        tab.get(url, timeout=25)
        try:
            tab.wait.doc_loaded(timeout=10)
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _bvid(url: str) -> str | None:
        match = _BVID.search(url or "")
        return match.group(1) if match else None

    def _api_video(self, bvid: str | None) -> dict | None:
        """不打开页面，用公开接口取标题与分P列表；失败返回 None。

        接口不需要登录，能拿到 title / pages / ugc_season，
        结构与页面里的 videoData 一致，所以复用同一套解析。
        接口有频率限制（频繁请求会返回 412），失败就交给调用方退回开页面。
        """
        if not bvid:
            return None
        if bvid in _API_CACHE:
            return _API_CACHE[bvid]

        url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
        headers = {"Referer": "https://www.bilibili.com/",
                   "User-Agent": DEFAULT_UA}
        for attempt in range(2):
            try:
                res = http_get(url, headers=headers, timeout=8, retries=0)
                payload = res.json()
            except Exception:  # noqa: BLE001 - 接口不可用就退回开页面
                if attempt == 0:
                    time.sleep(1.2)      # 412 多半是频率限制，退避一次
                continue
            if isinstance(payload, dict) and payload.get("code") == 0:
                data = payload.get("data")
                if isinstance(data, dict):
                    _API_CACHE[bvid] = data
                    return data
            break
        return None

    @staticmethod
    def _page_state(tab) -> str:
        """打开页面后先判一下：ok / missing / unknown。

        只做静态判断，不额外发请求：有 __playinfo__ 就是有效视频页，
        出现 B 站的 404 文案就是这一集不存在。
        """
        try:
            html = tab.html or ""
        except Exception:  # noqa: BLE001
            return "unknown"
        if "__playinfo__" in html:
            return "ok"

        head = html[:200000]
        try:
            title = tab.title or ""
        except Exception:  # noqa: BLE001
            title = ""
        markers = ("视频不见了", "没有知识存在的荒原", "视频不存在",
                   "抱歉，该视频已被删除", "404")
        if any(marker in head or marker in title for marker in markers):
            return "missing"
        return "unknown"

    @staticmethod
    def _pages(html: str) -> list[dict]:
        return BilibiliPlatform._pages_of(BilibiliPlatform._video_data(html))

    @staticmethod
    def _pages_of(video: dict) -> list[dict]:
        """分P：同一个 BV 下的多集（URL 用 ?p=N）。"""
        pages = (video or {}).get("pages") or []
        return [page for page in pages if isinstance(page, dict)]

    @staticmethod
    def _season_episodes(html: str) -> list[dict]:
        return BilibiliPlatform._season_of(BilibiliPlatform._video_data(html))

    @staticmethod
    def _season_of(video: dict) -> list[dict]:
        """合集：ugc_season 下多个不同 BV 的选集（URL 用各自 bvid）。"""
        season = (video or {}).get("ugc_season") or {}
        episodes: list[dict] = []
        for section in season.get("sections") or []:
            for item in (section or {}).get("episodes") or []:
                arc = (item or {}).get("arc") or {}
                bvid = item.get("bvid") or arc.get("bvid") or ""
                if not bvid:
                    continue
                episodes.append({
                    "index": len(episodes) + 1,
                    "title": item.get("title") or arc.get("title") or "",
                    "url": f"https://www.bilibili.com/video/{bvid}",
                })
        return episodes

    @classmethod
    def _episodes(cls, html: str) -> list[dict]:
        return cls._episodes_of(cls._video_data(html))

    @classmethod
    def _episodes_of(cls, video: dict) -> list[dict]:
        """统一成 [{index, title, url}]：优先分P，其次合集。"""
        pages = cls._pages_of(video)
        if len(pages) > 1:
            return [{"index": int(page.get("page") or i),
                     "title": page.get("part") or "",
                     "url": None}
                    for i, page in enumerate(pages, 1)]
        return cls._season_of(video)

    @staticmethod
    def _video_data(html: str) -> dict:
        state = BilibiliPlatform._initial_state(html)
        return (state or {}).get("videoData") or {}

    @classmethod
    def _episode_hint(cls, html: str) -> str:
        """解析不出选集时，把实际看到的数量报出来，避免只能猜。"""
        state = cls._initial_state(html)
        if state is None:
            return "页面里没有可解析的 __INITIAL_STATE__"
        video = state.get("videoData") or {}
        if not video:
            return "__INITIAL_STATE__ 里没有 videoData"
        pages = video.get("pages") or []
        sections = (video.get("ugc_season") or {}).get("sections") or []
        return f"pages={len(pages)}，ugc_season.sections={len(sections)}"

    @staticmethod
    def _select_episodes(episodes: list[dict],
                         wanted: list[int]) -> tuple[list[dict], list[int]]:
        """按用户填的集数挑选集。

        - 空列表表示"全部选集"
        - 只报告"选集内部缺失"的集数；超出总数的部分不算缺失，
          否则 `7-` 这种开区间会刷出一长串"不存在"
        """
        if not wanted:
            return list(episodes), []

        numbers = [int(episode.get("index") or 0) for episode in episodes]
        existing = set(numbers)
        top = max(numbers) if numbers else 0
        wanted_set = set(wanted)
        chosen = [episode for episode, number in zip(episodes, numbers)
                  if number in wanted_set]
        missing = [n for n in wanted if n not in existing and n <= top]
        return chosen, missing

    @staticmethod
    def _initial_state(html: str) -> dict | None:
        """`__INITIAL_STATE__` 不是严格 JSON（含 undefined），先替换再解析。"""
        index = (html or "").find("__INITIAL_STATE__")
        if index < 0:
            return None
        brace = html.find("{", index)
        if brace < 0:
            return None
        try:
            end = jsonx.object_end(html, brace)
        except ValueError:
            return None
        raw = html[brace:end + 1]
        # `undefined` 可能出现在对象值（":undefined"）也可能出现在数组里（",undefined]"），
        # 之前只处理了前者，遇到数组就直接解析失败，表现成"没有找到分P"
        candidates = (
            raw.replace(":undefined", ":null"),
            re.sub(r"(?<=[\[,:])\s*undefined\s*(?=[,\]}])", "null", raw),
        )
        for text in candidates:
            try:
                data = json.loads(text)
            except ValueError:
                continue
            return data if isinstance(data, dict) else None
        return None

    @staticmethod
    def _with_page(url: str, number: int) -> str:
        """把 URL 里的 p= 换成目标集号，其余参数原样保留。

        分集之间只差这一个数字，重建整条 URL 会丢掉 spm_id_from /
        vd_source 这类上下文，没必要冒这个风险。没有 p= 时补一个。
        """
        text = url or ""
        if _PAGE_PARAM.search(text):
            return _PAGE_PARAM.sub(rf"\g<1>p={number}", text, count=1)
        separator = "&" if "?" in text else "?"
        return f"{text}{separator}p={number}"

    # --- 解析 ---------------------------------------------------------
    @staticmethod
    def _playinfo(html: str) -> dict:
        for marker in ("window.__playinfo__=", "window.__playinfo__ ="):
            if marker in html:
                return jsonx.json_after(html, marker)
        raise ValueError("页面中没有 __playinfo__（可能需要登录，或页面已改版）")

    @staticmethod
    def _pick_video(items: list) -> dict | None:
        usable = [item for item in items if _urls_of(item)]
        if not usable:
            return None
        return max(usable, key=lambda it: (
            int(it.get("width") or 0) * int(it.get("height") or 0),
            int(it.get("bandwidth") or 0),
        ))

    @staticmethod
    def _pick_audio(dash: dict) -> dict | None:
        groups = [
            dash.get("audio") or [],
            (dash.get("dolby") or {}).get("audio") or [],
            (dash.get("flac") or {}).get("audio") or [],
        ]
        for group in groups:
            usable = [item for item in group if _urls_of(item)]
            if usable:
                return max(usable, key=lambda it: int(it.get("bandwidth") or 0))
        return None


def page_url(url: str, number: int) -> str:
    """对外暴露的"换集号"入口，供界面把合集拆成单集任务。"""
    return BilibiliPlatform._with_page(url, number)


def parse_parts(text: str) -> list[int] | None:
    """把 "3-7,9" 解析成集数列表。

    - 空串返回 []（表示"全部"，由调用方决定）
    - "3-7" 闭区间；"7-" 表示 7 到上限；"1,3,5" 离散
    - 无法解析返回 None（由界面报错，不静默变成"全部"）
    """
    raw = (text or "").strip().replace("，", ",").replace(" ", "")
    if not raw:
        return []

    numbers: list[int] = []
    for chunk in raw.split(","):
        if not chunk:
            continue
        if "-" in chunk:
            head, _, tail = chunk.partition("-")
            if not head.isdigit():
                return None
            if tail and not tail.isdigit():
                return None
            start = int(head)
            end = min(int(tail), MAX_PARTS) if tail else MAX_PARTS
            if start < 1 or end < start:
                return None
            numbers.extend(range(start, end + 1))
        else:
            if not chunk.isdigit():
                return None
            value = int(chunk)
            if value < 1:
                return None
            numbers.append(value)

    unique = sorted(set(numbers))
    return unique or None


def _urls_of(item: dict) -> list[str]:
    """baseUrl + backupUrl（兼容 snake_case）。"""
    urls: list[str] = []
    for key in ("baseUrl", "base_url"):
        value = item.get(key)
        if isinstance(value, str) and value:
            urls.append(value)
    for key in ("backupUrl", "backup_url"):
        value = item.get(key)
        if isinstance(value, list):
            urls.extend(u for u in value if isinstance(u, str) and u)
    return list(dict.fromkeys(urls))
