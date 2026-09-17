from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, copy_metadata


root = Path(SPECPATH).parents[1]
data_files = [
    (str(root / "nfc_workbench" / "assets"), "nfc_workbench/assets"),
    (str(root / "docs"), "docs"),
    (str(root / "README.md"), "."),
    (str(root / "LICENSE"), "."),
    (str(root / "CONTRIBUTING.md"), "."),
    (str(root / "SECURITY.md"), "."),
    (str(root / "CHANGELOG.md"), "."),
    (str(root / "build" / "licenses"), "licenses"),
]
data_files += collect_data_files("qtawesome")
for package in ("pyscard", "PySide6", "qtawesome", "ndeflib", "markdown-it-py"):
    data_files += copy_metadata(package)

analysis = Analysis(
    [str(root / "app.py")],
    pathex=[str(root)],
    binaries=[],
    datas=data_files,
    hiddenimports=["smartcard.scard", "ndef", "PySide6.QtSvg"],
    hookspath=[str(root / "packaging" / "windows" / "hooks")],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "PySide6.QtDataVisualization", "qtpy.QtDataVisualization"],
    noarchive=False,
)
archive = PYZ(analysis.pure)
application = EXE(
    archive,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="NFCWorkbench",
    icon=str(root / "build" / "NFCWorkbench.ico"),
    version=str(root / "build" / "windows-version.txt"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)