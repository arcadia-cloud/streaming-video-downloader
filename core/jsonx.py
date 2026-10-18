"""从不规整的文本里安全地取出一个 JSON 对象。

用于解析页面里内嵌的 `window.__playinfo__=...` 这类大对象：
先定位起始 '{'，再用括号配平 + 字符串状态机找到结束位置，
比正则 `\\{.+?\\}` 可靠得多（后者遇到嵌套对象必然截断）。
"""

from __future__ import annotations

import json
from typing import Any


def object_end(text: str, start: int) -> int:
    """返回从 text[start]（必须是 '{'）开始的完整 JSON 对象的结束下标。"""
    if start < 0 or start >= len(text) or text[start] != "{":
        raise ValueError("起点不是 JSON 对象")

    depth = 0
    in_string = False
    escaped = False

    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i

    raise ValueError("JSON 对象没有闭合")


def json_after(text: str, marker: str) -> Any:
    """在 marker 之后找到第一个 JSON 对象并解析。"""
    idx = text.find(marker)
    if idx < 0:
        raise ValueError(f"页面中未找到 {marker}")

    brace = text.find("{", idx + len(marker))
    if brace < 0:
        raise ValueError(f"{marker} 之后没有 JSON 对象")

    end = object_end(text, brace)
    return json.loads(text[brace:end + 1])


def find_key(obj: Any, keys: tuple[str, ...]) -> Any:
    """在嵌套结构里深度优先查找第一个命中的键。"""
    if isinstance(obj, dict):
        for key in keys:
            value = obj.get(key)
            if isinstance(value, dict):
                return value
        for value in obj.values():
            found = find_key(value, keys)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = find_key(value, keys)
            if found is not None:
                return found
    return None
