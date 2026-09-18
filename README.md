# Video Downloader

多平台视频下载工具，基于 DrissionPage 浏览器自动化。已支持 Bilibili，架构预留抖音、小红书等平台扩展。

> **声明**：本项目仅供技术交流与学习使用。下载功能需要登录对应平台账号，使用过程中可能存在账号风险，请知悉并自行评估。请遵守各平台相关用户协议，勿将下载内容用于商业用途。代码部分由ai生成（界面，多平台架构实现等）。

## 功能

- 批量下载视频（每行一条链接或用 `|` 分隔）
- Bilibili：自动分离下载视频流与音频流，用 ffmpeg 无损合并
- 浏览器自动登录检测
- 简洁暗色桌面界面
- 插件系统，支持自定义功能扩展
- 多平台架构，新增平台只需一个文件

## 环境要求

- Windows 10/11
- Python 3.10+
- Chrome 浏览器

## 快速开始

```bash
pip install -r requirements.txt
python main.py
```

## 使用方法

1. 启动程序，点击「启动浏览器」
2. 在弹出的浏览器中登录对应平台
3. 登录成功后，在输入框中粘贴视频播放页链接
4. 点击「下载」，进度和日志实时显示在下方
5. 下载完成的视频保存在 `~/video_downloader/bili_video/`（可在设置页修改）

## 项目结构

```
bili-downloader/
├── main.py                      # 程序入口
├── gui/
│   ├── app.py                   # 主窗口 + 侧边栏 + 下载路由
│   ├── theme.py                 # 配色与字体常量
│   └── views/
│       ├── download_view.py     # 下载视图
│       ├── settings_view.py     # 设置视图
│       └── about_view.py        # 关于视图
├── core/
│   ├── browser.py               # 浏览器管理 + 登录检测
│   ├── downloader.py            # 通用下载工具（ffmpeg 合并等）
│   ├── dp_tools.py              # 请求头 / Cookie 工具
│   ├── http_client.py           # HTTP 请求封装
│   ├── plugin_base.py           # 插件基类
│   ├── platform_base.py         # 平台基类（新增平台的接口）
│   └── platforms/
│       ├── __init__.py          # 平台注册表
│       ├── bilibili.py          # Bilibili 平台实现
│       ├── douyin.py            # 抖音平台（待实现）
│       └── xiaohongshu.py       # 小红书平台（待实现）
├── plugins/                     # 插件目录
│   └── example_logger.py        # 示例插件
├── requirements.txt
└── README.md
```

## 新增平台

以抖音为例，只需 3 步：

**1. 实现 `core/platforms/douyin.py`**

```python
from core.platform_base import PlatformBase

class DouyinPlatform(PlatformBase):
    name = "douyin"
    display_name = "抖音"
    url_prefix = "https://www.douyin.com/"
    sub_folder = "dy_video"

    def match_url(self, url: str) -> bool:
        return "douyin.com" in url

    def parse_urls(self, text: str) -> list[str]:
        # 解析用户输入中的抖音链接
        ...

    def login_url(self) -> str:
        return "https://www.douyin.com/"

    def is_logged_in(self, page) -> bool:
        # 检测页面是否已登录
        ...

    def get_video_name(self, tab) -> str | None:
        # 从标签页提取视频标题
        ...

    def download(self, tab, headers: dict, video_name: str):
        # 执行下载逻辑
        ...
```

**2. 在 `core/platforms/__init__.py` 中注册**

```python
from core.platforms.bilibili import BilibiliPlatform
from core.platforms.douyin import DouyinPlatform

PLATFORMS = [
    BilibiliPlatform(),
    DouyinPlatform(),
]
```

**3. 完成**

主程序会自动通过 `match_url` 将链接路由到对应平台，无需修改其他代码。

## 插件开发

在 `plugins/` 目录下创建 Python 文件，继承 `PluginBase`：

```python
from core.plugin_base import PluginBase

class MyPlugin(PluginBase):
    name = "我的插件"
    description = "示例插件"

    def on_init(self, browser):
        print(f"{self.name} 已加载")

    def on_download_complete(self, url, video_path, success):
        if success:
            print(f"下载完成: {video_path}")
```

程序启动时会自动扫描 `plugins/` 并加载所有插件。

## 配色方案

| 用途 | 色值 |
|------|------|
| 背景 | `#1e1e1e` |
| 卡片 | `#252526` |
| 强调 | `#c9a96e` |
| 文字 | `#cccccc` |
| 次要文字 | `#858585` |
| 成功 | `#7ec699` |
| 错误 | `#f44747` |

## License

MIT
