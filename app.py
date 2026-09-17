"""Compatibility launcher for source checkouts and the Windows executable."""

from nfc_workbench.__main__ import main


if __name__ == "__main__":
    raise SystemExit(main())