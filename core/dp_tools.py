"""把 DrissionPage 的 cookie 列表转换成请求头。"""

from __future__ import annotations

from core.http_client import DEFAULT_UA


class DpTools:
    def __init__(self, ck_dict_li: list | None = None,
                 cookie: str | None = None,
                 referer: str | None = None,
                 user_agent: str | None = None):
        self.ck_dict_li = ck_dict_li
        self.cookie = cookie
        self.referer = referer
        self.user_agent = user_agent

    def simp_cookie(self) -> "DpTools":
        """[{name, value}, ...] -> "a=1; b=2"。"""
        if not self.ck_dict_li:
            return self
        pairs = []
        for item in self.ck_dict_li:
            try:
                name, value = item["name"], item["value"]
            except (TypeError, KeyError):
                name, value = getattr(item, "name", None), getattr(item, "value", None)
            if name and value is not None:
                pairs.append(f"{name}={value}")
        if pairs:
            self.cookie = "; ".join(pairs)
        return self

    def build_headers(self) -> dict:
        return {
            "User-Agent": self.user_agent or DEFAULT_UA,
            "Referer": self.referer or "",
            **({"Cookie": self.cookie} if self.cookie else {}),
        }
