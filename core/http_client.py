import requests
from lxml import etree
from requests.exceptions import RequestException


def http_get(url: str, headers: dict, timeout: int = 10,
             parse_html: bool = True):
    """发送 GET 请求，返回 (res, tree)。

    下载二进制文件时设 parse_html=False 跳过 HTML 解析。
    请求失败时抛出 RequestException。
    """
    try:
        res = requests.get(url=url, headers=headers, timeout=timeout)
        res.raise_for_status()
    except RequestException as e:
        print(f"请求失败 [{url}]: {e}")
        raise

    tree = etree.HTML(res.text) if parse_html else None
    return res, tree
