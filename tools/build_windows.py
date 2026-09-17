"""Build and verify a Windows x64 release from the current source tree."""

from importlib.metadata import distribution
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import sys
from tempfile import TemporaryDirectory
from urllib.request import urlopen
from urllib.parse import urljoin
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import VERSION


def run(*arguments, **options):
    subprocess.run(arguments, cwd=ROOT, check=True, **options)


def collect_licenses(destination):
    destination.mkdir(parents=True, exist_ok=True)
    components = []
    for name in ("PySide6", "PySide6_Essentials", "PySide6_Addons", "shiboken6", "pyscard",
                 "qtawesome", "QtPy", "ndeflib", "markdown-it-py", "mdurl", "packaging", "pyinstaller"):
        package = distribution(name)
        components.append({"name": name, "version": package.version,
                           "license": package.metadata.get("License-Expression") or package.metadata.get("License"),
                           "project_urls": package.metadata.get_all("Project-URL", [])})
        for file in package.files or []:
            filename = Path(str(file)).name.lower()
            if (filename.startswith(("license", "copying", "copyright", "notice"))
                    and Path(str(file)).suffix.lower() in ("", ".txt", ".md", ".html")):
                source = Path(package.locate_file(file))
                target = destination / name / str(file).replace("../", "")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
    shutil.copy2(Path(sys.base_prefix) / "LICENSE.txt", destination / "Python-LICENSE.txt")
    for identifier in ("LGPL-3.0-only", "GPL-3.0-only", "LGPL-2.1-only", "OFL-1.1", "CC-BY-4.0", "GFDL-1.3-only"):
        source = f"https://raw.githubusercontent.com/spdx/license-list-data/main/text/{identifier}.txt"
        with urlopen(source, timeout=60) as response:
            text = response.read()
        if len(text) < 500:
            raise RuntimeError(f"Incomplete license text: {identifier}")
        (destination / f"{identifier}.txt").write_bytes(text)
    (destination / "components.json").write_text(json.dumps({"python": platform.python_version(),
        "components": components, "spdx_text_source": "https://github.com/spdx/license-list-data"}, indent=2), encoding="utf-8")
    shutil.copy2(ROOT / "THIRD_PARTY_NOTICES.md", destination / "THIRD_PARTY_NOTICES.md")


def prepare_assets():
    from PySide6.QtCore import qVersion
    from PySide6.QtWidgets import QApplication
    import qtawesome as qta
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo,
    )

    application = QApplication.instance() or QApplication([])
    application.setQuitOnLastWindowClosed(False)
    qta.icon("fa5s.broadcast-tower", color="#225ccb").pixmap(256, 256).save(str(ROOT / "build" / "NFCWorkbench.ico"))
    version = tuple(int(part) for part in VERSION.split(".")) + (0,)
    metadata = VSVersionInfo(
        ffi=FixedFileInfo(filevers=version, prodvers=version, mask=0x3F,
                          flags=0x02, OS=0x40004, fileType=0x1, subtype=0, date=(0, 0)),
        kids=[StringFileInfo([StringTable("040904B0", [
            StringStruct("FileDescription", "NFC Workbench for ACS ACR122U"),
            StringStruct("FileVersion", VERSION),
            StringStruct("ProductName", "NFC Workbench"),
            StringStruct("ProductVersion", VERSION),
            StringStruct("OriginalFilename", "NFCWorkbench.exe"),
        ])]), VarFileInfo([VarStruct("Translation", [1033, 1200])])],
    )
    (ROOT / "build" / "windows-version.txt").write_text(str(metadata), encoding="utf-8")

    class AttributionPage(HTMLParser):
        def __init__(self):
            super().__init__()
            self.links = set()
            self.text = []

        def handle_starttag(self, tag, attrs):
            href = dict(attrs).get("href", "")
            if tag == "a" and "qtwebengine-3rdparty-" in href and href.endswith(".html"):
                self.links.add(href)

        def handle_data(self, data):
            if data.strip():
                self.text.append(data.strip())

    base_url = "https://doc.qt.io/qt-6/qtwebengine-licensing.html"
    with urlopen(base_url, timeout=60) as response:
        index_html = response.read().decode("utf-8")
    expected_version = ".".join(qVersion().split(".")[:2])
    if f"Qt {expected_version}" not in index_html:
        raise RuntimeError("Qt attribution documentation no longer matches the bundled Qt minor version.")
    index_page = AttributionPage()
    index_page.feed(index_html)
    if len(index_page.links) < 50:
        raise RuntimeError("Qt WebEngine attribution index is incomplete.")

    def fetch_attribution(link):
        url = urljoin(base_url, link)
        with urlopen(url, timeout=60) as response:
            html = response.read().decode("utf-8")
        page = AttributionPage()
        page.feed(html)
        return "Source: " + url + "\n\n" + "\n".join(page.text)

    with ThreadPoolExecutor(max_workers=6) as executor:
        attributions = list(executor.map(fetch_attribution, sorted(index_page.links)))
    credit_text = "Qt WebEngine / Chromium third-party attributions\nSource: " + base_url + "\n\n"
    credit_text += "\n".join(index_page.text) + "\n\n" + "\n\n".join(attributions)
    (ROOT / "build" / "licenses" / "QtWebEngine-Chromium-credits.txt").write_text(credit_text, encoding="utf-8")
    print(f"Collected {len(attributions)} Qt WebEngine attribution pages for Qt {expected_version}.")


def main():
    if sys.platform != "win32" or struct.calcsize("P") != 8 or platform.machine().lower() not in ("amd64", "x86_64"):
        raise RuntimeError("Build using 64-bit x86 Python on Windows.")
    run(sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v")
    run(sys.executable, "tools/check_repository.py")
    build = ROOT / "build"
    build.mkdir(exist_ok=True)
    collect_licenses(build / "licenses")
    prepare_assets()
    run(sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "NFCWorkbench.spec")
    executable = ROOT / "dist" / "NFCWorkbench.exe"
    report = build / "packaged-smoke.json"
    with TemporaryDirectory(prefix="NFC Workbench smoke ") as working:
        environment = dict(os.environ)
        for variable in ("PYTHONHOME", "PYTHONPATH", "QT_PLUGIN_PATH", "QTWEBENGINEPROCESS_PATH"):
            environment.pop(variable, None)
        subprocess.run([str(executable), "--self-test", str(report)], cwd=working,
                       env=environment, check=True, timeout=240)
    result = json.loads(report.read_text(encoding="utf-8"))
    if not result.get("ok") or not result.get("frozen") or result.get("hardware_access"):
        raise RuntimeError(f"Packaged self-test failed: {result}")
    release = ROOT / "release"
    release.mkdir(exist_ok=True)
    name = f"NFCWorkbench-v{VERSION}-windows-x64"
    artifact = release / f"{name}.exe"
    shutil.copy2(executable, artifact)
    license_archive = release / f"{name}-licenses.zip"
    with zipfile.ZipFile(license_archive, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted((build / "licenses").rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(build))
        archive.write(ROOT / "LICENSE", "NFCWorkbench-LICENSE.txt")
    checksums = []
    for path in (artifact, license_archive):
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        checksums.append(f"{digest}  {path.name}")
    (release / "SHA256SUMS.txt").write_text("\n".join(checksums) + "\n", encoding="ascii")
    shutil.copy2(report, release / "packaged-smoke.json")
    print(f"Release verified: {artifact} ({artifact.stat().st_size / 1024 / 1024:.1f} MiB)")


if __name__ == "__main__":
    main()