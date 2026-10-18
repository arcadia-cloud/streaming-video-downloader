"""纯逻辑回归测试（不依赖浏览器、不联网）。

运行：python tests/test_core.py
覆盖旧版本里最容易出错的几处解析：
- 内嵌 JSON 的括号配平
- 分享文案 / 简化链接的提取
- 文件名清洗
- 抖音图文总页数、图片去重与画质选择
- B 站媒体地址挑选（含空数组、缺失 dolby）
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import jsonx, urls  # noqa: E402
from core.platform_base import PlatformBase  # noqa: E402
from core.platforms.bilibili import (BilibiliPlatform, _urls_of,  # noqa: E402
                                     parse_parts)
from core.platforms.douyin import DouyinPlatform, _image_key  # noqa: E402


class FakePacket:
    def __init__(self, url: str):
        self.url = url


class FakeTab:
    """只提供 _page_state 需要的两个属性。"""

    def __init__(self, html_text: str = "", url: str = "https://www.douyin.com/"):
        self.html = html_text
        self.url = url


# ---------------------------------------------------------------- jsonx
def test_json_after_handles_nesting():
    html = ('<script>window.__playinfo__='
            '{"code":0,"data":{"dash":{"video":[{"baseUrl":"v"}],'
            '"audio":[]}}};</script>')
    data = jsonx.json_after(html, "window.__playinfo__=")
    assert data["data"]["dash"]["video"][0]["baseUrl"] == "v"
    assert data["data"]["dash"]["audio"] == []


def test_json_after_handles_escaped_braces():
    html = 'x = {"t":"含 } 和 \\" 引号","n":{"a":1}} tail'
    data = jsonx.json_after(html, "x =")
    assert data["n"]["a"] == 1
    assert "}" in data["t"]


def test_find_key_deep():
    payload = {"a": {"b": {"aweme_detail": {"aweme_id": "1"}}}}
    assert jsonx.find_key(payload, ("aweme_detail",))["aweme_id"] == "1"


# ---------------------------------------------------------------- urls
def test_share_text_extraction():
    text = ("3.14 复制打开抖音，看看【某人】的作品 "
            "https://v.douyin.com/AbCdEf/ 复制此链接，打开Dou音搜索")
    candidates = list(urls.iter_candidates(text))
    assert "https://v.douyin.com/AbCdEf/" in candidates


def test_simplified_link_normalized():
    platform = BilibiliPlatform()
    got = platform.parse_urls("bilibili.com/video/BV1xx411c7mD")
    assert got == ["https://www.bilibili.com/video/BV1xx411c7mD"]


def test_mixed_input_routing():
    text = ("https://www.bilibili.com/video/BV1xx411c7mD\n"
            "https://v.douyin.com/AbCdEf/\n"
            "https://v.douyin.com/AbCdEf/")
    bili = BilibiliPlatform().parse_urls(text)
    dy = DouyinPlatform().parse_urls(text)
    assert bili == ["https://www.bilibili.com/video/BV1xx411c7mD"]
    assert dy == ["https://v.douyin.com/AbCdEf/"]


def test_hostname_matching_not_substring():
    platform = DouyinPlatform()
    assert platform.match_url("https://www.douyin.com/video/123")
    assert platform.match_url("https://v.douyin.com/abc/")
    assert not platform.match_url("https://evil.com/?ref=douyin.com")


def test_glued_links_are_split():
    glued = ("https://www.bilibili.com/video/BV1xx411c7mD"
             "https://www.bilibili.com/video/BV1yy411c7mE")
    assert len(BilibiliPlatform().parse_urls(glued)) == 2


def test_bare_video_ids():
    platform = BilibiliPlatform()
    assert platform.parse_urls("BV1xx411c7mD") == [
        "https://www.bilibili.com/video/BV1xx411c7mD"]
    assert platform.parse_urls("av170001") == [
        "https://www.bilibili.com/video/av170001"]


def test_query_params_kept_and_no_double_count():
    urls = BilibiliPlatform().parse_urls(
        "https://www.bilibili.com/video/BV1xx411c7mD?p=2")
    assert urls == ["https://www.bilibili.com/video/BV1xx411c7mD?p=2"]


def test_folder_avoids_double_nesting():
    os.environ["BILI_DOWNLOADER_DIR"] = r"D:\data\bili_video"
    try:
        folder = BilibiliPlatform().folder()
        assert folder.name == "bili_video"
        assert folder.parent.name == "data"

        folder = DouyinPlatform().photo_folder()
        assert folder.name == "dy_photo"
    finally:
        os.environ.pop("BILI_DOWNLOADER_DIR", None)


# ---------------------------------------------------------------- filename
def test_sanitize_filename():
    assert PlatformBase.sanitize_filename('a/b:c*?"<>|') == "a_b_c______"
    assert PlatformBase.sanitize_filename("CON") == "_CON"
    assert PlatformBase.sanitize_filename("   ") == "untitled"
    long_name = "长" * 200
    assert len(PlatformBase.sanitize_filename(long_name)) <= 90


# ---------------------------------------------------------------- douyin
def test_douyin_page_total():
    parse = DouyinPlatform._parse_page_total
    assert parse(["1/9"]) == 9
    assert parse(["1", " / ", "12"]) == 12
    assert parse(["第 1/9 页"]) == 9
    assert parse(["共 9 页"]) == 9
    assert parse([]) == 0


def test_douyin_image_order_and_quality():
    packets = [
        FakePacket("https://p3-pc-sign.douyinpic.com/tos-cn-i-0813/oAAA"
                   "~tplv-dy-aweme-images:q75.webp?biz=1"),
        FakePacket("https://p3-pc-sign.douyinpic.com/tos-cn-i-0813/oAAA"
                   "~noop.webp?biz=1"),
        FakePacket("https://p3-pc-sign.douyinpic.com/tos-cn-i-0813/oBBB"
                   "~tplv-dy-aweme-images:q75.webp?biz=1"),
    ]
    picked = DouyinPlatform._collect_images(packets)
    assert len(picked) == 2
    # 第一组保留原图，第二组只剩压缩图也只能用它；顺序按首次出现
    assert "oAAA" in picked[0] and "~noop" in picked[0]
    assert "oBBB" in picked[1]


def test_douyin_dedup_is_stable():
    packets = [
        FakePacket("https://p3-pc-sign.douyinpic.com/tos-cn-i-0813/oAAA"
                   "~tplv-dy-aweme-images:q75.webp?biz=1"),
        FakePacket("https://p3-pc-sign.douyinpic.com/tos-cn-i-0813/oAAA"
                   "~tplv-dy-aweme-images:q100.webp?biz=1"),
    ]
    first = DouyinPlatform._collect_images(packets)
    for _ in range(5):
        assert DouyinPlatform._collect_images(packets) == first


def test_douyin_page_total_ignores_implausible():
    parse = DouyinPlatform._parse_page_total
    assert parse(["999+"]) == 0          # 不能被放大成上限
    assert parse(["1/99"]) == 30         # 正常 a/b 仍按上限截断


def test_douyin_image_nodes_field_paths():
    node = {"url_list": ["https://x/1.jpg"]}
    assert DouyinPlatform._image_nodes({"images": [node]})[1] == "images"
    nested = {"image_post_info": {"images": [node]}}
    assert DouyinPlatform._image_nodes(nested)[1] == "image_post_info.images"
    assert DouyinPlatform._image_nodes({"images": []}) == ([], None)


def test_douyin_aweme_id():
    assert DouyinPlatform._aweme_id(
        "https://www.douyin.com/video/7123456789012345678"
    ) == "7123456789012345678"
    assert DouyinPlatform._aweme_id(
        "https://www.douyin.com/user/x?modal_id=7123456789012345678"
    ) == "7123456789012345678"
    assert DouyinPlatform._aweme_id("https://v.douyin.com/AbCdEf/") is None


def test_douyin_video_prefers_play_addr():
    aweme = {"video": {"play_addr": {"url_list": ["https://play"]},
                       "download_addr": {"url_list": ["https://wm"]}}}
    urls, watermarked = DouyinPlatform._video_urls(aweme)
    assert urls == ["https://play"] and watermarked is False

    only_wm = {"video": {"download_addr": {"url_list": ["https://wm"]}}}
    urls, watermarked = DouyinPlatform._video_urls(only_wm)
    assert urls == ["https://wm"] and watermarked is True


def test_douyin_name_from_desc():
    platform = DouyinPlatform()
    assert platform._name_from_aweme(
        {"desc": "  我的 作品 / 合集  "}) == "我的 作品 _ 合集"
    assert platform._name_from_aweme({}) is None
    assert platform._name_from_aweme({"desc": "   "}) is None


def test_douyin_image_key_variants():
    head = "https://p3-pc-sign.douyinpic.com/tos-cn-i-0813/"
    assert _image_key(head + "oAAA~tplv-dy:q75.webp?b=1") == "oAAA"
    assert _image_key(head + "oAAA~noop.webp?b=1") == "oAAA"
    # 没有 ~tplv/~noop 时也不该把整条 URL 当 key
    assert _image_key(
        "https://p3-pc-sign.douyinpic.com/plain/oBBB.jpeg"
    ) == "oBBB.jpeg"


def test_douyin_page_state_reasons():
    state = DouyinPlatform._page_state
    assert "登录" in state(FakeTab("<div>扫码登录</div>"))
    assert "风控" in state(FakeTab("<div>请完成验证</div>"))
    assert "作品不存在" in state(FakeTab("<div>作品不存在</div>"))
    assert "没有作品结构" in state(FakeTab("<html><body>x</body></html>", "https://a/b"))


# ---------------------------------------------------------------- bilibili
def test_bilibili_urls_include_backup():
    item = {"baseUrl": "https://a", "backupUrl": ["https://b", "https://c"]}
    assert _urls_of(item) == ["https://a", "https://b", "https://c"]


def test_bilibili_pick_video_prefers_biggest():
    items = [
        {"baseUrl": "https://low", "width": 640, "height": 360,
         "bandwidth": 500},
        {"baseUrl": "https://high", "width": 1920, "height": 1080,
         "bandwidth": 3000},
    ]
    assert BilibiliPlatform._pick_video(items)["baseUrl"] == "https://high"
    assert BilibiliPlatform._pick_video([]) is None


def test_bilibili_audio_fallbacks():
    dash = {"audio": [], "dolby": {"audio": [{"baseUrl": "https://dolby"}]}}
    assert BilibiliPlatform._pick_audio(dash)["baseUrl"] == "https://dolby"

    assert BilibiliPlatform._pick_audio({"audio": []}) is None

    dash = {"audio": [{"baseUrl": "https://a1", "bandwidth": 100},
                      {"baseUrl": "https://a2", "bandwidth": 300}]}
    assert BilibiliPlatform._pick_audio(dash)["baseUrl"] == "https://a2"


def test_bilibili_playinfo_parse():
    html = ('<script>window.__playinfo__ = {"code":0,"data":{"dash":'
            '{"video":[{"baseUrl":"https://v","id":80,"width":1920,'
            '"height":1080}],"audio":[{"baseUrl":"https://a"}]}}}</script>')
    play = BilibiliPlatform._playinfo(html)
    assert play["data"]["dash"]["video"][0]["id"] == 80


def test_bilibili_initial_state_pages():
    # __INITIAL_STATE__ 不是严格 JSON：里面会有 undefined
    html = ('<script>window.__INITIAL_STATE__={"videoData":{"pages":['
            '{"page":1,"part":"第一集","cid":1},'
            '{"page":2,"part":"第二集","cid":2}],"extra":undefined}};</script>')
    pages = BilibiliPlatform._pages(html)
    assert [p["page"] for p in pages] == [1, 2]
    assert pages[1]["part"] == "第二集"

    # 单集没有 pages 数组
    assert BilibiliPlatform._pages('<script>window.__INITIAL_STATE__='
                                  '{"videoData":{"pages":[]}};</script>') == []


def test_bilibili_with_page():
    f = BilibiliPlatform._with_page
    # 有 p=：只换数字，其余参数原样保留
    assert f("https://www.bilibili.com/video/BV1eY4y1W7Gd/"
             "?spm_id_from=333.788.videopod.episodes&p=7&vd_source=abc", 18) == \
        "https://www.bilibili.com/video/BV1eY4y1W7Gd/" \
        "?spm_id_from=333.788.videopod.episodes&p=18&vd_source=abc"
    # 没有 p=：补一个
    assert f("https://www.bilibili.com/video/BV1xx411c7mD", 3) == \
        "https://www.bilibili.com/video/BV1xx411c7mD?p=3"
    # 已有其他参数但没有 p=
    assert f("https://www.bilibili.com/video/BV1xx411c7mD?v=1", 2) == \
        "https://www.bilibili.com/video/BV1xx411c7mD?v=1&p=2"
    # 两位数 p 也要整体替换，不能只改末位
    assert f("https://www.bilibili.com/video/BV1xx?p=7", 18).endswith("p=18")


def test_bilibili_parse_parts():
    parse = parse_parts
    assert parse("3-7") == [3, 4, 5, 6, 7]
    assert parse("1,3,5") == [1, 3, 5]
    assert parse("3-5,9") == [3, 4, 5, 9]
    assert parse("  7  ") == [7]
    assert parse("") == []                  # 空 = 不限制，下当前这一集
    assert parse("1，3") == [1, 3]          # 中文逗号也认
    assert parse("7-")[0] == 7              # 开区间：7 到上限
    assert parse("abc") is None             # 无法解析 -> 界面报错
    assert parse("5-3") is None
    assert parse("0") is None


def test_bilibili_select_episodes():
    eps = [{"index": 1, "title": "a"}, {"index": 2, "title": "b"},
           {"index": 3, "title": "c"}]
    chosen, missing = BilibiliPlatform._select_episodes(eps, [2, 3])
    assert [e["index"] for e in chosen] == [2, 3]
    assert missing == []

    # 超出总数的部分不算"缺失"，避免 7- 刷屏
    chosen, missing = BilibiliPlatform._select_episodes(eps, [2, 5])
    assert [e["index"] for e in chosen] == [2]
    assert missing == []

    # 选集内部真缺一集（1、2、4，缺 3）才要报
    gap = [{"index": 1}, {"index": 2}, {"index": 4}]
    chosen, missing = BilibiliPlatform._select_episodes(gap, [3])
    assert chosen == [] and missing == [3]

    # 勾了但没填集数 → 全部
    chosen, missing = BilibiliPlatform._select_episodes(eps, [])
    assert chosen == eps and missing == []


def test_bilibili_episodes_sources():
    # 多个分P：优先用 pages，URL 留空（由调用方拼 ?p=N）
    multi = ('<script>window.__INITIAL_STATE__={"videoData":{"pages":['
             '{"page":1,"part":"a"},{"page":2,"part":"b"}],'
             '"ugc_season":null}};</script>')
    eps = BilibiliPlatform._episodes(multi)
    assert [e["index"] for e in eps] == [1, 2]
    assert eps[0]["url"] is None

    # 只有一个分P、但有合集：退回 ugc_season，每条用自己的 bvid
    season = ('<script>window.__INITIAL_STATE__={"videoData":{"pages":['
              '{"page":1,"part":"P1"}],"ugc_season":{"sections":[{"episodes":['
              '{"bvid":"BV1aa","title":"第一话"},'
              '{"bvid":"BV1bb","title":"第二话"}]}]}}};</script>')
    eps = BilibiliPlatform._episodes(season)
    assert [e["index"] for e in eps] == [1, 2]
    assert eps[1]["url"].endswith("BV1bb")

    # 两者都没有 → 空（调用方负责报"无法按集数下载"）
    plain = ('<script>window.__INITIAL_STATE__={"videoData":{"pages":'
             '[{"page":1,"part":"P1"}]}};</script>')
    assert BilibiliPlatform._episodes(plain) == []


def test_bilibili_initial_state_tolerates_undefined():
    # undefined 出现在数组里（旧实现只处理 ":undefined"，这里会整体解析失败）
    html = ('<script>window.__INITIAL_STATE__={"videoData":{"pages":['
            '{"page":1,"part":"a"},{"page":2,"part":"b"}],'
            '"extra":[1,undefined]}};</script>')
    state = BilibiliPlatform._initial_state(html)
    assert state is not None, "数组里的 undefined 不该导致整体解析失败"
    assert len(BilibiliPlatform._pages(html)) == 2

    # 真正缺失时，诊断信息要能说明是哪儿没了
    assert "没有可解析" in BilibiliPlatform._episode_hint("<html></html>")


def test_bilibili_page_state():
    class Tab:
        def __init__(self, html, title=""):
            self.html = html
            self.title = title

    state = BilibiliPlatform._page_state
    assert state(Tab('<script>window.__playinfo__={"data":{}}</script>')) == "ok"
    assert state(Tab("你似乎来到了没有知识存在的荒原")) == "missing"
    assert state(Tab("<html>视频不见了</html>")) == "missing"
    assert state(Tab("<html><body>别的内容</body></html>")) == "unknown"


def test_browser_manager_liveness():
    """用户手动关掉 Chrome 后，引用必须能失效并被清掉。"""
    from core.browser import BrowserManager

    class States:
        def __init__(self, alive):
            self.is_alive = alive

    class Page:
        url = "https://example/"

        def __init__(self, alive):
            self.states = States(alive)

    manager = BrowserManager()
    assert manager.is_alive() is False       # 还没启动

    manager._page = Page(True)
    assert manager.is_alive() is True
    assert manager.ensure() is True

    manager._page = Page(False)
    assert manager.is_alive() is False
    assert manager.ensure() is False
    assert manager._page is None             # 失效引用被清掉，下次会重新 launch


def test_douyin_classify_photos_vs_video():
    classify = DouyinPlatform._classify

    # note 同时带 images 和 video：必须判成图文，否则只会下到一个封面动画
    note = {"aweme_type": 68,
            "images": [{"url_list": ["https://img/1"]}],
            "video": {"play_addr": {"url_list": ["https://vid/1"]}}}
    assert classify(note) == "photos"

    video = {"aweme_type": 0,
             "video": {"play_addr": {"url_list": ["https://vid/1"]}}}
    assert classify(video) == "video"

    # 嵌套字段也算图文
    nested = {"image_post_info": {"images": [{"url_list": ["https://i"]}]}}
    assert classify(nested) == "photos"

    assert classify({}) == "unknown"


def main() -> int:
    tests = [(name, obj) for name, obj in sorted(globals().items())
             if name.startswith("test_") and callable(obj)]
    failed = 0
    for name, func in tests:
        try:
            func()
        except AssertionError as exc:
            failed += 1
            print(f"FAIL  {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"ERROR {name}: {type(exc).__name__}: {exc}")
        else:
            print(f"ok    {name}")

    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
