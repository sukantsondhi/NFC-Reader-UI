# Contributing

Open an issue before a large feature or a new card-family implementation. Include
the reader firmware, card's exact product family, host OS and a minimal sequence
of operations. Remove keys, private UIDs, card data, local usernames and unrelated
logs before sharing diagnostics. Do not attach production card dumps.

## Development

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r packaging/windows/requirements-build.txt -c packaging/windows/constraints.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe tools/check_repository.py
.\.venv\Scripts\python.exe app.py --demo
```

Keep application code under `nfc_workbench/`, Windows packaging inputs under
`packaging/windows/`, and illustrated documentation under `docs/`. Root launchers
are retained for compatibility; do not add implementation modules there.

Keep command encoding/decoding in the protocol module, device operations in the
single-thread-owned session, and UI callbacks on the Qt thread. Do not add
automatic write retries, log keys, remove protected-area guards, or perform
hardware operations in tests. Add focused protocol and demo tests with each
behavior change. Update the illustrated manual when controls change.

Hardware testing must use authorized test cards. Record what was actually tested;
do not turn a demo pass into a claim of physical compatibility. Use a disposable
card for intentional writes. No branch-protection settings are assumed by this
repository; CI must pass before merging or publishing a release.

The original project code and documentation are MIT licensed; preserve all
third-party notices. See [docs/RELEASING.md](docs/RELEASING.md) for binary builds.