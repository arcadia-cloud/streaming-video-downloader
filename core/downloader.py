import os
import re
import json
import uuid

from moviepy import VideoFileClip, AudioFileClip

from core.http_client import http_get

BASE_DIR = os.environ.get("BILI_DOWNLOADER_DIR", r"D:\data")


class VideoDownloader:
    """Bilibili / 抖音视频下载器。"""

    def __init__(self, url: str | None = None,
                 headers: dict | None = None,
                 html: str | None = None,
                 video_name: str | None = None):
        self.url = url
        self.headers = headers
        self.html = html
        self.video_name = video_name

    def _extract_media_url(self, key: str, next_key: str) -> str:
        pattern = rf'"{key}"\s*:\s*(\[.+?])(?=\s*,\s*"{next_key}")'
        match = re.findall(pattern, self.html, flags=re.S)
        if not match:
            raise ValueError(f"未找到 {key} 链接")
        return json.loads(match[0])[0]["baseUrl"]

    def _download_file(self, url: str, path: str):
        res, _ = http_get(url=url, headers=self.headers,
                          timeout=10, parse_html=False)
        with open(path, "wb") as f:
            f.write(res.content)

    def bili_download(self):
        folder = os.path.join(BASE_DIR, "bili_video")
        os.makedirs(folder, exist_ok=True)

        vid = self._extract_media_url("video", "audio")
        aud = self._extract_media_url("audio", "dolby")

        task_id = uuid.uuid4().hex[:8]
        v_path = os.path.join(folder, f"vid_{task_id}.mp4")
        a_path = os.path.join(folder, f"aud_{task_id}.mp3")

        try:
            self._download_file(vid, v_path)
            self._download_file(aud, a_path)

            video_clip = VideoFileClip(v_path)
            audio_clip = AudioFileClip(a_path)
            final = video_clip.with_audio(audio_clip)
            out_path = os.path.join(folder, f"{self.video_name}.mp4")
            final.write_videofile(out_path)
            final.close()
            video_clip.close()
            audio_clip.close()
        finally:
            for p in (v_path, a_path):
                if os.path.exists(p):
                    os.remove(p)

    def dy_download(self):
        folder = os.path.join(BASE_DIR, "dy_video")
        os.makedirs(folder, exist_ok=True)

        res, _ = http_get(url=self.url, headers=self.headers,
                          timeout=10, parse_html=False)
        video_path = os.path.join(folder, f"{self.video_name}.mp4")
        with open(video_path, "wb") as f:
            f.write(res.content)
