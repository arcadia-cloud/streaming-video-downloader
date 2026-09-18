import time
import threading

from DrissionPage import ChromiumPage

from core.dp_tools import DpTools

BILI_HOME = "https://www.bilibili.com/"
BILI_PREFIX = "https://www.bilibili.com/"
LOGIN_TIMEOUT = 40
LOGIN_WARN_COUNTDOWN = 10
INVALID_CHARS = r'\/:*?"<>|'


class BrowserManager:
    """管理浏览器生命周期与 Bilibili 登录状态。"""

    def __init__(self):
        self.page: ChromiumPage | None = None
        self._logged_in = False

    @property
    def logged_in(self) -> bool:
        return self._logged_in

    def launch(self):
        self.page = ChromiumPage()
        self.page.get(BILI_HOME)
        self.page._wait_loaded()

    def wait_for_login(self, on_status=None, on_countdown=None,
                       on_success=None, on_timeout=None):
        """等待用户登录，通过回调通知 GUI。"""

        def _worker():
            user_tag = self.page.ele('xpath://div[@class="header-login-entry"]')

            if not user_tag:
                self._logged_in = True
                if on_success:
                    on_success()
                return

            user_tag.click()

            for s in range(LOGIN_TIMEOUT):
                time.sleep(1)
                user_tag = self.page.ele(
                    'xpath://div[@class="header-login-entry"]'
                )
                if not user_tag:
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

    def get_video_name(self, tab) -> str | None:
        name_tag = tab.ele(
            'xpath://div[@class="video-info-title-inner"]/h1'
        )
        title = name_tag.attr('title') if name_tag else None
        return self._sanitize_filename(title) if title else None

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        if not name:
            return "anonymous"
        for c in INVALID_CHARS:
            name = name.replace(c, '_')
        return name

    @staticmethod
    def parse_urls(search: str) -> list[str]:
        search = search.replace("\n", "|").replace("\r", "")
        parts = [p.strip() for p in search.split("|") if p.strip()]
        seen = set()
        urls = []
        for p in parts:
            if p.startswith(BILI_PREFIX) and p not in seen:
                seen.add(p)
                urls.append(p)
        return urls

    def quit(self):
        if self.page:
            self.page.quit()
            self.page = None
        self._logged_in = False
