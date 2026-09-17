"""Generate manual screenshots with the real UI and demo-only card sessions."""

from dataclasses import asdict
from pathlib import Path
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QTabWidget, QWidget
import ndef

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nfc_workbench import acr122 as api
from nfc_workbench.device import Session
from nfc_workbench.simulator import DemoTransport
from nfc_workbench.ui import Workbench, pretty


class ManualCapture:
    def __init__(self):
        self.application = QApplication.instance() or QApplication([])
        self.application.setStyle("Fusion")
        self.application.setQuitOnLastWindowClosed(False)
        self.destination = ROOT / "docs" / "images"
        self.destination.mkdir(parents=True, exist_ok=True)
        self.window = Workbench(demo=True, autostart=False)
        self.window.request.disconnect()
        self.window.request.connect(self.dispatch)
        self.session = None
        self.files = []
        self.window.show()
        self.choose_card("MIFARE Classic 1K")

    def choose_card(self, profile):
        self.window.demo_profile.blockSignals(True)
        self.window.demo_profile.setCurrentText(profile)
        self.window.demo_profile.blockSignals(False)
        self.dispatch("source", {"demo": True, "profile": profile})
        self.window.toggle_connection()
        self.window.notice.hide()
        self.window.write_data.clear()
        self.window.command(api.get_data(), self.window.show_uid)

    def dispatch(self, operation, options):
        try:
            if operation == "source":
                if not options["demo"]:
                    raise RuntimeError("Documentation capture never permits hardware mode.")
                if self.session:
                    self.session.transport.close()
                self.session = Session(DemoTransport(options["profile"]), self.window.add_activity)
                self.session.cancel = self.window.worker.cancel_event
                result = {"source": "Demo"}
            else:
                if not isinstance(self.session.transport, DemoTransport):
                    raise RuntimeError("Only DemoTransport is allowed for screenshots.")
                result = self.session.execute(operation, options, self.window.update_progress)
            self.window.operation_finished({"operation": operation, "result": result})
        except Exception as error:
            self.window.operation_failed(str(error))
            raise
        finally:
            if self.session:
                self.window.update_state(self.session.snapshot())

    def page(self, index, position="top"):
        self.window.resize(1400, 1000)
        self.window.navigation.setCurrentRow(index)
        self.application.processEvents()
        scroll = self.window.pages.widget(index)
        scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum() if position == "bottom" else 0)
        self.application.processEvents()
        if scroll.widget().width() > scroll.viewport().width():
            raise RuntimeError(f"Page {index} overflows horizontally.")

    def save(self, filename, widget=None):
        self.application.processEvents()
        image = (widget or self.window).grab().toImage()
        if image.isNull() or image.width() < 200 or image.height() < 30:
            raise RuntimeError(f"Empty screenshot: {filename}")
        if not image.save(str(self.destination / filename)):
            raise RuntimeError(f"Could not save {filename}")
        self.files.append(filename)

    def accept_demo_dialog(self):
        def accept():
            dialog = self.application.activeModalWidget()
            if not isinstance(dialog, QMessageBox) or self.window.source.currentIndex() != 1:
                raise RuntimeError("Expected a demo-only confirmation dialog.")
            dialog.done(QMessageBox.StandardButton.Yes)
        QTimer.singleShot(0, accept)

    def capture_confirmation(self):
        def cancel_after_capture():
            dialog = self.application.activeModalWidget()
            if not isinstance(dialog, QMessageBox):
                raise RuntimeError("Confirmation dialog was not displayed.")
            self.save("04-write-confirmation.png", dialog)
            dialog.reject()
        QTimer.singleShot(0, cancel_after_capture)
        self.window.write_memory()

    def run(self):
        self.window.command(api.FIRMWARE, self.window.show_overview)
        self.page(0)
        self.save("01-overview.png")
        self.save("02-connection-bar.png", self.window.findChild(QWidget, "connectionBar"))
        self.window.end_address.setValue(10)
        self.window.read_memory()
        self.page(1)
        self.save("03-memory-read.png")

        self.window.write_address.setValue(4)
        self.window.write_data.setText("48 65 6C 6C 6F 20 4E 46 43 00 00 00 00 00 00 00")
        self.page(1, "bottom")
        self.capture_confirmation()
        self.accept_demo_dialog()
        self.window.write_memory()
        if "verified" not in self.window.memory_result.toPlainText():
            raise RuntimeError("Demo write did not verify.")
        self.window.read_memory()
        self.page(1, "bottom")
        self.save("05-memory-write.png")

        self.window.value_amount.setValue(100)
        self.accept_demo_dialog()
        self.window.value_operation("store")
        self.window.value_amount.setValue(5)
        self.accept_demo_dialog()
        self.window.value_operation("increment")
        self.page(2)
        self.save("06-value-blocks.png")

        self.window.led_presets.setCurrentIndex(6)
        self.window.run_led()
        self.page(3)
        self.save("07-led-buzzer.png")
        self.window.command(api.PICC, self.window.show_picc)
        self.page(3, "bottom")
        self.save("08-polling-timeout.png")

        self.window.command(api.RF_STATUS, lambda result: self.window.overview_output.setPlainText(pretty(api.rf_status(result["data"]))))
        self.page(0)
        self.save("09-rf-status.png")

        self.choose_card("MIFARE Ultralight")
        payload = b"".join(ndef.message_encoder([ndef.TextRecord("Hello NFC")]))
        tlv = b"\x03" + bytes([len(payload)]) + payload + b"\xFE"
        tlv += bytes((-len(tlv)) % 4)
        for offset in range(0, len(tlv), 4):
            self.session.execute("write_memory", {"profile": "MIFARE Ultralight", "address": 4 + offset // 4,
                                                   "data": tlv[offset:offset + 4]})
        self.window.start_address.setValue(4)
        self.window.end_address.setValue(4 + len(tlv) // 4 - 1)
        self.window.read_memory()
        self.window.inspect_ndef()
        self.page(1, "bottom")
        self.save("10-ndef-inspection.png")

        self.choose_card("DESFire")
        self.window.desfire_version()
        self.page(4)
        self.save("11-desfire-wrapped.png")
        self.choose_card("DESFire")
        self.window.desfire_native.setCurrentIndex(1)
        self.window.desfire_version()
        self.page(4)
        self.save("12-desfire-native.png")

        self.choose_card("FeliCa 212K")
        tabs = self.window.pages.widget(4).findChild(QTabWidget)
        tabs.setCurrentIndex(1)
        self.window.read_felica()
        self.page(4)
        self.save("13-felica.png")

        self.choose_card("Topaz / Jewel")
        tabs.setCurrentIndex(2)
        self.window.topaz_value.setText("2A")
        self.window.topaz_pseudo.setChecked(True)
        self.accept_demo_dialog()
        self.window.topaz_operation("write")
        self.page(4)
        self.save("14-topaz.png")

        self.choose_card("MIFARE Classic 1K")
        self.window.console_preset.setCurrentIndex(0)
        self.accept_demo_dialog()
        self.window.send_console()
        self.page(5)
        self.save("15-apdu-console.png")

        self.window.log_search.setText("Load volatile key")
        matching = [index for index, entry in enumerate(self.window.activity_entries) if entry["command"] == "Load volatile key"]
        self.window.log_table.selectRow(matching[-1])
        self.page(6)
        self.save("16-activity-log.png")

        result = asdict(self.session.send(api.get_data(True)))
        self.window.show_ats(result)
        self.window.show_error(result["message"])
        self.page(0)
        self.save("17-error-state.png")

        self.window.notice.hide()
        self.session.disconnect()
        self.window.mode.setCurrentIndex(1)
        self.window.update_state(self.session.connect(DemoTransport.NAME, direct=True))
        self.window.command(api.FIRMWARE, self.window.show_overview)
        self.page(0)
        self.save("18-direct-connection.png")
        print(f"Generated {len(self.files)} demo-only screenshots in docs/images:")
        print("\n".join(self.files))

    def close(self):
        if self.session:
            self.session.transport.close()
        self.window.close()


def main():
    capture = ManualCapture()
    try:
        capture.run()
    finally:
        capture.close()


if __name__ == "__main__":
    main()