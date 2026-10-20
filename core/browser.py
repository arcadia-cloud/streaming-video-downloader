"""浏览器生命周期与登录检测。

改动点：
- 不再使用 DrissionPage 的私有 `_wait_loaded()`，改用公开的 `page.wait.doc_loaded()`；
- 重复启动会先关掉旧实例，避免残留 Chrome 进程；
- 登录超时不再退出程序，只是回到未连接状态；
- 取 cookie 时用 `all_domains=True`，否则空白标签页拿不到目标站点的 cookie。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from core import urls as url_tools
from core.dp_tools import DpTools
from core.platforms import PLATFORMS

BROWSER_PORT = 9333      # 固定调试端口：既不蹭现成浏览器，也方便排查


class BrowserError(RuntimeError):
    pass


class BrowserManager:
    def __init__(self):
        self._page = None
        self._platform = PLATFORMS[0] if PLATFORMS else None
        self._browser_path = ""      # 实际用于启动的可执行文件

    # --- 状态 ---------------------------------------------------------
    @property
    def page(self):
        return self._page

    @property
    def platform(self):
        return self._platform

    def set_platform(self, platform) -> None:
        if platform is None or platform is self._platform:
            return
        self._platform = platform

    def get_platform_for_url(self, url: str):
        for platform in PLATFORMS:
            if platform.match_url(url):
                return platform
        return None

    # --- 启动 ---------------------------------------------------------
    # 小红书的分享页在 Chrome 里会渲染成"叠在信息流上的浮层"（图片走缓存、
    # 监听收不到），在 Edge 里是正常的详情页。没配 browser_path 时优先用 Edge。
    _EDGE_PATHS = (
        r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
        r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe",
    )

    @classmethod
    def _detect_edge(cls) -> str:
        for raw in cls._EDGE_PATHS:
            path = os.path.expandvars(raw)
            if os.path.exists(path):
                return path
        return ""

    @staticmethod
    def _configured_browser_path() -> str:
        try:
            from core import config as app_config

            return str(app_config.load().get("browser_path") or "").strip()
        except Exception:  # noqa: BLE001
            return ""

    def _launch_options(self):
        """显式配置优先；没配就优先 Edge，最后交给 DrissionPage 默认。"""
        path = self._configured_browser_path() or self._detect_edge()
        if not path:
            return None
        self._browser_path = path
        try:
            from DrissionPage import ChromiumOptions

            options = ChromiumOptions()
            options.set_browser_path(path)
            # 用固定的配置目录保存登录态。注意 DP 4.1 的方法名是
            # set_user_data_path（旧写法 set_user_data_dir 会抛 AttributeError，
            # 之前被 except 吞掉后回退成 auto_port，等于每次都是未登录状态）。
            profile = (Path(os.environ.get("APPDATA", Path.home()))
                       / "VideoDownloader" / "browser-profile")
            try:
                profile.mkdir(parents=True, exist_ok=True)
                setter = (getattr(options, "set_user_data_path", None)
                          or getattr(options, "set_user_data_dir", None))
                if setter is None:
                    raise AttributeError("没有可用的 user data 设置方法")
                setter(str(profile))
                options.set_local_port(BROWSER_PORT)
                self._prepare_profile(profile)
            except Exception:  # noqa: BLE001 - 退化为随机端口 + 临时目录
                try:
                    options.auto_port()
                except Exception:  # noqa: BLE001
                    pass
            # 不指定起始页时，Edge 会打开它自己的"新建标签页"默认页
            # （国内发行版就是百度），所以显式钉成 about:blank。
            # 起始页直接给平台首页：省掉"空白页 -> 再导航"这一跳，
            # 打开就有内容，不会白屏等半天。
            start = "about:blank"
            try:
                if self._platform is not None:
                    start = self._platform.login_url() or start
            except Exception:  # noqa: BLE001
                pass
            try:
                options.set_start_url(start)
            except Exception:  # noqa: BLE001
                pass
            for call, args in (
                ("set_argument", ("--no-first-run",)),
                ("set_argument", ("--no-default-browser-check",)),
                ("set_argument", ("--homepage=about:blank",)),
                ("set_argument", ("--disable-sync",)),
                # 启动页 / 新标签页的默认内容（含国内版百度合作页）
                ("set_argument", ("--disable-features=EdgeNewTabPage,"
                                  "MsEdgeNTP,msEdgeNTPFeed",)),
                # 末尾位置参数就是"启动时打开哪个地址"
                ("set_argument", (start,)),
            ):
                try:
                    getattr(options, call)(*args)
                except Exception:  # noqa: BLE001
                    pass
            return options
        except Exception:  # noqa: BLE001 - 路径无效时退回默认浏览器
            return None

    @staticmethod
    def _prepare_profile(profile: Path) -> None:
        """把配置目录里的启动页/主页改成 about:blank。

        Edge 的"启动时打开"和"主页"存在 Default/Preferences 里，
        默认值在国内发行版会把百度当作首页；这里在启动前直接改写。
        只动启动相关字段，不碰 cookie / 登录态。
        """
        prefs_path = profile / "Default" / "Preferences"
        prefs_path.parent.mkdir(parents=True, exist_ok=True)

        data: dict = {}
        if prefs_path.exists():
            try:
                data = json.loads(prefs_path.read_text("utf-8"))
                if not isinstance(data, dict):
                    data = {}
            except Exception:  # noqa: BLE001 - 文件损坏就重建
                data = {}

        startup = data.setdefault("browser", {}).setdefault("startup", {})
        startup["homepage"] = "about:blank"
        startup["homepage_is_newtabpage"] = False
        startup["restore_on_startup"] = 5        # 5 = 打开空白页
        data["homepage"] = "about:blank"
        data["homepage_is_newtabpage"] = False
        session = data.setdefault("session", {})
        session["restore_on_startup"] = 5
        session["startup_urls"] = []

        try:
            prefs_path.write_text(json.dumps(data, ensure_ascii=False),
                                  encoding="utf-8")
        except Exception:  # noqa: BLE001 - 写不了就算了，启动参数还有一层保险
            pass

    def browser_label(self) -> str:
        """当前实际使用的浏览器名：以 UA 为准，避免"配了没生效"看不出来。"""
        try:
            ua = str(self._page.run_js("navigator.userAgent") or "")
        except Exception:  # noqa: BLE001
            ua = ""
        if "Edg/" in ua:
            return "Edge"
        if "Chrome/" in ua:
            return "Chrome"
        path = (self._browser_path or self._configured_browser_path()
                or self._detect_edge())
        if not path:
            return "系统默认浏览器"
        lowered = path.lower()
        if "msedge" in lowered:
            return "Edge（配置）"
        if "chrome" in lowered:
            return "Chrome（配置）"
        return path.rsplit("\\", 1)[-1]

    def launch(self) -> None:
        if self._platform is None:
            raise BrowserError("没有可用的平台")

        try:
            from DrissionPage import ChromiumPage
        except ImportError as exc:
            raise BrowserError(
                "未安装 DrissionPage，请先执行 pip install -r requirements.txt"
            ) from exc

        if self._page is not None:
            self.quit()

        try:
            started = time.monotonic()
            options = self._launch_options()
            self._page = ChromiumPage(options) if options else ChromiumPage()
            # 浏览器刚起来时渲染器还没就绪，立刻 get 会落到"无法加载"的错误页，
            # 之后只能人工 F5。这里先等 JS 能执行，再导航。
            self._wait_ready(self._page)
            # 起始页已经是平台首页时不必再导航一次，省掉一次整页加载
            login_url = self._platform.login_url()
            try:
                current = self._page.url or ""
            except Exception:  # noqa: BLE001
                current = ""
            if current and current.split("?")[0].rstrip("/") == \
                    login_url.split("?")[0].rstrip("/"):
                self._wait_loaded(self._page)
            else:
                self._goto(self._page, login_url)
            self._last_launch_cost = time.monotonic() - started
        except Exception as exc:  # noqa: BLE001
            self._page = None
            raise BrowserError(f"浏览器启动失败：{exc}") from exc

    @staticmethod
    def _wait_ready(page, timeout: float = 8.0) -> bool:
        """等到页面能执行 JS 为止。

        注意 run_js 是把脚本当函数体执行，`1 + 1` 没有返回值（返回 None），
        必须写 `return 1 + 1`——之前漏了 return，每次都要空转满 8 秒才继续。
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if page.run_js("return 1 + 1") == 2:
                    return True
            except Exception:  # noqa: BLE001 - 还没就绪
                pass
            time.sleep(0.15)
        return False

    @staticmethod
    def is_error_page(page) -> bool:
        """是否是 Edge/Chrome 的"无法访问此页面"错误页。"""
        try:
            url = (page.url or "").lower()
        except Exception:  # noqa: BLE001
            return True
        if url.startswith(("edge-error", "chrome-error")) or "neterror" in url:
            return True
        try:
            return bool(page.ele("#main-frame-error", timeout=0.5))
        except Exception:  # noqa: BLE001
            return False

    def _goto(self, page, url: str, timeout: int = 25) -> None:
        """导航 + 错误页自动刷新一次。"""
        page.get(url, timeout=timeout)
        self._wait_loaded(page)
        if self.is_error_page(page):
            time.sleep(1.0)
            try:
                page.refresh()
                self._wait_loaded(page)
            except Exception:  # noqa: BLE001
                pass

    @staticmethod
    def _wait_loaded(page, timeout: int = 20) -> None:
        try:
            page.wait.doc_loaded(timeout=timeout)
        except Exception:  # noqa: BLE001 - 超时也继续，交给上层判断
            pass

    def wait_login(self, timeout: int = 90, on_tick=None,
                   should_stop=None) -> bool:
        """轮询登录状态。返回 True 表示已登录。"""
        page = self._page
        if page is None:
            return False

        if self._platform.is_logged_in(page):
            return True

        try:
            self._platform.click_login(page)
        except Exception:  # noqa: BLE001 - 登录按钮结构变化不应阻断流程
            pass

        deadline = time.time() + timeout
        while time.time() < deadline:
            if should_stop and should_stop():
                return False
            try:
                if self._platform.is_logged_in(page):
                    return True
            except Exception:  # noqa: BLE001
                pass
            time.sleep(1)
            if on_tick:
                on_tick(max(0, int(deadline - time.time())))
        return False

    # --- 存活检测 -----------------------------------------------------
    def is_alive(self) -> bool:
        """窗口是否还连着。用户手动关掉 Chrome 后这里会变 False。"""
        page = self._page
        if page is None:
            return False
        try:
            states = getattr(page, "states", None)
            alive = getattr(states, "is_alive", None)
            if alive is not None:
                return bool(alive)
            page.url                 # 断开时访问属性会抛
            return True
        except Exception:  # noqa: BLE001
            return False

    def ensure(self) -> bool:
        """清掉已失效的页面引用，返回当前是否还有可用窗口。

        不清的话，`page is None` 永远不成立，程序会一直以为浏览器还开着，
        既不重启也不报错。
        """
        if self._page is not None and not self.is_alive():
            self._page = None
        return self._page is not None

    # --- 下载辅助 -----------------------------------------------------
    def new_tab(self):
        if not self.is_alive():
            self._page = None
            raise BrowserError("浏览器窗口已关闭，请重新点击「开始下载」")
        try:
            # 显式 about:blank：不给地址时 Edge 会打开默认"新建标签页"
            # （国内发行版是百度），看起来像是程序乱开网页。
            # background=True：不抢焦点，下载过程中不会一直弹到前面
            return self._page.new_tab(url="about:blank", background=True)
        except TypeError:  # 老版本签名不同
            try:
                return self._page.new_tab("about:blank")
            except TypeError:
                return self._page.new_tab()

    def minimize(self) -> None:
        """把窗口缩到任务栏：登录完就不该一直在前面晃。"""
        page = self._page
        if page is None:
            return
        for action in ("mini", "hide"):
            try:
                getattr(page.set.window, action)()
                return
            except Exception:  # noqa: BLE001
                continue

    def restore(self) -> None:
        """需要用户操作（登录/扫码）时再拉回前台。"""
        page = self._page
        if page is None:
            return
        for action in ("normal", "show"):
            try:
                getattr(page.set.window, action)()
                return
            except Exception:  # noqa: BLE001
                continue

    def reset_tabs(self) -> int:
        """关掉多余标签页，但主页面本身不动；返回关闭数量。

        以前这里会把第一个标签导航到 about:blank，结果用户点开播放页时
        首页突然变成空白——没必要，保留用户原来的页面即可。
        关整个浏览器会丢登录态，所以只清理多余标签。
        """
        page = self._page
        if page is None:
            return 0

        try:
            tabs = page.get_tabs() or []
        except Exception:  # noqa: BLE001
            tabs = []

        keep_id = getattr(page, "tab_id", None)
        closed = 0
        for tab in tabs:
            # 明确保留主页面那个标签，其余关掉
            if keep_id is not None and getattr(tab, "tab_id", None) == keep_id:
                continue
            try:
                tab.close()
                closed += 1
            except Exception:  # noqa: BLE001
                pass
        return closed

    def headers(self, tab, referer: str) -> dict:
        cookies = []
        try:
            cookies = tab.cookies(all_domains=True)
        except Exception:  # noqa: BLE001
            pass
        user_agent = getattr(tab, "user_agent", None)
        return DpTools(ck_dict_li=cookies, referer=referer,
                       user_agent=user_agent).simp_cookie().build_headers()

    def quit(self) -> None:
        page, self._page = self._page, None
        if page is not None:
            try:
                page.quit()
            except Exception:  # noqa: BLE001
                pass

    # 域名认不出来时，用分享文案里的关键词兜底（新短链域名经常换）
    _PLATFORM_HINTS = (
        ("xiaohongshu", ("小红书", "xhslink", "xhscdn", "xhs")),
        ("douyin", ("抖音", "douyin")),
        ("bilibili", ("哔哩哔哩", "bilibili", "b 站", "b站")),
    )

    @classmethod
    def _guess_platform(cls, url: str, text: str):
        """域名没命中任何平台时，按链接本身 + 文案关键词猜一次。"""
        haystack = f"{url} {text}".lower()
        for name, keys in cls._PLATFORM_HINTS:
            if any(key in haystack for key in keys):
                return next((p for p in PLATFORMS if p.name == name), None)
        return None

    def parse_urls(self, text: str) -> list[str]:
        """单次扫描：按用户粘贴的先后顺序返回，平台混输也能保持原序。

        旧实现是"平台外层、链接内层"，结果永远是 B站→抖音→小红书，
        和粘贴顺序无关，混输时队列顺序全乱。
        """
        seen: set[str] = set()
        result: list[str] = []
        for candidate in url_tools.iter_candidates(text):
            platform = self.resolve_platform(candidate, text)
            if platform is None:
                continue
            full = platform.normalize_url(candidate)
            if full not in seen:
                seen.add(full)
                result.append(full)
        return result

    def resolve_platform(self, url: str, text: str = ""):
        """域名匹配优先；认不出来再用文案关键词兜底。"""
        for platform in PLATFORMS:
            if platform.match_url(url):
                return platform
        return self._guess_platform(url, text)
