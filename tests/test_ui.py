import os
import sys

if sys.platform != "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QTimer, Qt, QUrl
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWidgets import QApplication

import acr122 as api
from ui import Workbench
from manual_view import ManualPage, ManualView, render_manual


def javascript(browser, source):
    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    result = []

    def received(value):
        result.append(value)
        loop.quit()

    timer.start(10000)
    browser.page().runJavaScript(source, received)
    loop.exec()
    timer.stop()
    if not result:
        raise AssertionError("Browser script did not complete")
    return result[0]


def await_signal(signal, action=None):
    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)
    received = []

    def receive(*args):
        received.append(args)
        loop.quit()

    signal.connect(receive, Qt.ConnectionType.QueuedConnection)
    timer.timeout.connect(loop.quit)
    timer.start(5000)
    if action:
        action()
    if not received:
        loop.exec()
    timer.stop()
    signal.disconnect(receive)
    return bool(received)


class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle("Fusion")
        cls.app.setQuitOnLastWindowClosed(False)

    def tearDown(self):
        for widget in self.app.topLevelWidgets():
            if isinstance(widget, (Workbench, ManualView)):
                widget.close()
                widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_all_pages_construct_and_fit(self):
        window = Workbench(demo=True, autostart=False)
        window.show()
        for width, height in ((1400, 920), (1000, 720)):
            window.resize(width, height)
            for index in range(window.pages.count()):
                window.navigation.setCurrentRow(index)
                self.app.processEvents()
                scroll = window.pages.widget(index)
                if hasattr(scroll, "viewport"):
                    self.assertLessEqual(scroll.widget().width(), scroll.viewport().width(), f"Page {index} at {width}")
                self.assertFalse(window.grab().isNull())
            self.assertEqual(window.pages.count(), 8)
        window.close()

    def test_manual_content_images_navigation_search_and_zoom(self):
        window = Workbench(demo=True, autostart=False)
        window.navigation.setCurrentRow(7)
        window.show()
        viewer = window.manual_view
        try:
            self.assertTrue(await_signal(viewer.browser.loadFinished, viewer.load_manual))
            self.assertEqual(javascript(viewer.browser, "document.images.length"), 19)
            self.assertEqual(javascript(viewer.browser, "Array.from(document.images).filter(image => !image.complete || !image.naturalWidth).map(image => image.src).join(',')"), "")
            self.assertGreater(javascript(viewer.browser, "document.querySelectorAll('table').length"), 20)
            self.assertIn("Maintain the Illustrations", javascript(viewer.browser, "document.body.innerText"))
            self.assertEqual(javascript(viewer.browser, "Array.from(document.querySelectorAll('a[href^=\"#\"]')).filter(link => !document.getElementById(link.hash.slice(1))).length"), 0)
            self.assertEqual(javascript(viewer.browser, "document.querySelectorAll('a > img').length"), 19)
            viewer.jump_to("glossary")
            self.assertLess(abs(javascript(viewer.browser, "document.getElementById('glossary').getBoundingClientRect().top")), 35)
            self.assertTrue(await_signal(viewer.browser.page().findTextFinished, lambda: viewer.search.setText("authentication")))
            self.app.processEvents()
            self.assertGreater(int(viewer.match_count.text().split("/")[1]), 1)
            self.assertTrue(await_signal(viewer.browser.page().findTextFinished, viewer.find))
            self.assertTrue(await_signal(viewer.browser.page().findTextFinished, lambda: viewer.find(True)))
            self.assertTrue(await_signal(viewer.browser.page().findTextFinished, lambda: viewer.search.setText("no-such-term-12345")))
            self.app.processEvents()
            self.assertEqual(viewer.match_count.text(), "0/0")
            viewer.zoom.setCurrentText("125%")
            self.assertEqual(viewer.browser.zoomFactor(), 1.25)
            for width in (1400, 1000):
                window.resize(width, 920)
                self.app.processEvents()
                self.assertTrue(javascript(viewer.browser, "document.documentElement.scrollWidth <= window.innerWidth"))
            viewer.go_home()
            self.assertLess(javascript(viewer.browser, "window.scrollY"), 80)
            with patch.object(window.worker.cancel_event, "clear"):
                window.submit("command", {"command": api.get_data()})
                self.assertTrue(viewer.isEnabled())
                self.assertFalse(window.pages.widget(1).isEnabled())
                window.end_busy()
        finally:
            window.close()
            viewer.browser.setHtml("")

    def test_manual_links_and_missing_document(self):
        root = Path(__file__).resolve().parents[1]
        page = ManualPage(root)
        clicked = QWebEnginePage.NavigationType.NavigationTypeLinkClicked
        sections = []
        page.section_requested.connect(sections.append)
        with patch("manual_view.QDesktopServices.openUrl", return_value=True) as open_url:
            section = QUrl.fromLocalFile(str(root / "docs" / "USER_MANUAL.md"))
            section.setFragment("memory")
            self.assertFalse(page.acceptNavigationRequest(section, clicked, True))
            self.assertEqual(sections, ["memory"])
            open_url.assert_not_called()
            image = QUrl.fromLocalFile(str(root / "docs" / "images" / "01-overview.png"))
            self.assertFalse(page.acceptNavigationRequest(image, clicked, True))
            open_url.assert_called_once_with(image)
            open_url.reset_mock()
            external = QUrl("https://nfc-forum.org/learn/what-is-nfc/")
            self.assertFalse(page.acceptNavigationRequest(external, clicked, True))
            open_url.assert_called_once_with(external)
            open_url.reset_mock()
            for target in (QUrl("javascript:alert(1)"), QUrl.fromLocalFile(str(root / "launch.cmd")),
                           QUrl.fromLocalFile(str(root.parent / "private.txt"))):
                self.assertFalse(page.acceptNavigationRequest(target, clicked, True))
            open_url.assert_not_called()
        page.deleteLater()
        with TemporaryDirectory() as folder:
            viewer = ManualView(Path(folder))
            self.assertIn("USER_MANUAL.md", viewer.message.text())
            self.assertFalse(viewer.message.isHidden())
            viewer.close()
            viewer.deleteLater()

    def test_manual_renderer_preserves_source_and_disables_raw_html(self):
        with TemporaryDirectory() as folder:
            source = Path(folder) / "manual.md"
            source.write_text("# A heading\n\n# A heading\n\n<script>alert(1)</script>\n", encoding="utf-8")
            document, sections = render_manual(source)
            self.assertEqual(sections, [("A heading", "a-heading"), ("A heading", "a-heading-1")])
            self.assertNotIn("<script>", document)
            source.write_text("# Updated guide", encoding="utf-8")
            self.assertIn("Updated guide", render_manual(source)[0])

    def test_demo_worker_connection_and_read(self):
        window = Workbench(demo=True)
        try:
            self.assertTrue(await_signal(window.worker.state))
            self.app.processEvents()
            self.assertEqual(window.readers.count(), 1)
            self.assertTrue(await_signal(window.worker.finished, window.toggle_connection))
            self.app.processEvents()
            self.assertTrue(window.state["connected"])
            self.assertTrue(await_signal(window.worker.finished, lambda: window.command(api.get_data(), window.show_uid)))
            self.app.processEvents()
            self.assertEqual(window.uid.text(), "04 A1 B2 C3 D4 E5 F6")
            self.assertTrue(await_signal(window.worker.finished, window.read_memory))
            self.app.processEvents()
            self.assertEqual(window.memory_table.rowCount(), 3)
            self.assertFalse(window.busy)
            window.write_data.setText("00 " * 16)
            before = len(window.activity_entries)
            with patch.object(window, "confirm", return_value=None):
                window.write_memory()
            self.assertEqual(len(window.activity_entries), before)
            self.assertFalse(window.busy)
            with patch.object(window, "confirm", return_value=window.state["generation"]):
                self.assertTrue(await_signal(window.worker.finished, window.write_memory))
            self.app.processEvents()
            self.assertIn("verified", window.memory_result.toPlainText())
            self.assertTrue(await_signal(window.worker.finished, lambda: window.control_command(api.FIRMWARE)))
            self.app.processEvents()
            self.assertIn("ACR122U201", window.controls_result.toPlainText())
            window.led_presets.setCurrentIndex(1)
            self.assertTrue(await_signal(window.worker.finished, window.run_led))
            self.app.processEvents()
            self.assertIn("90 03", window.controls_result.toPlainText())
            with patch.object(window, "confirm", return_value=window.state["generation"]):
                self.assertTrue(await_signal(window.worker.finished, lambda: window.value_operation("store")))
            self.app.processEvents()
            self.assertIn('"value": 1', window.value_result.toPlainText())
            self.assertTrue(await_signal(window.worker.finished, lambda: window.command(api.get_data(True), window.show_ats)))
            self.app.processEvents()
            self.assertFalse(window.notice.isHidden())
            self.assertEqual(window.statusBar().currentMessage(), "Operation failed")
            self.assertTrue(await_signal(window.worker.finished, lambda: window.demo_present.setChecked(False)))
            self.app.processEvents()
            self.assertFalse(window.state["connected"])
        finally:
            self.assertTrue(await_signal(window.thread.finished, window.close))
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()