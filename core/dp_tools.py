class DpTools:
    def __init__(self, ck_dict_li: list | None = None,
                 cookie: str | None = None,
                 referer: str | None = None,
                 user_agent: str | None = None):
        self.ck_dict_li = ck_dict_li
        self.cookie = cookie
        self.referer = referer
        self.user_agent = user_agent

    def simp_cookie(self):
        if not self.ck_dict_li:
            return self
        ck_li = [f"{dic['name']}={dic['value']}" for dic in self.ck_dict_li]
        self.cookie = "; ".join(ck_li)
        return self

    def build_headers(self):
        headers = {
            "User-Agent": self.user_agent,
            "Referer": self.referer,
        }
        if self.cookie:
            headers["Cookie"] = self.cookie
        return headers

    def build_sim_headers(self):
        return {
            "User-Agent": self.user_agent,
            "Referer": self.referer,
        }
