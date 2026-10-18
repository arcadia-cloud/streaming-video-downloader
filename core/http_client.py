"""HTTP 访问层：连接复用、受控重试、流式落盘、下载进度。

速度相关的几处收紧：
- 超时拆成（连接, 读取）两段，避免一次 connect 卡很久；
- 每个候选地址最多重试 1 次，且只尝试前 3 个候选，
  旧实现「3 个候选 × 3 次重试」最多会串行等几分钟；
- 下载过程中按块回报进度，界面能显示百分比与速度。
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Iterable

import requests

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

CHUNK_SIZE = 1 << 16
PROGRESS_INTERVAL = 0.25


class HttpError(RuntimeError):
    """网络请求失败（已重试）。"""


_local = threading.local()


def _session() -> requests.Session:
    """每线程一个 Session：requests.Session 不保证线程安全。

    图片改为并发下载后，共享连接池会出现偶发的读到错误响应；
    线程局部 Session 让每个 worker 各用各的连接池。
    """
    session = getattr(_local, "session", None)
    if session is None:
        session = requests.Session()
        session.headers.update({"Accept-Language": "zh-CN,zh;q=0.9"})
        _local.session = session
    return session


def _clean_headers(headers: dict | None) -> dict:
    return {k: v for k, v in (headers or {}).items() if v}


def http_get(url: str, headers: dict | None = None, timeout: int = 15,
             retries: int = 2) -> requests.Response:
    """GET 一个文本/JSON 资源，失败按次数重试。"""
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            res = _session().get(url, headers=_clean_headers(headers),
                               timeout=(8, timeout))
            res.raise_for_status()
            return res
        except requests.RequestException as exc:
            last = exc
            if attempt < retries:
                time.sleep(0.6 * (attempt + 1))
    raise HttpError(f"请求失败：{url}（{last}）")


def download_file(url: str, dest: str | Path, headers: dict | None = None,
                  timeout: tuple[int, int] = (10, 45), retries: int = 1,
                  candidates: Iterable[str] | None = None,
                  on_progress=None, max_candidates: int = 3) -> Path:
    """把 url 流式写入 dest。

    candidates 是备用地址（如 B 站 CDN 的 backupUrl），按顺序尝试；
    只取前 max_candidates 个，避免死链把时间耗光。
    """
    urls = [url]
    for extra in candidates or []:
        if extra and extra not in urls:
            urls.append(extra)
    urls = urls[:max_candidates]

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")

    errors: list[str] = []
    for candidate in urls:
        for attempt in range(retries + 1):
            try:
                _stream_to(candidate, part, headers, timeout, on_progress)
                part.replace(dest)
                return dest
            except Exception as exc:  # noqa: BLE001 - 逐个候选地址兜底
                errors.append(f"{type(exc).__name__}: {exc}")
                part.unlink(missing_ok=True)
                if attempt < retries:
                    time.sleep(0.8)

    raise HttpError("下载失败：" + "；".join(errors[-3:]))


def _stream_to(url: str, part: Path, headers: dict | None,
               timeout: tuple[int, int], on_progress=None) -> None:
    with _session().get(url, headers=_clean_headers(headers), timeout=timeout,
                      stream=True) as res:
        res.raise_for_status()
        expected = int(res.headers.get("Content-Length") or 0)
        written = 0
        last_emit = 0.0

        with open(part, "wb") as fh:
            for chunk in res.iter_content(CHUNK_SIZE):
                if not chunk:
                    continue
                fh.write(chunk)
                written += len(chunk)

                if on_progress is not None:
                    now = time.monotonic()
                    if now - last_emit >= PROGRESS_INTERVAL:
                        last_emit = now
                        _emit(on_progress, written, expected)

        if expected and written < expected:
            raise IOError(f"文件不完整（{written}/{expected} 字节）")
        if written == 0:
            raise IOError("响应内容为空")
        _emit(on_progress, written, expected or written, final=True)


def _emit(callback, written: int, total: int, final: bool = False) -> None:
    if callback is None:
        return
    try:
        from core.models import Progress

        callback(Progress(done=written, total=total, unit="bytes"))
    except Exception:  # noqa: BLE001 - 进度回调不能影响下载
        pass


def download_media(url: str, dest_stem: str | Path,
                   headers: dict | None = None, timeout: int = 30,
                   retries: int = 2, on_progress=None) -> Path:
    """下载图片等二进制资源，并按 Content-Type 决定扩展名。"""
    stem = Path(dest_stem)
    stem.parent.mkdir(parents=True, exist_ok=True)
    probe = stem.with_name(stem.name + ".probe")

    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with _session().get(url, headers=_clean_headers(headers),
                              timeout=(8, timeout), stream=True) as res:
                res.raise_for_status()
                ext = _ext_from_content_type(res.headers.get("Content-Type", ""))
                target = stem.with_suffix(ext)
                written = 0
                with open(probe, "wb") as fh:
                    for chunk in res.iter_content(CHUNK_SIZE):
                        if chunk:
                            fh.write(chunk)
                            written += len(chunk)
                if written == 0:
                    raise IOError("响应内容为空")
            probe.replace(target)
            return target
        except Exception as exc:  # noqa: BLE001
            last = exc
            probe.unlink(missing_ok=True)
            if attempt < retries:
                time.sleep(0.5)

    raise HttpError(f"资源下载失败：{url}（{last}）")


def _ext_from_content_type(content_type: str) -> str:
    ct = (content_type or "").lower()
    if "webp" in ct:
        return ".webp"
    if "png" in ct:
        return ".png"
    if "gif" in ct:
        return ".gif"
    if "avif" in ct:
        return ".avif"
    return ".jpg"
