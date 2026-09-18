# Bili Downloader

Bilibili 视频下载工具，支持批量下载与音画合并，基于 DrissionPage 浏览器自动化。

> **声明**：本项目仅供技术交流与学习使用。下载功能需要登录 Bilibili 账号，使用过程中可能存在账号风险，请知悉并自行评估。请遵守 Bilibili 相关用户协议，勿将下载内容用于商业用途。

## 适用场景

- 当网站不支持直接下载时，可通过本工具获取视频播放页面的视频与音频流并合并
- 需要输入 Bilibili 视频播放页面的完整链接（`https://www.bilibili.com/video/...`）
- 支持批量下载，每行一条链接或用 `|` 分隔

## 功能

- 批量下载 Bilibili 视频
- 自动分离下载视频流与音频流并合并
- 浏览器自动登录检测
- 简洁的图形界面
- 插件系统，支持自定义功能扩展

## 环境要求

- Windows 10/11
- Python 3.10+
- Chrome 浏览器

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 运行
python main.py
```

## 构建 EXE

```bash
# 双击运行 build.bat，或手动执行：
pip install -r requirements.txt
pyinstaller --noconfirm --onefile --windowed --collect-data customtkinter --name BiliDownloader main.py
```

生成文件位于 `dist/BiliDownloader.exe`。

## 使用方法

1. 启动程序，点击「启动浏览器」
2. 在弹出的浏览器中登录 Bilibili
3. 登录成功后，在输入框中粘贴视频播放页链接（每行一条或用 `|` 分隔）
4. 点击「下载」，进度和日志实时显示在下方
5. 下载完成的视频保存在 `D:\data\bili_video\`（可在设置页修改）

## 项目结构

```
bili-downloader/
├── main.py                  # 程序入口
├── gui/
│   ├── app.py               # 主窗口 + 侧边栏
│   ├── theme.py             # 配色与字体常量
│   └── views/
│       ├── download_view.py # 下载视图
│       ├── settings_view.py # 设置视图
│       └── about_view.py    # 关于视图
├── core/
│   ├── browser.py           # 浏览器管理 + 登录检测
│   ├── downloader.py        # 视频下载 + 音画合并
│   ├── dp_tools.py          # 请求头/Cookie 工具
│   ├── http_client.py       # HTTP 请求封装
│   └── plugin_base.py       # 插件基类
├── plugins/                 # 插件目录（自行添加）
├── requirements.txt
├── build.bat
└── README.md
```

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
