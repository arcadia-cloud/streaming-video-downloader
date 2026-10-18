"""程序入口。"""

from __future__ import annotations

import os
import sys

if os.name == "nt":
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001 - 老系统没有 shcore，忽略即可
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gui.app import App  # noqa: E402  (必须在 sys.path 设置之后导入)


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
