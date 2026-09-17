"""Demo-only smoke checks shared by source and frozen Windows releases."""

import json
from pathlib import Path
import sys
import traceback

from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QTimer, Qt

import acr122 as api


def receive_signal(signal, action=None):
    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    received = []

    def receive(*arguments):
        received.append(arguments)
        loop.quit()

    signal.connect(receive, Qt.ConnectionType.QueuedConnection)
    timer.start(20000)
    if action:
        action()
    if not received:
        loop.exec()
    timer.stop()
    signal.disconnect(receive)
    if not received:
        raise RuntimeError("Timed out waiting for a Qt signal.")
    return received[0]


def javascript(browser, source):
    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    received = []

    def receive(value):
        received.append(value)
        loop.quit()

    timer.start(20000)
    browser.page().runJavaScript(source, receive)
    if not received:
        loop.exec()
    timer.stop()
    if not received:
        raise RuntimeError("Embedded browser did not respond.")
    return received[0]


def run_release_check(application, window, destination: Path) -> int:
    from smartcard import scard
    import ndef

    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    report = {"ok": False, "version": application.applicationVersion(),
              "frozen": bool(getattr(sys, "frozen", False)), "hardware_access": False, "checks": []}
    application.setQuitOnLastWindowClosed(False)

    def check(condition, description):
        if not condition:
            raise RuntimeError(description)
        report["checks"].append(description)

    def operate(operation, options):
        receive_signal(window.worker.finished, lambda: window.submit(operation, options))
        application.processEvents()

    try:
        check(callable(scard.SCardTransmit) and callable(ndef.message_decoder), "Native PC/SC and NDEF imports")
        receive_signal(window.worker.state, window.refresh.emit)
        application.processEvents()
        check(window.source.currentText() == "Demo", "Demo-only source")
        receive_signal(window.worker.finished, window.toggle_connection)
        application.processEvents()
        check(window.state["connected"] and window.state["name"].startswith("DEMO"), "Demo worker connection")
        receive_signal(window.worker.finished, lambda: window.command(api.get_data(), window.show_uid))
        application.processEvents()
        check(window.uid.text() == "04 A1 B2 C3 D4 E5 F6", "UID through UI worker")
        operate("write_memory", {"profile": "MIFARE Classic 1K", "key": b"\xFF" * 6,
                                 "address": 4, "data": bytes(range(16)),
                                 "expected_generation": window.state["generation"]})
        receive_signal(window.worker.finished, window.read_memory)
        application.processEvents()
        check(window.memory_table.rowCount() == 3 and window.dump["rows"][0]["data"] == api.hex_text(bytes(range(16))),
              "Demo write verification and memory read")
        window.navigation.setCurrentRow(7)
        viewer = window.manual_view
        loaded = receive_signal(viewer.browser.loadFinished, viewer.load_manual)
        check(loaded[0], "Embedded Chromium manual load")
        check(javascript(viewer.browser, "document.images.length") >= 19, "Manual illustrations present")
        check(javascript(viewer.browser, "Array.from(document.images).every(image => image.complete && image.naturalWidth > 0)"),
              "Every manual image decoded")
        check(javascript(viewer.browser, "document.querySelectorAll('table').length") > 20, "Manual tables rendered")
        receive_signal(viewer.browser.page().findTextFinished, lambda: viewer.search.setText("authentication"))
        application.processEvents()
        check(int(viewer.match_count.text().split("/")[1]) > 0, "Full-guide search")
        viewer.search.clear()
        viewer.jump_to("memory")
        check(abs(javascript(viewer.browser, "document.getElementById('memory').getBoundingClientRect().top")) < 40,
              "Section navigation")
        for width, height in ((1400, 920), (1000, 720)):
            window.resize(width, height)
            application.processEvents()
            check(javascript(viewer.browser, "document.documentElement.scrollWidth <= window.innerWidth"),
                  f"Manual fits {width}x{height}")
        viewer.go_home()
        window.resize(1400, 920)
        paint_loop = QEventLoop()
        QTimer.singleShot(500, paint_loop.quit)
        paint_loop.exec()
        check(window.grab().save(str(destination.with_suffix(".png"))), "Packaged window screenshot")
        report["ok"] = True
    except Exception:
        report["error"] = traceback.format_exc()
    finally:
        try:
            if window.thread.isRunning():
                window.worker.cancel_event.set()
                receive_signal(window.thread.finished, window.shutdown.emit)
            window.started = False
            window.busy = False
            window.close()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            report["checks"].append("Clean worker and browser shutdown")
        except Exception:
            report["ok"] = False
            report["shutdown_error"] = traceback.format_exc()
        destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["ok"] else 1