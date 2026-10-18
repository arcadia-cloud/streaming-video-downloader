"""浏览器生命周期与登录检测。

改动点：
- 不再使用 DrissionPage 的私有 `_wait_loaded()`，改用公开的 `page.wait.doc_loaded()`；
- 重复启动会先关掉旧实例，避免残留 Chrome 进程；
- 登录超时不再退出程序，只是回到未连接状态；
- 取 cookie 时用 `all_domains=True`，否则空白标签页拿不到目标站点的 cookie。
"""

from __future__ import annotations

import time

from core.dp_tools import DpTools
from core.platforms import PLATFORMS


class BrowserError(RuntimeError):
    pass


class BrowserManager:
    def __init__(self):
        self._page = None
        self._platform = PLATFORMS[0] if PLATFORMS else None

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
    @staticmethod
    def _configured_browser_path() -> str:
        try:
            from core import config as app_config

            return str(app_config.load().get("browser_path") or "").strip()
        except Exception:  # noqa: BLE001
            return ""

    def _launch_options(self):
        """指定了 browser_path 时用它（例如 Edge），否则交给 DrissionPage 默认。"""
        path = self._configured_browser_path()
        if not path:
            return None
        try:
            from DrissionPage import ChromiumOptions

            options = ChromiumOptions()
            options.set_browser_path(path)
            return options
        except Exception:  # noqa: BLE001 - 路径无效时退回默认浏览器
            return None

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
            options = self._launch_options()
            self._page = ChromiumPage(options) if options else ChromiumPage()
            self._page.get(self._platform.login_url())
            try:
                self._page.wait.doc_loaded(timeout=25)
            except Exception:  # noqa: BLE001 - 超时也继续，交给登录检测
                pass
        except Exception as exc:  # noqa: BLE001
            self._page = None
            raise BrowserError(f"浏览器启动失败：{exc}") from exc

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
            # 后台开标签：不抢焦点，下载过程中不会一直弹到前面
            return self._page.new_tab(background=True)
        except TypeError:  # 老版本没有这个参数
            return self._page.new_tab(background=False)

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

    def parse_urls(self, text: str) -> list[str]:
        """按 PLATFORMS 顺序解析，并保持用户输入中的先后顺序。"""
        seen: set[str] = set()
        result: list[str] = []
        for platform in PLATFORMS:
            for url in platform.parse_urls(text):
                if url not in seen:
                    seen.add(url)
                    result.append(url)
        return result
