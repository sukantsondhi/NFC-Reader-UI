import unittest

from nfc_workbench import acr122 as api


class ProtocolTests(unittest.TestCase):
    def test_manual_memory_commands(self):
        examples = [
            (api.get_data(), "FF CA 00 00 00"),
            (api.get_data(True), "FF CA 01 00 00"),
            (api.load_key(b"\xFF" * 6), "FF 82 00 00 06 FF FF FF FF FF FF"),
            (api.authenticate(4), "FF 86 00 00 05 01 00 04 60 00"),
            (api.authenticate(4, legacy=True), "FF 88 00 04 60 00"),
            (api.read_binary(4), "FF B0 00 04 10"),
            (api.write_binary(4, bytes(range(4))), "FF D6 00 04 04 00 01 02 03"),
            (api.value_operation(5, 0, -4), "FF D7 00 05 05 00 FF FF FF FC"),
            (api.read_value(5), "FF B1 00 05 04"),
            (api.restore_value(5, 6), "FF D7 00 05 02 03 06"),
        ]
        for command, expected in examples:
            with self.subTest(command=command.name):
                self.assertEqual(api.hex_text(command.data), expected)

    def test_special_responses(self):
        firmware = api.decode(b"ACR122U201", api.ResponseKind.FIRMWARE)
        self.assertTrue(firmware.ok)
        self.assertEqual(firmware.data, b"ACR122U201")
        self.assertTrue(api.decode(b"\x90\x03", api.ResponseKind.LED).ok)
        self.assertTrue(api.decode(b"\x90\xFF", api.ResponseKind.PICC).ok)
        self.assertFalse(api.decode(b"\x90\x03").ok)
        self.assertFalse(api.decode(b"\x63\x00", api.ResponseKind.FIRMWARE).ok)

    def test_desfire_does_not_drop_native_payload(self):
        response = api.decode(bytes.fromhex("AF 25 9C 65 0C 87 65 1D D7"), api.ResponseKind.NATIVE)
        self.assertEqual(response.data, bytes.fromhex("25 9C 65 0C 87 65 1D D7"))
        self.assertTrue(response.more)
        self.assertEqual(api.decode(bytes.fromhex("00 90 00"), api.ResponseKind.NATIVE).data, b"")
        self.assertTrue(api.decode(bytes.fromhex("04 01 91 AF"), api.ResponseKind.DESFIRE).more)
        self.assertFalse(api.decode(bytes.fromhex("91 AE"), api.ResponseKind.DESFIRE).ok)

    def test_direct_and_topaz(self):
        self.assertEqual(api.hex_text(api.topaz("read", pseudo=True).data), "FF 00 00 00 05 D4 40 01 01 08")
        self.assertFalse(api.decode(bytes.fromhex("D5 41 14 90 00"), api.ResponseKind.DIRECT).ok)
        self.assertEqual(api.rf_status(bytes.fromhex("D5 05 00 00 00 80"))["targets"], [])
        with self.assertRaises(ValueError):
            api.direct(bytes(256))

    def test_felica_length_and_endianness(self):
        frame = api.felica_read(bytes(8), 0x0109, 0).data
        self.assertEqual(frame[0], len(frame))
        self.assertEqual(frame[-6:], bytes.fromhex("01 09 01 01 80 00"))

    def test_memory_boundaries(self):
        self.assertEqual([api.sector_of(block) for block in (127, 128, 143, 144, 255)], [31, 32, 32, 33, 39])
        for block in (3, 127, 143, 255):
            self.assertTrue(api.is_trailer(block))
        self.assertFalse(api.is_trailer(131))
        with self.assertRaises(ValueError):
            api.restore_value(127, 128)
        with self.assertRaises(ValueError):
            api.validate_address("MIFARE Ultralight", 2, write=True)
        with self.assertRaises(ValueError):
            api.validate_address("MIFARE Classic 1K", 64)

    def test_atr(self):
        atr = bytes.fromhex("3B 8F 80 01 80 4F 0C A0 00 00 03 06 03 00 01 00 00 00 00 6A")
        self.assertEqual(api.identify_atr(atr), "MIFARE Classic 1K")

    def test_peripheral_commands_and_led_examples(self):
        for encoded in api.LED_EXAMPLES.values():
            data = api.hex_bytes(encoded)
            self.assertEqual(api.led(data[3], *data[5:]).data, data)
        self.assertEqual(api.FIRMWARE.data, bytes.fromhex("FF 00 48 00 00"))
        self.assertEqual(api.PICC.data, bytes.fromhex("FF 00 50 00 00"))
        for instruction in (0x41, 0x51, 0x52):
            for parameter in (0, 1, 254, 255):
                self.assertEqual(api.reader_command("test", instruction, parameter).data,
                                 bytes([255, 0, instruction, parameter, 0]))

    def test_reject_invalid_input_and_responses(self):
        for invalid in ("F", "GG", "0xFF", "FF:00"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                api.hex_bytes(invalid)
        for malformed in (b"", b"\x90"):
            self.assertFalse(api.decode(malformed).ok)
        for key, slot in ((bytes(5), 0), (bytes(6), 2)):
            with self.assertRaises(ValueError):
                api.load_key(key, slot)
        for value in (-(2**31), 2**31 - 1):
            command = api.value_operation(4, 0, value)
            self.assertEqual(int.from_bytes(command.data[-4:], "big", signed=True), value)
        with self.assertRaises(ValueError):
            api.value_operation(4, 0, 2**31)
        with self.assertRaises(ValueError):
            api.rf_status(bytes.fromhex("D5 05 00 00 01 80"))


if __name__ == "__main__":
    unittest.main()