"""小红书平台实现：图文笔记按张下载。

数据获取方式和桌面脚本一致——监听笔记图片请求（sns-webpic / notes_pre_post），
不解析详情接口；一次请求内通常就能拿到全部图片。

与原始脚本的差别：
- 等待数量按页面 `.fraction`（形如 `1/7`）里的总张数来定，不再写死 100；
- 以"拿到 total 张**去重后**的图"为停止条件，重复请求不会提前截断；
- 保留首次出现的顺序，文件名 01.jpg… 与页面翻页顺序一致；
- 图片下载先带 Referer 再退回裸请求（两个 CDN 的脾气不一样）；
- 视频笔记会给出明确提示，而不是静默存下封面。
"""

from __future__ import annotations

import random
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

from core import urls as url_tools
from core.http_client import DEFAULT_UA, download_media
from core.media import unique_dir
from core.models import DownloadResult, Progress
from core.platform_base import PlatformBase, find_ele

# 采集完全基于 DOM：轮播容器里的 <img> 的 currentSrc 就是真实 CDN 地址。
# 不再用 listen —— 实测（Edge 154 + DrissionPage 4.1）监听收不到任何请求，
# 而页面节点一直都在，跟是否发请求无关。
_NOISE = ("/avatar/", "sns-avatar", "fe-platform", "favicon", "emoji")

# 图片并发上限：浏览器对同一域名默认开 6 个连接，8 已是保守上限。
MAX_CONCURRENCY = 8

XHS_HOST = ("xiaohongshu.com", "xhslink.com")
FRACTION_XPATH = ('xpath://div[contains(@class,"fraction")]')
TITLE_XPATH = ('xpath://div[@id="detail-desc"]//span[contains(@class,"note-text")]')


class XiaohongshuPlatform(PlatformBase):
    name = "xiaohongshu"
    display_name = "小红书"
    url_prefix = "https://www.xiaohongshu.com/"
    sub_folder = "xhs_photo"
    host_suffixes = ("xiaohongshu.com", "xhslink.com",
                     "xiaohongshu.cn", "xhslink.cn")

    # --- 链接 ---------------------------------------------------------
    def match_url(self, url: str) -> bool:
        """宽松匹配：域名里带 xhslink / xiaohongshu / xhs 就认。

        分享短链的顶级域换过好几次（.com → .cn → …），按后缀白名单写死
        迟早漏；这里只看域名关键词，新域名不用改代码。
        """
        host = (urlparse(url_tools.normalize(url)).hostname or "").lower()
        if not host:
            return False
        return any(key in host for key in ("xhslink", "xiaohongshu", "xhs"))

    def login_url(self) -> str:
        return "https://www.xiaohongshu.com/explore"

    def is_logged_in(self, page) -> bool:
        """登录后页头不再有 login-btn；找不到才算登录成功。"""
        try:
            button = page.ele('xpath://button[@id="login-btn"]', timeout=1)
        except Exception:  # noqa: BLE001 - 页面没加载好时按未登录处理
            return False
        return not button

    def get_video_name(self, tab) -> str | None:
        for selector in (TITLE_XPATH, 'xpath://title'):
            element = find_ele(tab, selector, timeout=2)
            if not element:
                continue
            text = (element.text or "").strip()
            if text:
                return text.split("\n")[0][:60]
        return None

    # --- 下载 ---------------------------------------------------------
    def download(self, tab, url: str, headers: dict,
                 fallback_name: str, on_progress=None, on_log=None,
                 options=None) -> DownloadResult:
        log = make_log(tab, on_log)
        # 就在调用方给的标签页里跳转：监听是先开好的，不能换标签页/窗口，
        # 否则监听器绑在旧 tab 上，导航发生在别处，一个包都收不到。
        return self._download_in(tab, url, headers, fallback_name,
                                 on_progress, log)

    def _download_in(self, tab, url: str, headers: dict, fallback_name: str,
                     on_progress, log) -> DownloadResult:
        """全靠 DOM 解析：导航 -> 读轮播里的 <img> -> 按 .fraction 截断 -> 下载。

        不再使用 listen：实测该环境下收不到任何请求（Edge 154 + DP 4.1），
        而图片节点在页面里一直存在，src 就是真实 CDN 地址。
        """
        started = time.monotonic()

        # 短链先在后台跟一跳，拿到 /discovery/item/<id> 再交给浏览器：
        # 这样浏览器不经过 xhslink 的转介，不会渲染成"分享浮层"
        resolved = self._resolve_short(url)
        target = self._detail_url(resolved or url)
        if resolved:
            log(f"短链已解析：{target[:78]}")
        tab.get(target, timeout=25)
        try:
            tab.wait.doc_loaded(timeout=6)
        except Exception:  # noqa: BLE001
            pass
        if _page_failed(tab):
            log("页面没加载出来（错误页），自动刷新重试", "warn")
            time.sleep(1.0)
            try:
                tab.refresh()
                tab.wait.doc_loaded(timeout=15)
            except Exception:  # noqa: BLE001
                pass

        # 落地后如果又被改回 /explore/（带 app_share 参数），再纠一次。
        # 已经是 pc_feed 入口就不重复导航——那会白白多一次整页加载。
        landed = getattr(tab, "url", "") or ""
        fixed = self._detail_url(landed)
        if (fixed and fixed != landed
                and "xsec_source=pc_feed" not in landed):
            tab.get(fixed, timeout=25)
            try:
                tab.wait.doc_loaded(timeout=6)
            except Exception:  # noqa: BLE001
                pass
            log("已切换到笔记详情页（避开浮层）")

        total = self._fraction_total(tab)
        # 标题里常有 | \ : ? 这类字符（小红书笔记标题尤其爱用 |），
        # 必须先清洗，否则建目录直接 WinError 123
        name = self.sanitize_filename(self.get_video_name(tab)
                                      or fallback_name)
        if total:
            log(f"页面标注 {total} 张，开始采集")
        else:
            log("没读到页码（.fraction），按最多 30 张采集", "warn")

        order: list[str] = []
        best: dict[str, str] = {}

        def absorb(urls: list[str]) -> int:
            added = 0
            for candidate in urls:
                if not candidate:
                    continue
                key = _image_key(candidate)
                if key not in best:
                    best[key] = candidate
                    order.append(key)
                    added += 1
            return added

        # 轮播容器的 DOM 顺序就是 1/8、2/8 的翻页顺序，也是唯一干净的来源
        carousel = self._wait_images(tab)
        if carousel:
            absorb(carousel)
            log(f"轮播区读到 {len(carousel)} 张"
                f"（{time.monotonic() - started:.1f}s）")

        if not order:
            # 轮播选择器没命中：退一步扫整页的 <img>
            absorb(_harvest_dom(tab))

        # 轮播区排在最前面，超出的基本都是推荐位/别的规格变体
        if total and len(order) > total:
            dropped = len(order) - total
            order = order[:total]
            log(f"忽略 {dropped} 张非本篇图片", "warn")

        if order:
            log(f"采集到 {len(order)} 张")

        if not order:
            if _has_video(tab):
                raise ValueError("这是视频笔记，当前只支持图文笔记")
            if not self.is_logged_in(tab):
                raise ValueError(
                    "未登录或登录已失效：请先在浏览器里登录小红书再试")
            raise ValueError(
                f"没有采集到图片（页面标注 {total or '未知'} 张）。"
                "可能页面结构变了——把这一页的 HTML 片段发我，"
                "我按新的 class 改选择器")

        if total and len(order) < total:
            log(f"只采集到 {len(order)}/{total} 张", "warn")

        candidates = [best[key] for key in order]
        return self._save_images(candidates, name, headers, log, on_progress)

    # --- 辅助 ---------------------------------------------------------
    # 访问笔记只需要这两个参数；其余都是 App 分享带来的"浮层"标记
    _DETAIL_PARAMS = ("xsec_token", "xsec_source")

    @staticmethod
    def _resolve_short(url: str) -> str | None:
        """短链跟一跳，返回重定向目标（通常是 /discovery/item/<id>?…）。

        只发一个 HEAD/GET 就不再跟，避免落到登录页；拿不到就交给浏览器自己跳。
        """
        if "xhslink" not in (url or ""):
            return None
        try:
            import requests

            res = requests.get(
                url, headers={"User-Agent": DEFAULT_UA},
                timeout=4, allow_redirects=False,
            )
        except Exception:  # noqa: BLE001
            return None
        location = res.headers.get("Location") or ""
        if not location:
            return None
        return urljoin("https://www.xiaohongshu.com/", location)

    @classmethod
    def _detail_url(cls, url: str) -> str:
        """统一成"从 PC 信息流点进来"的地址：/explore/<id>?xsec_token=…&xsec_source=pc_feed

        同一篇笔记的四种链接只有 xsec_source 不同，而这个参数决定渲染形态：

        - `xsec_source=app_share`（含 app_platform=ios / xhsshare=CopyLink
          那一串）→ 按"App 分享"呈现：笔记叠在信息流上的浮层，图片直接吃
          内存缓存、不发请求，监听自然一无所获
        - `xsec_source=pc_feed` → 按"PC 信息流点进来"呈现：标准详情页，
          图片会走正常的 304 条件请求

        另外 `/discovery/item/<id>` 是旧的分享路由，前端会把它重写回
        `/explore/<id>` 浮层，所以这里也不用它。
        """
        text = url or ""
        match = re.search(r"/(?:explore|discovery/item)/([0-9a-fA-F]{16,})",
                          text)
        if not match:
            return text

        query = parse_qs(urlparse(text).query)
        token = (query.get("xsec_token") or [""])[0]
        params: dict[str, str] = {}
        if token:
            params["xsec_token"] = token
        params["xsec_source"] = "pc_feed"       # 强制成信息流入口

        base = f"https://www.xiaohongshu.com/explore/{match.group(1)}"
        return f"{base}?{urlencode(params)}"

    def _wait_images(self, tab, timeout: float = 6.0) -> list[str]:
        """轮询等轮播图出现：一出现就返回，不用干等固定超时。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            urls = _carousel_images(tab)
            if urls:
                return urls
            time.sleep(0.25)
        return []

    def _fraction_total(self, tab) -> int:
        """页面右下角的 `1/7`，取分母作为图片总数（最多等 1.5 秒）。"""
        element = find_ele(tab, FRACTION_XPATH, timeout=1.5)
        if not element:
            return 0
        return _parse_fraction(element.text or "")

    def _save_images(self, urls: list[str], name: str, headers: dict,
                     log, on_progress=None) -> DownloadResult:
        # 再清洗一次：调用方万一带了非法字符，也不会炸在建目录上
        folder = unique_dir(self.photo_folder() / self.sanitize_filename(name))
        folder.mkdir(parents=True, exist_ok=True)

        total = len(urls)
        saved: dict[int, str] = {}
        done = 0

        def fetch(item: tuple[int, str]) -> tuple[int, str | None]:
            index, url = item
            path = self._fetch_image(url, folder / f"{index:02d}", headers)
            return index, (str(path) if path else None)

        # 并发数按张数自适应：1 张没必要开线程，几十张才值得多开几路。
        workers = _concurrency(total)
        if total > 1:
            log(f"并发 {workers} 路下载 {total} 张")

        # 图片走静态 CDN，浏览器本身对同一域名就开 6 个连接，
        # 这里的并发不超过正常浏览行为，不存在风控问题。
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for index, path in pool.map(fetch, enumerate(urls, 1)):
                done += 1
                if path is None:
                    log(f"第 {index} 张下载失败，已跳过", "error")
                else:
                    saved[index] = path
                if on_progress:
                    on_progress(Progress(done=done, total=total, unit="items"))

        files = [saved[i] for i in sorted(saved)]
        if not files:
            raise ValueError("所有图片下载均失败")
        return DownloadResult(name=name, kind="photos", path=str(folder),
                              files=files, extra={"expected": total,
                                                  "saved": len(files)})

    @staticmethod
    def _fetch_image(url: str, target: Path, headers: dict | None):
        """带 Referer 试一次，不行再裸请求（小红书 CDN 两者都可能接受）。"""
        attempts = [headers, None] if headers else [None]
        for attempt in attempts:
            try:
                return download_media(url, target, attempt)
            except Exception:  # noqa: BLE001 - 换下一种头
                continue
        return None

    def photo_folder(self) -> Path:
        from core.config import download_dir

        base = download_dir()
        return base if base.name == self.sub_folder else base / self.sub_folder


# --- 模块级工具 -------------------------------------------------------
def _concurrency(total: int) -> int:
    """按图片张数决定并发路数。

    张数少的时候多开线程没有收益（启动开销反而更明显），
    张数多才值得并行；上限 8，不超过浏览器自己的连接数太多。
    """
    if total <= 1:
        return 1
    if total <= 3:
        return total
    if total <= 8:
        return 4
    if total <= 20:
        return 6
    return MAX_CONCURRENCY


def _parse_fraction(text: str) -> int:
    """把 `1/7` 解析成 7；`999+`、`视频` 之类一律返回 0。"""
    match = re.search(r"(\d+)\s*/\s*(\d+)", text or "")
    if not match:
        return 0
    total = int(match.group(2))
    return total if 1 <= total <= 100 else 0


def _image_key(url: str) -> str:
    """同一张图的不同规格共用 key。

    笔记图片形如 `.../nd_dft_wlteh_xxx.jpg!nd_dft_wgth_xxx`，
    `!` 后面只是规格参数，去掉后才好判重。
    """
    path = (url or "").split("?")[0].split("!")[0]
    name = path.rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[0] or path


def _carousel_images(tab) -> list[str]:
    """只读笔记轮播容器里的图，顺序即翻页顺序。

    页面上还有"相关推荐"等区域的图，它们同样走 sns-* CDN，
    混进来就会"照片不匹配"，所以按容器限定范围。
    """
    # 实测：轮播图的 src 就是真实 CDN 地址（1080x2348 已解码），
    # 但 Edge 154 + DrissionPage 4.1 下 listen 一个包都收不到。
    # 所以以 DOM 为准：直接读 currentSrc，顺序就是翻页顺序。
    js = """
        const sels = ['[class*=swiper] img', '[class*=note-slider] img',
                      '[class*=media-container] img'];
        for (const sel of sels) {
            const urls = [...document.querySelectorAll(sel)]
                .map(e => e.currentSrc || e.src || '')
                .filter(u => u.startsWith('http'));
            if (urls.length) return urls;
        }
        return [];
    """
    try:
        urls = list(tab.run_js(js) or [])
    except Exception:  # noqa: BLE001
        urls = []
    urls = [u for u in urls if u.startswith("http")
            and not any(n in u for n in _NOISE)]
    if urls:
        return urls

    # JS 不可用时的退路：按 xpath 抓
    selectors = (
        'xpath://div[contains(@class,"swiper")]//img',
        'xpath://div[contains(@class,"note-slider")]//img',
        'xpath://div[contains(@class,"media-container")]//img',
    )
    for selector in selectors:
        try:
            elements = find_eles(tab, selector, timeout=1)
        except Exception:  # noqa: BLE001
            elements = []
        found: list[str] = []
        for element in elements:
            src = (element.attr("src") or "").strip()
            if src.startswith("http") and not any(n in src for n in _NOISE):
                found.append(src)
        if found:
            return found
    return []


def _harvest_dom(tab) -> list[str]:
    """DOM 里已渲染的图：包没抓到时兜底（缓存命中不会再发请求）。"""
    try:
        elements = find_eles(tab, 'xpath://img[contains(@src,"xhscdn.com")]',
                             timeout=1)
    except Exception:  # noqa: BLE001
        return []
    urls: list[str] = []
    for element in elements:
        src = (element.attr("src") or "").strip()
        if not src.startswith("http"):
            continue
        if any(noise in src for noise in _NOISE):
            continue
        urls.append(src)
    return urls


def _has_video(tab) -> bool:
    return bool(find_ele(tab, 'xpath://video', timeout=1))


def _page_failed(tab) -> bool:
    """是否是浏览器"无法访问此页面"的错误页（需要刷新一次）。"""
    try:
        url = (tab.url or "").lower()
    except Exception:  # noqa: BLE001
        return True
    if url.startswith(("edge-error", "chrome-error")) or "neterror" in url:
        return True
    try:
        return bool(tab.ele("#main-frame-error", timeout=0.5))
    except Exception:  # noqa: BLE001
        return False


def make_log(tab, on_log):
    from core.platform_base import make_logger

    return make_logger(on_log)
