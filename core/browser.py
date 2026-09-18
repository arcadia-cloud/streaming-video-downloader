import time
import threading

from DrissionPage import ChromiumPage

from core.dp_tools import DpTools
from core.platforms import PLATFORMS

LOGIN_TIMEOUT = 40
LOGIN_WARN_COUNTDOWN = 10


class BrowserManager:
    """管理浏览器生命周期与平台登录状态。"""

    def __init__(self):
        self.page: ChromiumPage | None = None
        self._logged_in = False
        self.platform = PLATFORMS[0] if PLATFORMS else None

    @property
    def logged_in(self) -> bool:
        return self._logged_in

    def launch(self):
        self.page = ChromiumPage()
        self.page.get(self.platform.login_url())
        self.page._wait_loaded()

    def wait_for_login(self, on_status=None, on_countdown=None,
                       on_success=None, on_timeout=None):
        """等待用户登录，通过回调通知 GUI。"""

        def _worker():
            if self.platform.is_logged_in(self.page):
                self._logged_in = True
                if on_success:
                    on_success()
                return

            login_tag = self.page.ele(
                'xpath://div[@class="header-login-entry"]'
            )
            if login_tag:
                login_tag.click()

            for s in range(LOGIN_TIMEOUT):
                time.sleep(1)
                if self.platform.is_logged_in(self.page):
                    self._logged_in = True
                    if on_success:
                        on_success()
                    return
                if on_status:
                    on_status(s + 1)

            for countdown in range(LOGIN_WARN_COUNTDOWN, 0, -1):
                if on_countdown:
                    on_countdown(countdown)
                time.sleep(1)

            if on_timeout:
                on_timeout()

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        return t

    def get_headers(self, url: str) -> tuple[dict, object]:
        tab = self.page.new_tab(url)
        headers = DpTools(
            referer=tab.url,
            user_agent=tab.user_agent,
        ).build_headers()
        return headers, tab

    @staticmethod
    def get_platform_for_url(url: str):
        """根据 URL 匹配对应的平台。"""
        for p in PLATFORMS:
            if p.match_url(url):
                return p
        return None

    def parse_urls(self, text: str) -> list[str]:
        """解析所有平台的合法链接，自动补全简化链接，保持顺序去重。"""
        text = text.replace("\n", "|").replace("\r", "")
        parts = [p.strip() for p in text.split("|") if p.strip()]
        seen = set()
        urls = []
        for p in parts:
            platform = self.get_platform_for_url(p)
            if platform:
                full = platform.normalize_url(p)
                if full not in seen:
                    seen.add(full)
                    urls.append(full)
        return urls

    def quit(self):
        if self.page:
            self.page.quit()
            self.page = None
        self._logged_in = False
