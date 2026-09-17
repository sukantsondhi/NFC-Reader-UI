# Third-party notices

The project MIT license applies to NFC Workbench's original code and user
documentation, not to third-party libraries, icons, vendor documentation or
trademarks. NFC Workbench is an independent project, not an ACS or NXP product.

| Component | License / notices | Source |
| --- | --- | --- |
| CPython | Python Software Foundation license and included notices | https://www.python.org/downloads/source/ |
| PySide6, Shiboken, Qt libraries | LGPL v3 option; other upstream options are not relicensed by this project | https://code.qt.io/cgit/pyside/pyside-setup.git/ and https://download.qt.io/archive/qt/ |
| Qt WebEngine / Chromium | Qt licensing plus bundled third-party notices | https://doc.qt.io/qt-6/qtwebengine-licensing.html |
| pyscard | LGPL v2.1 or later | https://github.com/LudovicRousseau/pyscard |
| QtAwesome / QtPy | MIT | https://github.com/spyder-ide/qtawesome and https://github.com/spyder-ide/qtpy |
| Font Awesome Free | Icons: CC BY 4.0; fonts: SIL OFL 1.1; code: MIT | https://fontawesome.com/license/free |
| Other icon fonts bundled by QtAwesome | See the font-specific license files shipped by QtAwesome | https://github.com/spyder-ide/qtawesome/tree/master/qtawesome/fonts |
| ndeflib | ISC | https://github.com/nfcpy/ndeflib |
| markdown-it-py / mdurl | MIT and included upstream notices | https://github.com/executablebooks/markdown-it-py and https://github.com/executablebooks/mdurl |
| packaging | Apache 2.0 or BSD-2-Clause | https://github.com/pypa/packaging |
| PyInstaller bootloader | GPL with the upstream distribution exception | https://pyinstaller.org/en/stable/license.html |

## Binary distribution

The build gathers installed distributions' license files and versions, CPython's
license, icon-font notices, LGPL/GPL license texts, and the Qt WebEngine credits.
These are embedded under `licenses` and supplied as a separate license archive
next to the executable. See that archive's `components.json` for exact versions.

The Qt/PySide and pyscard libraries are unmodified upstream dependencies, not
statically linked into proprietary application code. The one-file launcher
extracts its runtime before starting. You may inspect, debug and replace LGPL
components, including reverse engineering needed to debug your modifications.
No project restriction overrides those rights. To use replacement libraries,
run the MIT-licensed application from source or rebuild the executable with your
modified dependency versions and the included PyInstaller specification. All
corresponding application code and build scripts are included in the matching
Git tag. See [docs/RELEASING.md](docs/RELEASING.md).

For Qt/PySide 6.11.2, the corresponding source is available from:

- https://download.qt.io/archive/qt/6.11/6.11.2/single/
- https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.11.2-src/
- https://code.qt.io/cgit/pyside/pyside-setup.git/?h=v6.11.2

For pyscard, use the exact version in `components.json` from its upstream
repository or the source distribution on https://pypi.org/project/pyscard/.
The build also records upstream license-download URLs. A distributor who changes
dependency versions or redistributes a modified build must review the applicable
licenses and corresponding-source requirements for that build.

## Vendor documents and trademarks

The ACS API PDF remains the property of Advanced Card Systems Ltd. It is **not
redistributed** in this repository or executable. The API manual button opens a
user-supplied local copy, or ACS's official download. The original filename is
ignored by Git so a user's copy is not accidentally published.

MIFARE, DESFire and Ultralight are NXP trademarks; Windows is a Microsoft
trademark; other names belong to their respective owners. Screenshots in this
repository show the application's own UI with explicitly simulated data.