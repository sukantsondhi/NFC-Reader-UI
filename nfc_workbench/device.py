"""Single-thread-owned PC/SC transport and application operations."""

from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
import json
import threading
import time

from . import acr122 as api


class PcscError(RuntimeError):
    pass


class Cancelled(RuntimeError):
    pass


class PcscTransport:
    def __init__(self):
        from smartcard import scard
        self.sc = scard
        self.context = None
        self.handle = None
        self.protocol = 0
        self.direct = False
        self.name = ""

    def check(self, result: int, operation: str):
        if result != self.sc.SCARD_S_SUCCESS:
            detail = self.sc.SCardGetErrorMessage(result)
            hint = ""
            if operation == "Escape command":
                hint = " Check driver escape-command support (SCARD_CTL_CODE(3500)); no registry changes were made."
            raise PcscError(f"{operation}: {detail} (0x{result & 0xFFFFFFFF:08X}).{hint}")

    def ensure_context(self):
        if self.context is None:
            result, context = self.sc.SCardEstablishContext(self.sc.SCARD_SCOPE_USER)
            self.check(result, "Start Windows Smart Card service / establish context")
            self.context = context

    def snapshot(self) -> dict:
        self.ensure_context()
        result, names = self.sc.SCardListReaders(self.context, [])
        if result == self.sc.SCARD_E_NO_READERS_AVAILABLE:
            return {}
        self.check(result, "List readers")
        if not names:
            return {}
        result, states = self.sc.SCardGetStatusChange(
            self.context, 0, [(name, self.sc.SCARD_STATE_UNAWARE) for name in names])
        self.check(result, "Check card presence")
        return {name: {"present": bool(state & self.sc.SCARD_STATE_PRESENT),
                       "atr": bytes(atr), "counter": state >> 16}
                for name, state, atr in states}

    def connect(self, name: str, direct: bool = False) -> bytes:
        self.disconnect()
        self.ensure_context()
        mode = self.sc.SCARD_SHARE_DIRECT if direct else self.sc.SCARD_SHARE_SHARED
        result, handle, protocol = self.sc.SCardConnect(
            self.context, name, mode, 0 if direct else self.sc.SCARD_PROTOCOL_T1)
        self.check(result, "Connect reader" if direct else "Connect card (place a tag on the reader)")
        self.handle, self.protocol, self.direct, self.name = handle, protocol, direct, name
        if direct:
            return b""
        result, _, _, _, atr = self.sc.SCardStatus(handle)
        try:
            self.check(result, "Read ATR")
        except Exception:
            self.disconnect()
            raise
        return bytes(atr)

    def exchange(self, data: bytes, escape: bool = False) -> bytes:
        if self.handle is None:
            raise PcscError("Connect to a reader first.")
        if self.direct or escape:
            result, raw = self.sc.SCardControl(self.handle, self.sc.SCARD_CTL_CODE(3500), list(data))
            self.check(result, "Escape command")
        else:
            result, raw = self.sc.SCardTransmit(self.handle, self.protocol, list(data))
            self.check(result, "Transmit (do not retry a failed write until its outcome is checked)")
        return bytes(raw)

    @contextmanager
    def transaction(self):
        handle = self.handle
        locked = handle is not None and not self.direct
        if locked:
            self.check(self.sc.SCardBeginTransaction(handle), "Begin card transaction")
        try:
            yield
        finally:
            if locked:
                self.sc.SCardEndTransaction(handle, self.sc.SCARD_LEAVE_CARD)

    def disconnect(self):
        handle, self.handle = self.handle, None
        if handle is not None:
            self.sc.SCardDisconnect(handle, self.sc.SCARD_LEAVE_CARD)
        self.name = ""
        self.direct = False

    def close(self):
        self.disconnect()
        if self.context is not None:
            self.sc.SCardReleaseContext(self.context)
            self.context = None


class Session:
    def __init__(self, transport=None, logger=None):
        self.transport = transport or PcscTransport()
        self.logger = logger or (lambda entry: None)
        self.cancel = threading.Event()
        self.connected = False
        self.name = ""
        self.atr = b""
        self.generation = 0
        self.card_counter = None
        self.desfire_mode = None

    def snapshot(self) -> dict:
        states = self.transport.snapshot()
        if self.connected:
            state = states.get(self.name)
            lost = state is None
            if not self.transport.direct and state is not None:
                lost = not state["present"] or state["atr"] != self.atr
                if self.card_counter is not None and state["counter"] != self.card_counter:
                    lost = True
            if lost:
                self.disconnect()
        return {"readers": states, "connected": self.connected, "name": self.name,
                "atr": self.atr, "generation": self.generation,
                "direct": self.transport.direct}

    def connect(self, name: str, direct: bool = False) -> dict:
        self.disconnect()
        self.atr = self.transport.connect(name, direct)
        self.connected, self.name = True, name
        self.generation += 1
        self.desfire_mode = None
        try:
            states = self.transport.snapshot()
            self.card_counter = states.get(name, {}).get("counter")
            return self.snapshot()
        except Exception:
            self.disconnect()
            raise

    def disconnect(self):
        self.transport.disconnect()
        self.connected, self.name, self.atr = False, "", b""
        self.generation += 1
        self.card_counter = None
        self.desfire_mode = None

    def check_cancel(self):
        if self.cancel.is_set():
            raise Cancelled("Cancelled between commands. Completed operations were not rolled back.")

    def send(self, command: api.Command, escape: bool = False) -> api.Response:
        if not self.connected:
            raise RuntimeError("Connect to a reader first.")
        if self.transport.direct and not command.reader_only and not escape:
            raise RuntimeError("This is a card command. Connect in Shared T=1 mode with a card present.")
        started = time.perf_counter()
        sensitive = command.sensitive or command.data[:2] == b"\xFF\x82"
        entry = {"time": datetime.now().astimezone().isoformat(timespec="milliseconds"),
                 "command": command.name, "route": "Escape" if escape or self.transport.direct else "T=1",
                 "tx": "[REDACTED]" if sensitive else api.hex_text(command.data)}
        try:
            raw = self.transport.exchange(command.data, escape)
            response = api.decode(raw, command.kind)
            entry.update(rx=api.hex_text(raw), ok=response.ok, message=response.message)
            return response
        except Exception as error:
            entry.update(rx="", ok=False, message=str(error))
            if isinstance(error, PcscError):
                self.disconnect()
            raise
        finally:
            entry["ms"] = round((time.perf_counter() - started) * 1000, 1)
            self.logger(entry)

    def auth(self, address: int, options: dict):
        if options.get("auto_auth", True):
            self.send(api.load_key(options["key"], options.get("slot", 0))).require_ok()
            self.send(api.authenticate(address, options.get("key_type", 0x60),
                      options.get("slot", 0), options.get("legacy", False))).require_ok()

    def require_profile(self, profile: str):
        detected = api.identify_atr(self.atr)
        if detected != profile:
            raise ValueError(f"Selected {profile}, but the ATR identifies {detected}. Use the raw console only with the correct card specification.")

    def read_memory(self, options: dict, progress=None) -> dict:
        profile = options["profile"]
        self.require_profile(profile)
        start, end = options["start"], options["end"]
        if start > end:
            raise ValueError("Start address must not exceed end address.")
        size = api.validate_address(profile, start)
        api.validate_address(profile, end)
        rows = []
        sector = None
        for address in range(start, end + 1):
            self.check_cancel()
            if options.get("ndef_delay") and profile == "MIFARE Classic 4K":
                if self.cancel.wait(2):
                    self.check_cancel()
            if size == 16 and sector != api.sector_of(address):
                self.auth(address, options)
                sector = api.sector_of(address)
            data = self.send(api.read_binary(address, size)).require_ok()
            if len(data) != size:
                raise RuntimeError(f"Address {address}: expected {size} bytes, received {len(data)}.")
            row = {"address": address, "data": api.hex_text(data)}
            rows.append(row)
            if progress:
                progress({"row": row, "done": len(rows), "total": end - start + 1})
        return {"profile": profile, "atr": api.hex_text(self.atr), "rows": rows}

    def write_memory(self, options: dict) -> dict:
        profile, address, data = options["profile"], options["address"], options["data"]
        self.require_profile(profile)
        size = api.validate_address(profile, address, True, options.get("allow_protected", False))
        if len(data) != size:
            raise ValueError(f"This card requires exactly {size} bytes per write.")
        if size == 16:
            self.auth(address, options)
        self.check_cancel()
        self.send(api.write_binary(address, data)).require_ok()
        if size == 16 and (address == 0 or api.is_trailer(address)):
            return {"result": "Write acknowledged; protected block not read-back verified. Reconnect before using changed keys."}
        try:
            actual = self.send(api.read_binary(address, size)).require_ok()
        except Exception as error:
            raise RuntimeError(f"Write was acknowledged, but verification failed: {error}. Do not blindly repeat the write.") from error
        if actual != data:
            raise RuntimeError("Write was acknowledged, but read-back differs. Inspect memory before another write.")
        return {"result": "Write acknowledged and read-back verified", "address": address, "data": api.hex_text(actual)}

    def value(self, options: dict) -> dict:
        profile, address = options["profile"], options["address"]
        self.require_profile(profile)
        size = api.validate_address(profile, address)
        if size != 16 or address == 0 or api.is_trailer(address):
            raise ValueError("Value operations require a Classic/Mini data block, not block 0 or a trailer.")
        operation = options["operation"]
        commands = {"read": lambda: api.read_value(address),
                    "store": lambda: api.value_operation(address, 0, options["value"]),
                    "increment": lambda: api.value_operation(address, 1, options["value"]),
                    "decrement": lambda: api.value_operation(address, 2, options["value"])}
        target = options.get("target", address)
        if operation == "restore":
            api.validate_address(profile, target, True)
            command = api.restore_value(address, target)
        elif operation in commands:
            command = commands[operation]()
        else:
            raise ValueError("Unknown value operation.")
        self.auth(address, options)
        self.check_cancel()
        data = self.send(command).require_ok()
        if operation != "read":
            try:
                data = self.send(api.read_value(target if operation == "restore" else address)).require_ok()
            except Exception as error:
                raise RuntimeError(f"Value operation was acknowledged, but read-back failed: {error}. Do not repeat an increment/decrement blindly.") from error
        if len(data) != 4:
            raise RuntimeError("Expected four value bytes.")
        return {"value": int.from_bytes(data, "big", signed=True), "data": api.hex_text(data)}

    def desfire(self, options: dict) -> dict:
        native = options["native"]
        if self.desfire_mode is not None and self.desfire_mode != native:
            raise ValueError("DESFire mode cannot change within an activation. Remove and re-present the card before changing mode.")
        self.desfire_mode = native
        instruction = options["instruction"]
        payload = options.get("payload", b"")
        frames = []
        for _ in range(32):
            self.check_cancel()
            response = self.send(api.desfire(instruction, payload, native))
            response.require_ok()
            frames.append(response.data)
            if not response.more or not options.get("chain", False):
                return {"data": api.hex_text(b"".join(frames)), "frames": len(frames),
                        "status": response.message, "more": response.more}
            instruction, payload = 0xAF, b""
        raise RuntimeError("Stopped after 32 DESFire frames; possible malformed or endless chain.")

    def felica(self, options: dict) -> dict:
        identifier = options.get("identifier") or self.send(api.get_data()).require_ok()
        response = self.send(api.felica_read(identifier, options["service"], options["block"], options["pseudo"]))
        data = response.require_ok()
        if options["pseudo"]:
            if data[:3] != b"\xD5\x41\x00":
                raise RuntimeError("Unexpected FeliCa direct envelope.")
            data = data[3:]
        if len(data) < 12 or data[0] != len(data) or data[1] != 7 or data[2:10] != identifier:
            raise RuntimeError("Malformed FeliCa response or IDm mismatch.")
        if data[10:12] != b"\x00\x00":
            raise RuntimeError(f"FeliCa status flags: {api.hex_text(data[10:12])}; check the service and access permissions.")
        if len(data) != 29 or data[12] != 1:
            raise RuntimeError("Expected one 16-byte FeliCa block.")
        return {"IDm": api.hex_text(identifier), "data": api.hex_text(data[13:])}

    def topaz(self, options: dict) -> dict:
        if options["operation"] == "write" and not 8 <= options["address"] <= 103 and not options.get("allow_protected"):
            raise ValueError("Topaz address is outside user bytes 08..67. Explicit protected-write override required.")
        data = self.send(api.topaz(options["operation"], options["address"], options["value"], options["pseudo"])).require_ok()
        if options["pseudo"]:
            if data[:3] != b"\xD5\x41\x00":
                raise RuntimeError("Unexpected Topaz direct envelope.")
            data = data[3:]
        if options["operation"] in ("read", "write") and len(data) != 1:
            raise RuntimeError("Expected one Topaz response byte.")
        if options["operation"] == "write" and data != bytes([options["value"]]):
            raise RuntimeError("Topaz write echo mismatch; inspect the card before repeating.")
        return {"data": api.hex_text(data)}

    def execute(self, operation: str, options: dict, progress=None):
        if operation == "connect":
            return self.connect(**options)
        if operation == "disconnect":
            self.disconnect()
            return self.snapshot()
        self.snapshot()
        if "expected_generation" in options and options["expected_generation"] != self.generation:
            raise RuntimeError("The connection/card changed during confirmation. Reconnect and inspect the current card.")
        if not self.connected:
            raise RuntimeError("No active connection. Connect to the reader first.")
        with self.transport.transaction():
            if operation == "command":
                return asdict(self.send(options["command"], options.get("escape", False)))
            if operation == "read_memory":
                return self.read_memory(options, progress)
            if operation == "write_memory":
                return self.write_memory(options)
            if operation == "value":
                return self.value(options)
            if operation == "desfire":
                return self.desfire(options)
            if operation == "felica":
                return self.felica(options)
            if operation == "topaz":
                return self.topaz(options)
        raise ValueError(f"Unknown operation: {operation}")


def parse_dump(text: str) -> dict:
    dump = json.loads(text)
    if not isinstance(dump, dict) or dump.get("profile") not in api.PROFILES or not isinstance(dump.get("rows"), list):
        raise ValueError("Expected a memory JSON export with a supported profile and rows.")
    seen = set()
    for row in dump["rows"]:
        if not isinstance(row, dict) or type(row.get("address")) is not int or not isinstance(row.get("data"), str):
            raise ValueError("Invalid memory row.")
        address = row["address"]
        size = api.validate_address(dump["profile"], address)
        if address in seen:
            raise ValueError("Duplicate address in memory dump.")
        seen.add(address)
        api.hex_bytes(row["data"], size)
    if not seen:
        raise ValueError("Memory dump is empty.")
    return dump


def decode_ndef(dump: dict) -> list[str]:
    import ndef
    profile = dump["profile"]
    rows = {row["address"]: api.hex_bytes(row["data"]) for row in dump["rows"]}
    size = api.PROFILES[profile][1]
    addresses = [address for address in range(4, max(rows, default=3) + 1)
                 if size == 4 or not api.is_trailer(address)]
    if not addresses or any(address not in rows for address in addresses):
        raise ValueError("Read a contiguous user-memory range beginning at address 4 (Classic trailers may be omitted).")
    data = b"".join(rows[address] for address in addresses)
    offset = 0
    while offset < len(data):
        tag = data[offset]
        offset += 1
        if tag == 0:
            continue
        if tag == 0xFE:
            break
        if offset >= len(data):
            raise ValueError("Truncated TLV length.")
        length = data[offset]
        offset += 1
        if length == 0xFF:
            if offset + 2 > len(data):
                raise ValueError("Truncated extended TLV length.")
            length = int.from_bytes(data[offset:offset + 2], "big")
            offset += 2
        if offset + length > len(data):
            raise ValueError("NDEF/TLV extends beyond this dump; read more memory.")
        payload = data[offset:offset + length]
        offset += length
        if tag == 3:
            return [str(record) for record in ndef.message_decoder(payload, errors="strict")] if payload else ["Empty NDEF message"]
    raise ValueError("No NDEF TLV found. Proprietary layouts and Classic MAD allocation are not inferred.")