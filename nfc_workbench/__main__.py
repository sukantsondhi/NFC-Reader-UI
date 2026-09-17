"""Launch the local ACR122U desktop application."""

import argparse
from pathlib import Path
import sys


VERSION = "0.1.0"


def main():
    parser = argparse.ArgumentParser(description="ACR122U NFC Workbench")
    parser.add_argument("--demo", action="store_true", help="Start with simulated hardware")
    parser.add_argument("--version", action="version", version=VERSION)
    parser.add_argument("--self-test", type=Path, metavar="REPORT.json",
                        help="Run a demo-only packaged-app smoke test and exit")
    options = parser.parse_args()
    try:
        from PySide6.QtWidgets import QApplication
        from .ui import Workbench
    except ImportError as error:
        message = f"Missing dependency: {error}\nInstall with: python -m pip install -r requirements.txt"
        if sys.stderr is not None:
            print(message, file=sys.stderr)
        elif sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "NFC Workbench could not start", 0x10)
        return 1
    application = QApplication(sys.argv[:1])
    application.setApplicationName("NFC Workbench")
    application.setApplicationVersion(VERSION)
    application.setOrganizationName("NFC Workbench")
    application.setStyle("Fusion")
    window = Workbench(demo=options.demo or options.self_test is not None)
    window.show()
    if options.self_test is not None:
        from .release_check import run_release_check
        return run_release_check(application, window, options.self_test)
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())