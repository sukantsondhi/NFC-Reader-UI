# ACR122U feature checklist

Scope: every command and workflow in ACS **ACR122U API V2.04**. Implementation
does not imply hardware verification. Card-specific permissions still apply.

| Status | Function | Manual | UI location |
| --- | --- | --- | --- |
| Implemented | List readers; connect shared T=1; disconnect | 7 | Connection bar |
| Implemented | Direct PC/SC connection; CCID escape (3500) | Appendix A | Connection bar / Console |
| Implemented | Reader/card insertion and removal status | 3, 7 | Overview |
| Implemented | ATR display and card-family identification | 3.1 | Overview |
| Implemented | Read UID and ATS | 4.1 | Overview |
| Implemented | Load six-byte volatile keys into slots 0/1 | 5.1 | Memory |
| Implemented | Authenticate with Key A or B; modern and obsolete APDUs | 5.2 | Memory |
| Implemented | Read Classic/Mini blocks and Ultralight pages | 5.3 | Memory |
| Implemented | Write 16-byte blocks or 4-byte pages | 5.4 | Memory |
| Implemented | Classic 1K/4K/Mini sector and trailer mapping | 5.2 | Memory |
| Implemented | Read/store/increment/decrement signed value blocks | 5.5 | Value blocks |
| Implemented | Restore/copy a value within the same sector | 5.5.3 | Value blocks |
| Implemented | Direct transmit of up to 255 payload bytes | 6.1 | Console |
| Implemented | Read and set red/green LED states and masks | 6.2 | Reader controls |
| Implemented | Blink timing, repetition, initial states and buzzer linking | 6.2 | Reader controls |
| Implemented | All seven LED examples | Appendix E | Reader controls |
| Implemented | Firmware version (ASCII, without status words) | 6.3 | Overview |
| Implemented | Read/set all eight PICC operating-parameter bits | 6.4, 6.5 | Reader controls |
| Implemented | Chip response timeout including 00/FF special modes | 6.6 | Reader controls |
| Implemented | Card-detection buzzer on/off | 6.7 | Reader controls |
| Implemented | RF antenna on/off | 7 | Reader controls |
| Implemented | ISO 7816 APDU exchange and Get Challenge | 7.1 | Console |
| Implemented | DESFire native and ISO-wrapped exchange | 7.2 | Other tags |
| Implemented | DESFire Get Version with bounded frame chaining | 7.2 | Other tags |
| Implemented | DESFire authentication-challenge command | 7.2 | Other tags |
| Implemented | FeliCa read without encryption; native/direct transport | 7.3 | Other tags |
| Implemented | Topaz/Jewel read byte, read all, write byte | 7.4 | Other tags |
| Implemented | RF status, target, bitrate, modulation, PN532 errors | 7.5, Appendix D | Overview |
| Implemented | Timestamped command/response log and export | Supporting feature | Activity log |
| Implemented | Memory range dump, import/export, verified single writes | Supporting feature | Memory |
| Implemented | NDEF decode from memory dumps | Supporting feature | Memory |
| Implemented | Offline demo; protocol, service and UI tests | Supporting feature | Connection bar |

## Verification status

- Automated tests cover protocol byte sequences, response formats, boundary checks,
  simulated read/write/authentication/value/tag flows, and asynchronous UI actions.
- Desktop panels were rendered and checked at 1400x920 and 1000x720.
- Physical reader discovery and direct firmware query succeeded on Windows:
  **ACS ACR122 0 / ACR122U216**.
- No card was present. Physical tag commands and changes to LEDs, buzzer, RF and
  polling settings still need hardware acceptance testing. No physical writes were
  made. "Implemented" means available in code/UI, not certified across all tags.

## Boundaries and manual corrections

- This is a local desktop application, not Web NFC or an HTTP service.
- The reader supports one active tag at a time. No UID cloning, key recovery, or
  bypass of card access controls is provided.
- MIFARE Classic authentication is not DESFire mutual authentication. Section 7.2
  demonstrates only the initial DESFire challenge; secure sessions and proprietary
  card applications need their own specifications and keys.
- ATS uses **FF CA 01 00 00** from section 4.1, not the contradictory note in 7.1.
  ATS is not available on every tag.
- Read Value uses **Le=04** from 5.5.2, not Le=00 in the 5.5.3 example.
- Classic sector 14 data blocks are **38..3A**, not 38..0A in Table 4.
- A native DESFire response starts with its status. Its final two bytes may be
  payload, not ISO status words. LED and PICC responses use the second byte as data.
- Direct/escape support depends on the installed driver. Registry changes are
  never made automatically. Appendix A describes old Windows versions; use the
  actual device instance and current driver guidance.