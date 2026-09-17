import unittest
from unittest.mock import patch

from nfc_workbench import acr122 as api
from nfc_workbench.device import Session, decode_ndef, parse_dump
from nfc_workbench.simulator import DemoTransport


class DeviceTests(unittest.TestCase):
    def setUp(self):
        self.log = []
        self.transport = DemoTransport()
        self.session = Session(self.transport, self.log.append)
        self.session.connect(self.transport.NAME)
        self.options = {"profile": "MIFARE Classic 1K", "key": b"\xFF" * 6,
                        "start": 4, "end": 8, "address": 4}

    def test_memory_write_verify_and_dump(self):
        result = self.session.execute("write_memory", dict(self.options, data=bytes(range(16))))
        self.assertIn("verified", result["result"])
        result = self.session.execute("read_memory", self.options)
        self.assertEqual(len(result["rows"]), 5)
        self.assertEqual(result["rows"][0]["data"], api.hex_text(bytes(range(16))))
        self.assertTrue(all(entry["tx"] == "[REDACTED]" for entry in self.log if entry["command"] == "Load volatile key"))

    def test_authentication_failure(self):
        with self.assertRaisesRegex(RuntimeError, "Operation failed"):
            self.session.execute("read_memory", dict(self.options, key=bytes(6)))

    def test_generation_guards_writes(self):
        generation = self.session.generation
        self.transport.counter += 1
        with self.assertRaisesRegex(RuntimeError, "changed"):
            self.session.execute("write_memory", dict(self.options, data=bytes(16), expected_generation=generation))
        self.assertFalse(self.session.connected)
        self.assertEqual(self.log, [])

    def test_values_and_restore(self):
        for operation, value, expected in [("store", -4, -4), ("increment", 5, 1), ("decrement", 2, -1)]:
            result = self.session.execute("value", dict(self.options, operation=operation, value=value))
            self.assertEqual(result["value"], expected)
        result = self.session.execute("value", dict(self.options, operation="restore", target=5))
        self.assertEqual(result["value"], -1)
        with self.assertRaises(ValueError):
            self.session.execute("value", dict(self.options, operation="restore", target=8))

    def test_protected_write_rejected(self):
        with self.assertRaises(ValueError):
            self.session.execute("write_memory", dict(self.options, address=7, data=bytes(16)))
        self.assertEqual(self.log, [])

    def test_direct_does_not_send_card_commands(self):
        self.session.connect(self.transport.NAME, True)
        self.assertEqual(self.session.send(api.FIRMWARE).data, b"ACR122U201")
        with self.assertRaisesRegex(RuntimeError, "Shared"):
            self.session.send(api.get_data())

    def test_desfire_chaining_modes(self):
        for native in (False, True):
            self.transport.profile = "DESFire"
            self.session.connect(self.transport.NAME)
            result = self.session.execute("desfire", {"native": native, "instruction": 0x60, "chain": True})
            self.assertEqual(result["frames"], 3)
            self.assertEqual(len(api.hex_bytes(result["data"])), 28)
            with self.assertRaises(ValueError):
                self.session.execute("desfire", {"native": not native, "instruction": 0x60})

    def test_other_tags(self):
        for pseudo in (False, True):
            self.transport.profile = "FeliCa 212K"
            self.session.connect(self.transport.NAME)
            result = self.session.execute("felica", {"service": 0x0109, "block": 0, "pseudo": pseudo})
            self.assertEqual(api.hex_bytes(result["data"]), bytes(range(16)))
            self.transport.profile = "Topaz / Jewel"
            self.session.connect(self.transport.NAME)
            result = self.session.execute("topaz", {"operation": "write", "address": 8, "value": 42, "pseudo": pseudo})
            self.assertEqual(result["data"], "2A")

    def test_cancel_and_wrong_profile(self):
        self.session.cancel.set()
        with self.assertRaisesRegex(RuntimeError, "Cancelled"):
            self.session.execute("read_memory", self.options)
        self.session.cancel.clear()
        with self.assertRaisesRegex(ValueError, "Selected"):
            self.session.execute("read_memory", dict(self.options, profile="MIFARE Ultralight"))

    def test_dump_validation(self):
        with self.assertRaises(ValueError):
            parse_dump('{"profile":"MIFARE Ultralight","rows":[{"address":2,"data":"00"}]}')

    def test_ndef_decode(self):
        import ndef
        payload = b"".join(ndef.message_encoder([ndef.TextRecord("Hi")]))
        tlv = b"\x03" + bytes([len(payload)]) + payload + b"\xFE"
        tlv += bytes((-len(tlv)) % 4)
        dump = {"profile": "MIFARE Ultralight", "rows": [
            {"address": 4 + offset // 4, "data": api.hex_text(tlv[offset:offset + 4])}
            for offset in range(0, len(tlv), 4)]}
        self.assertIn("Hi", decode_ndef(dump)[0])

    def test_desfire_chain_limit(self):
        self.transport.profile = "DESFire"
        self.session.connect(self.transport.NAME)
        with patch.object(self.transport, "exchange", return_value=b"\x91\xAF"):
            with self.assertRaisesRegex(RuntimeError, "32"):
                self.session.execute("desfire", {"native": False, "instruction": 0x60, "chain": True})
        self.assertEqual(len(self.log), 32)

    def test_failed_write_is_never_retried(self):
        exchange = self.transport.exchange
        writes = []

        def fail_write(data, escape=False):
            if data[:2] == b"\xFF\xD6":
                writes.append(data)
                raise RuntimeError("Driver lost response; write outcome unknown")
            return exchange(data, escape)

        with patch.object(self.transport, "exchange", side_effect=fail_write):
            with self.assertRaisesRegex(RuntimeError, "unknown"):
                self.session.execute("write_memory", dict(self.options, data=bytes(16)))
        self.assertEqual(len(writes), 1)

    def test_bad_felica_status_and_truncated_ndef(self):
        self.transport.profile = "FeliCa 212K"
        self.session.connect(self.transport.NAME)
        identifier = bytes(range(8))
        malformed = b"\x0C\x07" + identifier + b"\x01\xA1\x90\x00"
        with patch.object(self.transport, "exchange", return_value=malformed):
            with self.assertRaisesRegex(RuntimeError, "status flags"):
                self.session.execute("felica", {"identifier": identifier, "service": 0x0109, "block": 0, "pseudo": False})
        with self.assertRaisesRegex(ValueError, "beyond"):
            decode_ndef({"profile": "MIFARE Ultralight", "rows": [{"address": 4, "data": "03 20 D1 01"}]})


if __name__ == "__main__":
    unittest.main()