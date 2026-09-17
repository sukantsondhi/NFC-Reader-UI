"""Offline, read-only viewer for the bundled Markdown user manual."""

from html import escape
import json
from pathlib import Path
import re

from markdown_it import MarkdownIt
from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)
import qtawesome as qta


STYLE = """
body { margin: 0; padding: 24px 30px 64px; color: #252d39; background: white;
       font: 15px/1.65 'Bahnschrift', 'Segoe UI', sans-serif; overflow-wrap: anywhere; }
main { max-width: 1060px; margin: auto; }
h1, h2, h3 { line-height: 1.3; color: #194aa8; scroll-margin-top: 20px; }
h1 { font-size: 28px; } h2 { font-size: 23px; margin-top: 36px; }
h3 { font-size: 18px; margin-top: 26px; }
a { color: #225ccb; } a:hover { color: #153d87; }
a:focus-visible { outline: 2px solid #225ccb; outline-offset: 3px; }
img { max-width: 100%; height: auto; border: 1px solid #d7e0ec; border-radius: 4px; }
table { border-collapse: collapse; width: 100%; margin: 18px 0; table-layout: fixed; }
th, td { border: 1px solid #d7e0ec; padding: 10px; vertical-align: top; overflow-wrap: anywhere; }
th { background: #eaf0fa; text-align: left; } tr:nth-child(even) { background: #f7f9fd; }
code { font-family: 'Consolas', monospace; font-size: 14px; background: #eef3fb; }
pre { padding: 16px; background: #eef3fb; border-radius: 4px; white-space: pre-wrap; }
blockquote { margin: 20px 0; padding: 6px 18px; border-left: 4px solid #3478e5; background: #eff5ff; }
li { margin: 6px 0; } hr { border: 0; border-top: 1px solid #d7e0ec; }
@media (max-width: 700px) { body { padding: 16px; font-size: 14px; } th, td { padding: 6px; } }
"""


def render_manual(path: Path) -> tuple[str, list[tuple[str, str]]]:
    parser = MarkdownIt("commonmark", {"html": False}).enable("table")
    image_rule = parser.renderer.rules["image"]

    def linked_image(tokens, index, options, environment):
        source = escape(tokens[index].attrGet("src") or "", quote=True)
        return f'<a href="{source}">{image_rule(tokens, index, options, environment)}</a>'

    parser.renderer.rules["image"] = linked_image
    tokens = parser.parse(path.read_text(encoding="utf-8"))
    sections = []
    counts = {}
    for index, token in enumerate(tokens):
        if token.type == "heading_open":
            title = tokens[index + 1].content
            base = re.sub(r"[^a-z0-9 _-]", "", title.lower()).replace(" ", "-")
            count = counts.get(base, 0)
            counts[base] = count + 1
            anchor = f"{base}-{count}" if count else base
            token.attrSet("id", anchor)
            sections.append((title, anchor))
        for child in token.children or []:
            if child.type == "image":
                child.attrSet("loading", "eager")
    content = parser.renderer.render(tokens, parser.options, {})
    policy = "default-src 'none'; img-src 'self' file: data:; style-src 'unsafe-inline'; base-uri 'self';"
    document = (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
                f'<meta name="viewport" content="width=device-width, initial-scale=1">'
                f'<meta http-equiv="Content-Security-Policy" content="{escape(policy, quote=True)}">'
                f'<title>NFC Workbench User Manual</title><style>{STYLE}</style></head>'
                f'<body><main>{content}</main></body></html>')
    return document, sections


class ManualPage(QWebEnginePage):
    section_requested = Signal(str)
    link_blocked = Signal(str)

    def __init__(self, root: Path, parent=None):
        super().__init__(parent)
        self.root = root.resolve()

    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        if navigation_type != QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
            return True
        if url.isLocalFile():
            target = Path(url.toLocalFile()).resolve()
            if target == self.root / "docs" / "USER_MANUAL.md" and url.fragment():
                self.section_requested.emit(url.fragment())
            elif target.is_relative_to(self.root) and target.is_file():
                if target.suffix.lower() in (".pdf", ".png", ".md", ".txt"):
                    QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
                else:
                    self.link_blocked.emit("This source-file link is available in the workspace: " + target.name)
            else:
                self.link_blocked.emit("This local link is unavailable or outside the application folder.")
        elif url.scheme() in ("http", "https"):
            QDesktopServices.openUrl(url)
        else:
            self.link_blocked.emit("Unsupported link type.")
        return False


class ManualView(QWidget):
    def __init__(self, root: Path, parent=None):
        super().__init__(parent)
        self.manual_path = root / "docs" / "USER_MANUAL.md"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 16)
        toolbar = QHBoxLayout()
        self.sections = QComboBox()
        self.sections.setMinimumContentsLength(12)
        self.sections.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.sections.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.sections.setAccessibleName("Manual section")
        self.sections.setToolTip("Jump to a section")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find in manual")
        self.search.setAccessibleName("Find in manual")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(130)
        self.search.setMaximumWidth(260)
        self.match_count = QLabel()
        self.match_count.setMinimumWidth(55)
        self.zoom = QComboBox()
        self.zoom.addItems(["75%", "90%", "100%", "110%", "125%", "150%"])
        self.zoom.setCurrentText("100%")
        self.zoom.setAccessibleName("Manual zoom")
        self.zoom.setToolTip("Text and image zoom")
        self.zoom.setFixedWidth(85)
        self.home = self.icon_button("fa5s.arrow-up", "Top of manual", self.go_home)
        self.previous = self.icon_button("fa5s.chevron-up", "Previous match", lambda: self.find(True))
        self.next = self.icon_button("fa5s.chevron-down", "Next match", self.find)
        self.reload_button = self.icon_button("fa5s.sync-alt", "Reload manual from disk", self.load_manual)
        for control in (self.home, self.sections, self.search, self.previous, self.next,
                        self.match_count, self.zoom, self.reload_button):
            toolbar.addWidget(control)
        layout.addLayout(toolbar)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.hide()
        layout.addWidget(self.message)
        self.browser = QWebEngineView()
        self.browser.setAccessibleName("Illustrated user manual")
        self.browser.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        page = ManualPage(root, self.browser)
        self.browser.setPage(page)
        page.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        page.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False)
        page.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        page.section_requested.connect(self.jump_to)
        page.link_blocked.connect(self.show_message)
        page.findTextFinished.connect(self.show_matches)
        self.browser.loadFinished.connect(self.loaded)
        layout.addWidget(self.browser, 1)
        self.sections.activated.connect(lambda index: self.jump_to(self.sections.itemData(index)))
        self.search.textChanged.connect(lambda _: self.find())
        self.search.returnPressed.connect(self.find)
        self.zoom.currentTextChanged.connect(lambda value: self.browser.setZoomFactor(int(value[:-1]) / 100))
        self.load_manual()

    def icon_button(self, icon, title, handler):
        control = QPushButton(qta.icon(icon, color="#46688f"), "")
        control.setFixedWidth(38)
        control.setToolTip(title)
        control.setAccessibleName(title)
        control.clicked.connect(lambda checked=False: handler())
        return control

    def load_manual(self):
        self.message.hide()
        self.sections.clear()
        try:
            document, sections = render_manual(self.manual_path)
        except (OSError, UnicodeError) as error:
            self.browser.setHtml("<h1>User manual unavailable</h1><p>Restore docs/USER_MANUAL.md and reload.</p>")
            self.show_message(str(error))
            return
        for title, anchor in sections:
            self.sections.addItem(title, anchor)
        self.browser.setHtml(document, QUrl.fromLocalFile(str(self.manual_path)))

    def loaded(self, success):
        if not success:
            self.show_message("The manual could not be loaded. Reload to try again.")
        self.find()

    def show_message(self, text):
        self.message.setText(text)
        self.message.show()

    def jump_to(self, anchor):
        self.browser.page().runJavaScript(
            f"document.getElementById({json.dumps(anchor)})?.scrollIntoView();")
        index = self.sections.findData(anchor)
        if index >= 0:
            self.sections.setCurrentIndex(index)

    def go_home(self):
        self.jump_to(self.sections.itemData(0))

    def find(self, backwards=False):
        flags = QWebEnginePage.FindFlag.FindBackward if backwards else QWebEnginePage.FindFlag(0)
        self.browser.findText(self.search.text(), flags)

    def show_matches(self, result):
        self.match_count.setText(f"{result.activeMatch()}/{result.numberOfMatches()}" if self.search.text() else "")