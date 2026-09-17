# Building and Publishing

## Windows executable

Use Windows x64 and Python 3.11 x64. This builds a self-contained executable;
users do not need Python installed. PyInstaller bundles Qt WebEngine, so the
download is substantially larger than the Python source and first launch must
extract the runtime to the user's temporary directory.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r packaging/windows/requirements-build.txt -c packaging/windows/constraints.txt
.\.venv\Scripts\python.exe tools/build_windows.py
```

The build runs the source tests, checks repository/doc files, collects license
notices and version metadata, generates the application icon, freezes the app,
and executes the resulting binary from a separate working directory with no
Python/Qt path overrides. Its self-test uses only Demo and checks native imports,
worker connection, UID, memory write/read, full manual, local images, search,
responsive layout and shutdown. An unsuccessful test stops the release build.

Outputs are under `release`: the versioned `.exe`, license archive, SHA-256
checksums and packaged smoke report. They are ignored by Git. Publish binaries
as GitHub Release assets, never as tracked Git blobs.

```powershell
.\release\NFCWorkbench-v0.1.0-windows-x64.exe --demo
.\release\NFCWorkbench-v0.1.0-windows-x64.exe --self-test smoke.json
Get-FileHash .\release\NFCWorkbench-v0.1.0-windows-x64.exe -Algorithm SHA256
```

The self-test flag is also available from source. It does not enumerate real
readers. The JSON report and matching PNG screenshot are written only to the
explicitly requested path. A frozen-app self-test has a finite timeout in the
build wrapper. This is smoke coverage, not real-card acceptance testing.

## Rebuilds and LGPL components

[packaging/windows/constraints.txt](../packaging/windows/constraints.txt) records
the versions tested for this release. The PyInstaller specification and hooks
live beside it; the build command remains [tools/build_windows.py](../tools/build_windows.py).
The build
is repeatable from source but not promised byte-for-byte reproducible: wheel,
compiler and PyInstaller timestamps can affect output hashes. To replace a Qt,
PySide or pyscard library, install your compatible modified distribution in the
build environment and rebuild using the same specification without those version
constraints. Application source is MIT licensed and contains no obfuscated or
closed components that prevent relinking. Preserve dependency notices and the
corresponding-source rights described in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Publication checklist

1. Update `VERSION` in [nfc_workbench/__main__.py](../nfc_workbench/__main__.py) and add a changelog entry.
2. Run the build above in the environment whose dependencies you intend to ship.
3. Review the resulting smoke report and screenshot, and perform manual desktop checks.
4. Review `git diff --cached`, the publishable-file check and the secret/file audit.
   Keep the vendor PDF, `.venv`, keys, real card dumps and local artifacts excluded.
5. Commit and push the validated source. Do not force-push over collaborators.
6. Wait for GitHub Actions to pass. Create a release targeting that exact commit;
   upload the executable, license archive, checksum file and smoke report.
7. Download the uploaded artifact and compare its checksum before announcing it.

Windows binaries are unsigned until a maintainer sets up trusted code signing.
Do not advise users to disable antivirus or bypass organizational policies.
Use preview/prerelease status while physical card acceptance coverage is limited.

The Windows CI workflow also builds and smoke-tests the binary. Pull requests
receive read-only repository permissions; no deployment token is embedded in
the repository or executable. Release publication remains an explicit maintainer action.