"""文件系统与 ffmpeg 小工具。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class MergeError(RuntimeError):
    pass


def unique_dir(path: Path) -> Path:
    """目录已存在时追加 (2)、(3)…，避免覆盖上一次的结果。"""
    if not path.exists():
        return path
    index = 2
    while True:
        candidate = path.with_name(f"{path.name} ({index})")
        if not candidate.exists():
            return candidate
        index += 1


def unique_file(path: Path) -> Path:
    """文件已存在时追加 (2)、(3)…"""
    if not path.exists():
        return path
    index = 2
    while True:
        candidate = path.with_name(f"{path.stem} ({index}){path.suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def ffmpeg_exe() -> str | None:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001 - 没装就退回 PATH 里的 ffmpeg
        return "ffmpeg"


def merge_audio_video(video: Path, audio: Path, out: Path) -> Path:
    """把 DASH 的视频流和音频流合并为 mp4。

    先尝试直接 copy 音频（DASH 音频本身是 AAC），失败再转码，
    最后仍失败则抛出带 ffmpeg 错误摘要的异常。
    """
    exe = ffmpeg_exe()
    if not exe:
        raise MergeError("未找到 ffmpeg，请先 pip install imageio-ffmpeg")

    out.parent.mkdir(parents=True, exist_ok=True)
    attempts = [
        ["-c:v", "copy", "-c:a", "copy"],
        ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k"],
    ]

    last_error = ""
    for audio_args in attempts:
        cmd = [
            exe, "-y", "-loglevel", "error",
            "-i", str(video), "-i", str(audio),
            *audio_args,
            "-movflags", "+faststart",
            str(out),
        ]
        proc = subprocess.run(
            cmd, capture_output=True, text=True, errors="ignore",
            creationflags=CREATE_NO_WINDOW,
        )
        if proc.returncode == 0 and out.exists() and out.stat().st_size > 0:
            return out
        lines = (proc.stderr or "").strip().splitlines()
        last_error = lines[-1] if lines else ""
        out.unlink(missing_ok=True)

    raise MergeError(f"ffmpeg 合并失败：{last_error or '未知错误'}")


def open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        os.startfile(str(path))  # noqa: S606 - 用户主动点击"打开目录"
    else:
        subprocess.Popen(["xdg-open", str(path)])
