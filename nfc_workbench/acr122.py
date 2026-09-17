"""ACR122U command encoding and response decoding, based on ACS API V2.04."""

from dataclasses import dataclass
from enum import Enum


class ResponseKind(str, Enum):
    ISO = "ISO 7816"
    FIRMWARE = "Firmware ASCII"
    LED = "LED state"
    PICC = "PICC parameter"
    DIRECT = "PN532 direct"
    DESFIRE = "DESFire wrapped"
    NATIVE = "DESFire native"
    RAW = "Raw bytes"


STATUS_ERRORS = {
    0x6300: "Operation failed (check authentication, card type and access rights)",
    0x6700: "Wrong length",
    0x6982: "Security status not satisfied",
    0x6985: "Conditions of use not satisfied",
    0x6A81: "Function not supported by this card/reader",
    0x6A82: "File or application not found",
    0x6A86: "Incorrect P1/P2",
    0x6B00: "Address outside valid range",
    0x6D00: "Instruction not supported",
    0x6E00: "Class not supported",
}

PN532_ERRORS = {
    0x00: "No error", 0x01: "Target response timeout", 0x02: "CRC error",
    0x03: "Parity error", 0x04: "Invalid anti-collision bit count",
    0x05: "MIFARE framing error", 0x06: "Bit collision",
    0x07: "Communication buffer too small", 0x08: "RF buffer overflow",
    0x0A: "External RF field not activated in time", 0x0B: "RF protocol error",
    0x0D: "Overheating; antenna drivers disabled", 0x0E: "Internal buffer overflow",
    0x10: "Invalid parameter", 0x12: "Unsupported DEP command",
    0x13: "Invalid RF frame format", 0x14: "MIFARE authentication failed",
    0x23: "UID check byte mismatch", 0x25: "Invalid device state",
    0x26: "Operation not allowed in this configuration",
    0x27: "Command not allowed in current context", 0x29: "Target released",
    0x2A: "Type B card exchanged", 0x2B: "Type B card removed",
    0x2C: "NFCID3 mismatch", 0x2D: "Over-current", 0x2E: "Missing NAD",
}

CARD_NAMES = {
    0x0001: "MIFARE Classic 1K", 0x0002: "MIFARE Classic 4K",
    0x0003: "MIFARE Ultralight", 0x0026: "MIFARE Mini",
    0xF004: "Topaz / Jewel", 0xF011: "FeliCa 212K", 0xF012: "FeliCa 424K",
}

PROFILES = {
    "MIFARE Classic 1K": (64, 16),
    "MIFARE Classic 4K": (256, 16),
    "MIFARE Mini": (20, 16),
    "MIFARE Ultralight": (16, 4),
}

LED_EXAMPLES = {
    "1. Read LED state": "FF 00 40 00 04 00 00 00 00",
    "2. Both LEDs on": "FF 00 40 0F 04 00 00 00 00",
    "3. Red off; green unchanged": "FF 00 40 04 04 00 00 00 00",
    "4. Red pulse, 2 seconds": "FF 00 40 50 04 14 00 01 01",
    "5. Red blink, 1 Hz, three times": "FF 00 40 50 04 05 05 03 01",
    "6. Both blink, 1 Hz, three times": "FF 00 40 F0 04 05 05 03 03",
    "7. Alternate, 1 Hz, three times": "FF 00 40 D0 04 05 05 03 01",
}


def hex_bytes(text: str, length: int | None = None) -> bytes:
    try:
        data = bytes.fromhex(text)
    except ValueError as error:
        raise ValueError("Enter complete hexadecimal bytes, e.g. FF CA 00 00 00.") from error
    if length is not None and len(data) != length:
        raise ValueError(f"Expected exactly {length} bytes; received {len(data)}.")
    return data


def hex_text(data: bytes) -> str:
    return data.hex(" ").upper()


def byte(value: int) -> int:
    if not isinstance(value, int) or not 0 <= value <= 255:
        raise ValueError("Value must be an integer from 0 to 255.")
    return value


def sector_of(block: int) -> int:
    byte(block)
    return block // 4 if block < 128 else 32 + (block - 128) // 16


def is_trailer(block: int) -> bool:
    byte(block)
    return (block + 1) % (4 if block < 128 else 16) == 0


def validate_address(profile: str, address: int, write: bool = False,
                     allow_protected: bool = False) -> int:
    count, size = PROFILES[profile]
    if not 0 <= address < count:
        raise ValueError(f"Address must be 0..{count - 1} for {profile}.")
    protected = address < 4 if size == 4 else address == 0 or is_trailer(address)
    if write and protected and not allow_protected:
        raise ValueError("Protected manufacturer, lock/OTP or sector-trailer area. Enable the protected-write override explicitly.")
    return size


@dataclass(frozen=True)
class Command:
    name: str
    data: bytes
    kind: ResponseKind = ResponseKind.ISO
    reader_only: bool = False
    sensitive: bool = False


def get_data(ats: bool = False) -> Command:
    return Command("Read ATS" if ats else "Read UID", bytes([0xFF, 0xCA, int(ats), 0, 0]))


def load_key(key: bytes, slot: int = 0) -> Command:
    if len(key) != 6 or slot not in (0, 1):
        raise ValueError("Keys must be six bytes and the slot must be 0 or 1.")
    return Command("Load volatile key", bytes([0xFF, 0x82, 0, slot, 6]) + key, sensitive=True)


def authenticate(block: int, key_type: int = 0x60, slot: int = 0,
                 legacy: bool = False) -> Command:
    if key_type not in (0x60, 0x61) or slot not in (0, 1):
        raise ValueError("Select Key A/B and slot 0/1.")
    if legacy:
        data = bytes([0xFF, 0x88, 0, byte(block), key_type, slot])
    else:
        data = bytes([0xFF, 0x86, 0, 0, 5, 1, 0, byte(block), key_type, slot])
    return Command("Authenticate sector", data)


def read_binary(block: int, length: int = 16) -> Command:
    if not 1 <= length <= 16:
        raise ValueError("Read length must be 1..16 bytes.")
    return Command("Read memory", bytes([0xFF, 0xB0, 0, byte(block), length]))


def write_binary(block: int, data: bytes) -> Command:
    if len(data) not in (4, 16):
        raise ValueError("Write exactly 4 bytes (Ultralight) or 16 bytes (Classic/Mini).")
    return Command("Write memory", bytes([0xFF, 0xD6, 0, byte(block), len(data)]) + data)


def value_operation(block: int, operation: int, value: int) -> Command:
    if operation not in (0, 1, 2) or not -(2**31) <= value < 2**31:
        raise ValueError("Choose store/increment/decrement and a signed 32-bit value.")
    return Command(("Store", "Increment", "Decrement")[operation] + " value",
                   bytes([0xFF, 0xD7, 0, byte(block), 5, operation]) + value.to_bytes(4, "big", signed=True))


def read_value(block: int) -> Command:
    return Command("Read value", bytes([0xFF, 0xB1, 0, byte(block), 4]))


def restore_value(source: int, target: int) -> Command:
    if sector_of(source) != sector_of(target):
        raise ValueError("Source and target must belong to the same sector.")
    return Command("Restore value", bytes([0xFF, 0xD7, 0, byte(source), 2, 3, byte(target)]))


def direct(payload: bytes) -> Command:
    if not 1 <= len(payload) <= 255:
        raise ValueError("Direct payload must contain 1..255 bytes.")
    return Command("Direct transmit", bytes([0xFF, 0, 0, 0, len(payload)]) + payload,
                   ResponseKind.DIRECT, True)


def reader_command(name: str, instruction: int, parameter: int = 0,
                   kind: ResponseKind = ResponseKind.ISO) -> Command:
    return Command(name, bytes([0xFF, 0, byte(instruction), byte(parameter), 0]), kind, True)


def led(control: int, first: int, second: int, repetitions: int, buzzer: int) -> Command:
    if buzzer not in range(4):
        raise ValueError("Buzzer link must be 0..3.")
    return Command("LED / buzzer", bytes([0xFF, 0, 0x40, byte(control), 4,
                   byte(first), byte(second), byte(repetitions), buzzer]), ResponseKind.LED, True)


FIRMWARE = reader_command("Firmware", 0x48, kind=ResponseKind.FIRMWARE)
PICC = reader_command("Get PICC parameter", 0x50, kind=ResponseKind.PICC)
RF_STATUS = direct(bytes.fromhex("D4 04"))
GET_CHALLENGE = Command("Get Challenge", bytes.fromhex("00 84 00 00 08"))


def desfire(instruction: int, payload: bytes = b"", native: bool = False) -> Command:
    byte(instruction)
    if len(payload) > 255:
        raise ValueError("DESFire payload exceeds 255 bytes.")
    if native:
        return Command("DESFire native", bytes([instruction]) + payload, ResponseKind.NATIVE)
    body = bytes([len(payload)]) + payload if payload else b""
    return Command("DESFire wrapped", bytes([0x90, instruction, 0, 0]) + body + b"\x00", ResponseKind.DESFIRE)


def felica_read(identifier: bytes, service: int, block: int, pseudo: bool = False) -> Command:
    if len(identifier) != 8 or not 0 <= service <= 0xFFFF or not 0 <= block <= 0xFFFF:
        raise ValueError("FeliCa requires an 8-byte IDm and 16-bit service/block numbers.")
    block_list = bytes([0x80, block]) if block < 256 else b"\x00" + block.to_bytes(2, "little")
    body = b"\x06" + identifier + b"\x01" + service.to_bytes(2, "little") + b"\x01" + block_list
    frame = bytes([len(body) + 1]) + body
    return direct(b"\xD4\x40\x01" + frame) if pseudo else Command("FeliCa read", frame)


def topaz(operation: str, address: int = 8, value: int = 0, pseudo: bool = False) -> Command:
    if operation == "all":
        frame = b"\x00"
    elif operation == "read":
        frame = bytes([1, byte(address)])
    elif operation == "write":
        frame = bytes([0x53, byte(address), byte(value)])
    else:
        raise ValueError("Unknown Topaz operation.")
    return direct(b"\xD4\x40\x01" + frame) if pseudo else Command(f"Topaz {operation}", frame)


@dataclass(frozen=True)
class Response:
    raw: bytes
    data: bytes
    status: int | None
    ok: bool
    message: str
    more: bool = False

    def require_ok(self) -> bytes:
        if not self.ok:
            raise RuntimeError(self.message)
        return self.data


def decode(raw: bytes, kind: ResponseKind = ResponseKind.ISO) -> Response:
    if kind == ResponseKind.RAW:
        return Response(raw, raw, None, True, "Raw response (not interpreted)")
    if kind == ResponseKind.FIRMWARE:
        valid = len(raw) == 10 and raw.startswith(b"ACR122U") and all(32 <= item < 127 for item in raw)
        return Response(raw, raw, None, valid, raw.decode("ascii", errors="replace") if valid else "Unexpected firmware response: " + hex_text(raw))
    if kind == ResponseKind.NATIVE:
        if not raw:
            return Response(raw, b"", None, False, "Empty DESFire response")
        status = raw[0]
        data = b"" if len(raw) == 3 and raw[1:] == b"\x90\x00" else raw[1:]
        return Response(raw, data, status, status in (0, 0xAF),
                        "Additional frame" if status == 0xAF else f"DESFire status {status:02X}", status == 0xAF)
    if len(raw) < 2:
        return Response(raw, b"", None, False, "Truncated response: expected status bytes")
    status = int.from_bytes(raw[-2:], "big")
    data = raw[:-2]
    if kind in (ResponseKind.LED, ResponseKind.PICC):
        valid = len(raw) == 2 and raw[0] == 0x90
        return Response(raw, raw[1:], status, valid,
                        f"{kind.value}: {raw[1]:02X}" if valid else STATUS_ERRORS.get(status, f"Reader status {status:04X}"))
    if kind == ResponseKind.DESFIRE:
        return Response(raw, data, status, status in (0x9100, 0x91AF),
                        "Additional frame" if status == 0x91AF else f"DESFire status {status:04X}", status == 0x91AF)
    valid = status == 0x9000
    message = "Success" if valid else STATUS_ERRORS.get(status, f"Card status {status:04X}")
    if kind == ResponseKind.DIRECT and valid:
        if len(data) < 2 or data[0] != 0xD5:
            valid, message = False, "Malformed PN532 response"
        elif data[1] in (0x41, 0x43):
            if len(data) < 3:
                valid, message = False, "Missing PN532 status"
            elif data[2] & 0x3F:
                valid = False
                message = PN532_ERRORS.get(data[2] & 0x3F, f"PN532 error {data[2]:02X}")
    return Response(raw, data, status, valid, message)


def identify_atr(atr: bytes) -> str:
    prefix = bytes.fromhex("3B 8F 80 01 80 4F 0C A0 00 00 03 06")
    if len(atr) == 20 and atr.startswith(prefix):
        card_code = int.from_bytes(atr[13:15], "big")
        return CARD_NAMES.get(card_code, f"Unknown PC/SC card ({card_code:04X})")
    return "ISO 14443-4 / other (ATR alone is not definitive)"


def rf_status(data: bytes) -> dict:
    if len(data) < 6 or data[:2] != b"\xD5\x05":
        raise ValueError("Invalid Get General Status response.")
    count = data[4]
    if len(data) != 6 + count * 4:
        raise ValueError("Truncated or malformed RF target list.")
    rates = {0: "106 Kbps", 1: "212 Kbps", 2: "424 Kbps"}
    types = {0: "ISO 14443 / MIFARE", 0x10: "FeliCa", 1: "Active", 2: "Topaz / Jewel"}
    targets = []
    for offset in range(5, 5 + count * 4, 4):
        target, receive, transmit, modulation = data[offset:offset + 4]
        targets.append({"target": target, "receive": rates.get(receive, str(receive)),
                        "transmit": rates.get(transmit, str(transmit)), "type": types.get(modulation, str(modulation))})
    return {"last_error": PN532_ERRORS.get(data[2], f"Unknown {data[2]:02X}"),
            "external_field": bool(data[3]), "targets": targets}