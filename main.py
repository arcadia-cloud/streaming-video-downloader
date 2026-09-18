import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gui.app import App


if __name__ == "__main__":
    app = App()
    app.mainloop()
