"""In-memory demo device. Never connects to PC/SC or physical hardware."""

from contextlib import nullcontext

import acr122 as api


class DemoTransport:
    NAME = "DEMO - ACR122U simulator"

    def __init__(self, profile="MIFARE Classic 1K"):
        self.profile = profile
        self.direct = False
        self.connected = False
        self.present = True
        self.counter = 0
        self.keys = {}
        self.authenticated = set()
        self.picc = 0xFF
        self.led_state = 0
        self.antenna = True
        self.frame = 0
        self.memory = bytearray(4096)
        self.values = {}
        self.memory[64:80] = b"NFC WORKBENCH   "

    @property
    def atr(self):
        codes = {value: key for key, value in api.CARD_NAMES.items()}
        code = codes.get(self.profile)
        if code is None:
            return bytes.fromhex("3B 86 80 01 06 75 77 81 02 80 00")
        data = bytes.fromhex("3B 8F 80 01 80 4F 0C A0 00 00 03 06 03") + code.to_bytes(2, "big") + bytes(4)
        checksum = 0
        for item in data[1:]:
            checksum ^= item
        return data + bytes([checksum])

    def snapshot(self):
        return {self.NAME: {"present": self.present and self.antenna,
                           "atr": self.atr if self.present and self.antenna else b"", "counter": self.counter}}

    def connect(self, name, direct=False):
        if name != self.NAME:
            raise RuntimeError("Unknown demo reader.")
        if not direct and not (self.present and self.antenna):
            raise RuntimeError("No demo card present.")
        self.connected, self.direct = True, direct
        self.authenticated.clear()
        self.frame = 0
        return b"" if direct else self.atr

    def disconnect(self):
        self.connected, self.direct = False, False
        self.authenticated.clear()

    def close(self):
        self.disconnect()

    def transaction(self):
        return nullcontext()

    def exchange(self, data, escape=False):
        if not self.connected:
            raise RuntimeError("Demo reader disconnected.")
        if data[:3] == b"\xFF\x00\x48":
            return b"ACR122U201"
        if data[:3] == b"\xFF\x00\x50":
            return bytes([0x90, self.picc])
        if data[:3] == b"\xFF\x00\x51":
            self.picc = data[3]
            return bytes([0x90, self.picc])
        if data[:3] == b"\xFF\x00\x40" and len(data) == 9:
            control = data[3]
            for index in (0, 1):
                if control & (1 << (index + 2)):
                    self.led_state = (self.led_state & ~(1 << index)) | (control & (1 << index))
            return bytes([0x90, self.led_state])
        if data[:3] in (b"\xFF\x00\x41", b"\xFF\x00\x52"):
            return b"\x90\x00"
        if data[:4] == b"\xFF\x00\x00\x00":
            payload = data[5:]
            if len(payload) != data[4]:
                return b"\x67\x00"
            if payload == b"\xD4\x04":
                target = b"\x01\x01\x00\x00\x00" if self.present and self.antenna else b"\x00"
                return b"\xD5\x05\x00\x00" + target + b"\x80\x90\x00"
            if payload[:3] == b"\xD4\x32\x01":
                self.antenna = bool(payload[3])
                self.counter += 1
                return b"\xD5\x33\x90\x00"
            if payload[:3] == b"\xD4\x40\x01":
                response = self.card_exchange(payload[3:])
                return b"\xD5\x41\x00" + response
            return b"\x6A\x81"
        return self.card_exchange(data)

    def card_exchange(self, data):
        if not self.present or not self.antenna:
            return b"\x63\x00"
        if data[:2] == b"\xFF\xCA":
            if data[2] == 1:
                return bytes.fromhex("06 75 77 81 02 80 90 00") if self.profile == "DESFire" else b"\x6A\x81"
            uid = bytes.fromhex("01 02 03 04 05 06 07 08") if self.profile.startswith("FeliCa") else bytes.fromhex("04 A1 B2 C3 D4 E5 F6")
            return uid + b"\x90\x00"
        if data[:2] == b"\xFF\x82" and len(data) == 11 and data[3] in (0, 1):
            self.keys[data[3]] = data[5:]
            return b"\x90\x00"
        if data[:2] in (b"\xFF\x86", b"\xFF\x88"):
            address, slot = (data[7], data[9]) if data[1] == 0x86 else (data[3], data[5])
            if self.keys.get(slot) != b"\xFF" * 6:
                return b"\x63\x00"
            self.authenticated.add(api.sector_of(address))
            return b"\x90\x00"
        if len(data) >= 5 and data[0] == 0xFF and data[1] in (0xB0, 0xD6, 0xB1, 0xD7):
            address = data[3]
            count, size = api.PROFILES.get(self.profile, (0, 16))
            if address >= count or (size == 16 and api.sector_of(address) not in self.authenticated):
                return b"\x63\x00"
            offset = address * size
            if data[1] == 0xB0:
                return bytes(self.memory[offset:offset + data[4]]) + b"\x90\x00"
            if data[1] == 0xD6:
                if len(data[5:]) != size:
                    return b"\x67\x00"
                self.memory[offset:offset + size] = data[5:]
                return b"\x90\x00"
            if data[1] == 0xB1:
                return self.values[address].to_bytes(4, "big", signed=True) + b"\x90\x00" if address in self.values else b"\x63\x00"
            operation = data[5]
            if operation == 3:
                if address not in self.values or api.sector_of(address) != api.sector_of(data[6]):
                    return b"\x63\x00"
                self.values[data[6]] = self.values[address]
            else:
                value = int.from_bytes(data[6:10], "big", signed=True)
                if operation and address not in self.values:
                    return b"\x63\x00"
                result = value if operation == 0 else self.values[address] + (value if operation == 1 else -value)
                if not -(2**31) <= result < 2**31:
                    return b"\x63\x00"
                self.values[address] = result
            return b"\x90\x00"
        if self.profile == "DESFire":
            native = data[0] != 0x90
            instruction = data[0] if native else data[1]
            if instruction == 0x60:
                self.frame = 0
            elif instruction == 0xAF:
                self.frame += 1
            elif instruction == 0x0A:
                payload, status = bytes.fromhex("7B 18 92 9D 9A 25 05 21"), 0xAF
                return bytes([status]) + payload if native else payload + bytes([0x91, status])
            else:
                return b"\x1C\x90\x00" if native else b"\x91\x1C"
            frames = [bytes.fromhex("04 01 01 00 02 18 05"), bytes.fromhex("04 01 01 00 06 18 05"),
                      bytes.fromhex("04 52 5A 19 B2 1B 80 8E 36 54 4D 40 26 04")]
            payload = frames[min(self.frame, 2)]
            status = 0xAF if self.frame < 2 else 0
            return bytes([status]) + payload if native else payload + bytes([0x91, status])
        if self.profile.startswith("FeliCa") and len(data) >= 16 and data[1] == 6:
            return b"\x1D\x07" + data[2:10] + b"\x00\x00\x01" + bytes(range(16)) + b"\x90\x00"
        if self.profile == "Topaz / Jewel":
            if data == b"\x00":
                return b"\x11\x48" + bytes(self.memory[:120]) + b"\x90\x00"
            if len(data) >= 2 and data[0] in (1, 0x53):
                if data[0] == 0x53 and len(data) == 3:
                    self.memory[data[1]] = data[2]
                return bytes([self.memory[data[1]]]) + b"\x90\x00"
        if data == api.GET_CHALLENGE.data:
            return bytes.fromhex("1A F7 F3 1B CD 2B A9 58 90 00")
        return b"\x6A\x81"