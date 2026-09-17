# Changelog

## 0.1.0 - 2026-09-17

Initial public preview of NFC Workbench for the ACS ACR122U.

- Blue PySide6 desktop UI with eight navigation views.
- PC/SC shared T=1 and Direct/Escape reader connections.
- UID/ATR/ATS, memory authentication/read/write, signed value-block operations.
- LED/buzzer sequencing, PICC parameters, RF and timeout controls.
- DESFire framing, FeliCa read and Topaz/Jewel command helpers.
- Raw APDU console, redacted key loads and session export.
- Offline embedded user manual with 18 screenshots, search, section links and zoom.
- Separate Demo transport, automated tests, Windows single-file build and smoke test.

### Known limitations

- Physical reader discovery and firmware query were checked; physical card writes
  and changes to reader settings have not been validated in this environment.
- No full DESFire secure-session manager, encrypted FeliCa workflow, automatic NDEF
  writer, Classic MAD allocation, or universal NTAG capacity handling.
- Cancellation cannot undo a transmitted command or force every blocked driver call.
- Windows executable is unsigned; first startup extracts the bundled Qt runtime.