"""Collect the QtQml runtime dependency without unrelated QML application plugins."""

from PyInstaller.utils.hooks.qt import add_qt6_dependencies


hiddenimports, binaries, datas = add_qt6_dependencies(__file__)