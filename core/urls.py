"""从任意文本中提取受支持的链接。

用户可能粘贴：
- 每行一条，或用空格、|、逗号、顿号、分号分隔
- 抖音分享文案（"3.14 复制打开抖音…… https://v.douyin.com/xxx/"）
- 不带协议头的简化链接（bilibili.com/video/BV1xx、b23.tv/xxx）
- 多条链接直接连写（…BV1xxhttps://…BV1yy）
- 裸的 BV 号 / av 号（BV1xx411c7mD、av170001）

这里只负责"切出候选"，是否属于某平台交给各平台的 match_url。
"""

from __future__ import annotations

import re

# http(s) 链接；host 至少有一段点分域名，路径排除空白、CJK 与常见分隔符
# 注意保留半角 ? & = % #，这样 ?p=2 这类分P参数不会被丢掉
_CANDIDATE = re.compile(
    r"(?:https?://)?(?:[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,}"
    r"(?::\d+)?(?:/[^\s\u4e00-\u9fff|,，、；;！？）)】\]\"'<>]*)?"
)

# 裸 BV / av 号
_BARE_ID = re.compile(r"(?:BV[0-9A-Za-z]{10}|av[0-9]{1,12})", re.I)

_TRAILING = ".,;:!?)]}>\"'，。、；：！？）】》"
_ID_NEIGHBORS = "/?=&-_."


def _prepared(text: str) -> str:
    """把粘连的协议头拆开：a.com/xhttps://b -> a.com/x\\nhttps://b。"""
    return re.sub(r"https?://", lambda m: "\n" + m.group(0), text or "")


def iter_candidates(text: str):
    """按出现顺序产出候选链接（已去掉尾部标点）。"""
    for match in _CANDIDATE.finditer(_prepared(text)):
        raw = match.group(0).strip().rstrip(_TRAILING)
        if raw:
            yield raw

    source = text or ""
    for match in _BARE_ID.finditer(source):
        start, end = match.span()
        before = source[start - 1] if start else " "
        after = source[end] if end < len(source) else " "
        # 跳过 URL 里的 BV 号，只认独立出现的
        if before in _ID_NEIGHBORS or after in _ID_NEIGHBORS:
            continue
        yield match.group(0)


def normalize(url: str) -> str:
    url = url.strip()
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    return url
