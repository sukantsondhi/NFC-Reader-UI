"""ACR122U desktop workbench."""

import csv
import io
import json
from pathlib import Path
import sys

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont, QCloseEvent
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout,
    QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QScrollArea, QSizePolicy, QSpinBox, QStackedWidget,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)
import qtawesome as qta

from . import acr122 as api
from .device import decode_ndef, parse_dump
from .manual_view import ManualView
from .worker import ReaderWorker


ROOT = Path(__file__).resolve().parents[1]
ASSETS = Path(__file__).resolve().parent / "assets"


def pretty(value):
    return json.dumps(value, indent=2, default=lambda item: api.hex_text(item) if isinstance(item, bytes) else str(item))


def button(text, icon, handler, style=""):
    control = QPushButton(qta.icon(icon, color="white" if style == "primary" else "#46688f"), text)
    control.setObjectName(style)
    control.clicked.connect(lambda checked=False: handler())
    if not text:
        control.setFixedWidth(42)
    return control


def spin(low=0, high=255, value=0, suffix=""):
    control = QSpinBox()
    control.setRange(low, high)
    control.setValue(value)
    control.setSuffix(suffix)
    control.setMinimumWidth(110)
    return control


def combo(items):
    control = QComboBox()
    control.addItems(items)
    control.setMinimumContentsLength(8)
    control.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    return control


def line(text="", placeholder=""):
    control = QLineEdit(text)
    control.setPlaceholderText(placeholder)
    control.setFont(QFont("Consolas", 11))
    return control


def row(*widgets):
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)
    for widget in widgets:
        layout.addWidget(widget)
    return container


def section(layout, title):
    label = QLabel(title)
    label.setObjectName("sectionTitle")
    layout.addWidget(label)


def form(layout):
    result = QFormLayout()
    result.setSpacing(12)
    result.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    result.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    layout.addLayout(result)
    return result


def output(height=140):
    control = QPlainTextEdit()
    control.setReadOnly(True)
    control.setFont(QFont("Consolas", 10))
    control.setMinimumHeight(height)
    control.setMaximumBlockCount(2000)
    return control


class Workbench(QMainWindow):
    request = Signal(str, object)
    refresh = Signal()
    shutdown = Signal()

    def __init__(self, demo=False, autostart=True):
        super().__init__()
        self.setWindowTitle("NFC Workbench | ACR122U")
        self.setWindowIcon(qta.icon("fa5s.broadcast-tower", color="#225ccb"))
        self.resize(1400, 920)
        self.setMinimumSize(960, 650)
        stylesheet = (ASSETS / "theme.qss").read_text(encoding="utf-8")
        self.setStyleSheet(stylesheet.replace("@ASSETS@", ASSETS.as_posix()))
        self.state = {"connected": False, "generation": 0, "readers": {}, "direct": False}
        self.busy = False
        self.closing = False
        self.callback = None
        self.activity_entries = []
        self.dump = {"profile": "MIFARE Classic 1K", "rows": []}
        self.started = autostart
        self.build_shell(demo)
        self.thread = QThread(self)
        self.worker = ReaderWorker(demo)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.start)
        self.request.connect(self.worker.execute)
        self.refresh.connect(self.worker.poll)
        self.shutdown.connect(self.worker.stop)
        self.worker.stopped.connect(self.thread.quit)
        self.worker.stopped.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread_finished)
        self.worker.state.connect(self.update_state)
        self.worker.activity.connect(self.add_activity)
        self.worker.progress.connect(self.update_progress)
        self.worker.finished.connect(self.operation_finished)
        self.worker.failed.connect(self.operation_failed)
        self.worker.service_error.connect(self.service_error)
        if autostart:
            self.thread.start()

    def build_shell(self, demo):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        shell = QHBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(200)
        side = QVBoxLayout(sidebar)
        brand = QLabel("NFC Workbench")
        brand.setObjectName("brand")
        side.addWidget(brand)
        subtitle = QLabel("ACR122U  /  USB READER")
        subtitle.setObjectName("brandSub")
        side.addWidget(subtitle)
        self.navigation = QListWidget()
        self.navigation.setObjectName("navigation")
        names = [("Overview", "fa5s.satellite-dish"), ("Memory", "fa5s.th"),
                 ("Value blocks", "fa5s.calculator"), ("Reader controls", "fa5s.sliders-h"),
                 ("Other tags", "fa5s.layer-group"), ("APDU console", "fa5s.terminal"),
                 ("Activity log", "fa5s.stream"), ("User Manual", "fa5s.book")]
        for name, icon in names:
            self.navigation.addItem(QListWidgetItem(qta.icon(icon, color="#bed2f1"), name))
        side.addWidget(self.navigation, 1)
        self.source_badge = QLabel("LOCAL PC/SC\nACS API v2.04")
        self.source_badge.setObjectName("sidebarNote")
        side.addWidget(self.source_badge)
        manual = button("API manual", "fa5s.book-open", self.open_manual)
        manual.setToolTip("Open a local ACS API PDF, or the official ACS download")
        side.addWidget(manual)
        shell.addWidget(sidebar)
        main = QVBoxLayout()
        main.setSpacing(0)
        shell.addLayout(main, 1)
        connection = QWidget()
        connection.setObjectName("connectionBar")
        bar = QHBoxLayout(connection)
        bar.setContentsMargins(20, 16, 20, 16)
        self.source = combo(["Hardware", "Demo"])
        self.source.setCurrentIndex(int(demo))
        self.source.setFixedWidth(115)
        self.source.setToolTip("Hardware talks to PC/SC; Demo only changes simulated memory")
        self.readers = combo([])
        self.readers.setMinimumWidth(130)
        self.readers.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.readers.setToolTip("PC/SC reader")
        self.mode = combo(["Shared T=1", "Direct / Escape"])
        self.mode.setFixedWidth(155)
        self.mode.setToolTip("Shared requires a card; Direct controls reader peripherals without a card")
        self.refresh_button = button("", "fa5s.sync-alt", self.refresh.emit)
        self.refresh_button.setToolTip("Refresh readers and card presence")
        self.connect_button = button("Connect", "fa5s.plug", self.toggle_connection, "primary")
        for widget in (self.source, self.readers, self.mode, self.refresh_button, self.connect_button):
            bar.addWidget(widget)
        main.addWidget(connection)
        self.notice = QLabel()
        self.notice.setObjectName("notice")
        self.notice.setWordWrap(True)
        self.notice.hide()
        main.addWidget(self.notice)
        self.pages = QStackedWidget()
        main.addWidget(self.pages, 1)
        self.build_overview(demo)
        self.build_memory()
        self.build_values()
        self.build_controls()
        self.build_other_tags()
        self.build_console()
        self.build_activity()
        self.manual_view = ManualView(ROOT)
        self.pages.addWidget(self.manual_view)
        self.navigation.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.navigation.setCurrentRow(0)
        self.source.currentIndexChanged.connect(self.change_source)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFixedWidth(160)
        self.cancel_button = button("", "fa5s.stop", self.cancel_operation)
        self.cancel_button.setToolTip("Cancel between commands; a command already sent cannot be undone")
        self.cancel_button.setEnabled(False)
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().addPermanentWidget(self.cancel_button)
        self.statusBar().showMessage("Ready")

    def page(self, title, subtitle):
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(12)
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)
        label = QLabel(subtitle)
        label.setObjectName("muted")
        label.setWordWrap(True)
        layout.addWidget(label)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        self.pages.addWidget(scroll)
        return layout

    def build_overview(self, demo):
        layout = self.page("Reader overview", "ACR122U / Contactless interface")
        self.connection_status = QLabel("Disconnected")
        self.connection_status.setObjectName("statusBadge")
        layout.addWidget(self.connection_status, alignment=Qt.AlignmentFlag.AlignLeft)
        self.demo_panel = QWidget()
        panel = QHBoxLayout(self.demo_panel)
        panel.setContentsMargins(0, 0, 0, 0)
        self.demo_profile = combo(list(api.PROFILES) + ["DESFire", "FeliCa 212K", "FeliCa 424K", "Topaz / Jewel"])
        self.demo_present = QCheckBox("Demo card present")
        self.demo_present.setChecked(True)
        panel.addWidget(QLabel("DEMO CARD"))
        panel.addWidget(self.demo_profile, 1)
        panel.addWidget(self.demo_present)
        layout.addWidget(self.demo_panel)
        self.demo_panel.setVisible(demo)
        self.demo_profile.currentIndexChanged.connect(self.change_source)
        self.demo_present.toggled.connect(lambda present: self.submit("demo_card", {"present": present}))
        section(layout, "Card identity")
        self.uid = QLabel("No UID read")
        self.uid.setObjectName("heroValue")
        self.uid.setWordWrap(True)
        self.uid.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.uid)
        self.card_type = QLabel("No active card")
        self.card_type.setObjectName("fieldValue")
        self.card_type.setWordWrap(True)
        self.atr_label = QLabel("-")
        self.atr_label.setObjectName("fieldValue")
        self.atr_label.setWordWrap(True)
        self.atr_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.ats_label = QLabel("-")
        self.ats_label.setObjectName("fieldValue")
        self.ats_label.setWordWrap(True)
        self.ats_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        identity = form(layout)
        identity.addRow("Card family", self.card_type)
        identity.addRow("ATR", self.atr_label)
        identity.addRow("ATS", self.ats_label)
        copy_uid = button("", "fa5s.copy", lambda: QApplication.clipboard().setText(self.uid.text()))
        copy_uid.setToolTip("Copy displayed UID")
        self.uid_button = button("Read UID", "fa5s.fingerprint", lambda: self.command(api.get_data(), self.show_uid), "primary")
        layout.addWidget(row(self.uid_button, button("Read ATS", "fa5s.id-card", lambda: self.command(api.get_data(True), self.show_ats)), copy_uid))
        section(layout, "Reader & RF status")
        layout.addWidget(row(button("Firmware", "fa5s.microchip", lambda: self.command(api.FIRMWARE, self.show_overview)),
                             button("RF status", "fa5s.broadcast-tower", self.get_rf_status),
                             button("Polling parameter", "fa5s.wave-square", lambda: self.command(api.PICC, self.show_overview))))
        self.overview_output = output(160)
        layout.addWidget(self.overview_output)
        layout.addStretch()

    def key_options_panel(self, layout):
        section(layout, "Authentication")
        self.key = line("FF FF FF FF FF FF")
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setMaxLength(64)
        self.key.setToolTip("Six-byte key; kept in memory only and redacted from the command log")
        show_key = QCheckBox("Show key")
        show_key.toggled.connect(lambda visible: self.key.setEchoMode(QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password))
        self.key_slot = combo(["Slot 0", "Slot 1"])
        self.key_type = combo(["Key A (60)", "Key B (61)"])
        self.auto_auth = QCheckBox("Authenticate each sector automatically")
        self.auto_auth.setChecked(True)
        self.legacy_auth = QCheckBox("Legacy FF 88 authentication")
        self.legacy_auth.setToolTip("Obsolete PC/SC V2.01 command; modern FF 86 is the default")
        key_form = form(layout)
        key_form.addRow("Key (hex)", row(self.key, show_key))
        key_form.addRow("Reader key slot", row(self.key_slot, self.key_type))
        layout.addWidget(row(self.auto_auth, self.legacy_auth))

    def build_memory(self):
        layout = self.page("Card memory", "MIFARE Classic 1K / 4K / Mini / original Ultralight")
        self.profile = combo(list(api.PROFILES))
        self.start_address = spin(value=4)
        self.end_address = spin(value=6)
        memory_form = form(layout)
        memory_form.addRow("Memory layout", self.profile)
        memory_form.addRow("Read range (decimal)", row(self.start_address, QLabel("through"), self.end_address))
        self.key_options_panel(layout)
        layout.addWidget(row(button("Load key", "fa5s.key", self.load_key),
                             button("Authenticate start block", "fa5s.lock-open", self.authenticate)))
        self.ndef_delay = QCheckBox("Classic 4K NDEF: 2-second delay before each block read")
        layout.addWidget(self.ndef_delay)
        self.read_memory_button = button("Read range", "fa5s.download", self.read_memory, "primary")
        layout.addWidget(row(self.read_memory_button,
                             button("Read all", "fa5s.th", lambda: self.read_memory(True)),
                             button("Import", "fa5s.folder-open", self.import_dump),
                             button("Export", "fa5s.file-export", self.export_dump),
                             button("Decode NDEF", "fa5s.tag", self.inspect_ndef)))
        self.memory_table = QTableWidget(0, 4)
        self.memory_table.setHorizontalHeaderLabels(["Address", "Region", "Hex data", "ASCII"])
        self.memory_table.setMinimumHeight(235)
        self.memory_table.setAlternatingRowColors(True)
        self.memory_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.memory_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.memory_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.memory_table.verticalHeader().hide()
        self.memory_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.memory_table.setColumnWidth(0, 95)
        self.memory_table.setColumnWidth(1, 110)
        self.memory_table.setColumnWidth(3, 155)
        self.memory_table.itemSelectionChanged.connect(self.select_memory_row)
        layout.addWidget(self.memory_table)
        self.dump_label = QLabel("No memory captured")
        self.dump_label.setObjectName("muted")
        layout.addWidget(self.dump_label)
        section(layout, "Write one block / page")
        self.write_address = spin(value=4)
        self.write_data = line("", "Complete block/page in hexadecimal")
        self.protected_write = QCheckBox("Allow protected-area write")
        self.protected_write.setToolTip("Manufacturer, lock/OTP and trailer writes can permanently damage or lock a card")
        write_form = form(layout)
        write_form.addRow("Address (decimal)", self.write_address)
        write_form.addRow("Data (hex)", self.write_data)
        layout.addWidget(row(self.protected_write, button("Write & verify", "fa5s.pen", self.write_memory, "danger")))
        self.memory_result = output(95)
        layout.addWidget(self.memory_result)
        self.profile.currentIndexChanged.connect(self.update_memory_limits)
        self.update_memory_limits()

    def build_values(self):
        layout = self.page("Value blocks", "MIFARE Classic / Mini | signed 32-bit integers")
        self.value_profile_label = QLabel()
        self.value_profile_label.setObjectName("statusBadge")
        layout.addWidget(self.value_profile_label)
        value_form = form(layout)
        self.value_address = spin(value=5)
        self.value_amount = spin(-(2**31), 2**31 - 1, 1)
        self.value_target = spin(value=6)
        value_form.addRow("Block (decimal)", self.value_address)
        value_form.addRow("Value / delta", self.value_amount)
        value_form.addRow("Restore target", self.value_target)
        layout.addWidget(row(button("Read value", "fa5s.download", lambda: self.value_operation("read"), "primary"),
                             button("Store", "fa5s.save", lambda: self.value_operation("store"), "danger")))
        layout.addWidget(row(button("Increment", "fa5s.plus", lambda: self.value_operation("increment"), "danger"),
                             button("Decrement", "fa5s.minus", lambda: self.value_operation("decrement"), "danger"),
                             button("Restore / copy", "fa5s.copy", lambda: self.value_operation("restore"), "danger")))
        self.value_result = output(200)
        layout.addWidget(self.value_result)
        layout.addStretch()
        self.update_value_profile()
        self.profile.currentTextChanged.connect(self.update_value_profile)

    def build_controls(self):
        layout = self.page("Reader controls", "ACR122U peripherals / contactless operating parameters")
        section(layout, "LED & buzzer sequence")
        led_grid = QGridLayout()
        self.led_bits = []
        labels = ["Red: final on", "Green: final on", "Red: update final state", "Green: update final state",
                  "Red: initial blink on", "Green: initial blink on", "Red: blink enabled", "Green: blink enabled"]
        for index, text in enumerate(labels):
            control = QCheckBox(text)
            control.setToolTip(f"P2 bit {index}")
            self.led_bits.append(control)
            led_grid.addWidget(control, index // 2, index % 2)
        layout.addLayout(led_grid)
        self.first_duration = spin(suffix=" x 100 ms")
        self.second_duration = spin(suffix=" x 100 ms")
        self.repetitions = spin()
        self.buzzer_link = combo(["Off", "During T1", "During T2", "During T1 + T2"])
        led_form = form(layout)
        led_form.addRow("Duration T1 / T2", row(self.first_duration, self.second_duration))
        led_form.addRow("Repetitions / buzzer", row(self.repetitions, self.buzzer_link))
        self.led_presets = combo(list(api.LED_EXAMPLES))
        self.led_presets.currentIndexChanged.connect(self.fill_led_preset)
        layout.addWidget(row(self.led_presets, button("Run sequence", "fa5s.play", self.run_led, "primary")))
        layout.addWidget(row(button("Read LED state", "fa5s.lightbulb", lambda: self.control_command(api.led(0, 0, 0, 0, 0))),
                             button("Both off", "fa5s.power-off", lambda: self.control_command(api.led(0x0C, 0, 0, 0, 0)))))
        section(layout, "PICC polling")
        self.picc_bits = []
        picc_grid = QGridLayout()
        picc_labels = ["ISO 14443 Type A", "ISO 14443 Type B", "Topaz", "FeliCa 212K",
                       "FeliCa 424K", "250 ms interval (off: 500 ms)", "Auto ATS generation", "Auto PICC polling"]
        for index, text in enumerate(picc_labels):
            control = QCheckBox(text)
            control.setChecked(True)
            control.setToolTip(f"PICC parameter bit {index}")
            self.picc_bits.append(control)
            picc_grid.addWidget(control, index // 2, index % 2)
        layout.addLayout(picc_grid)
        layout.addWidget(row(button("Read parameter", "fa5s.download", lambda: self.command(api.PICC, self.show_picc)),
                             button("Apply parameter", "fa5s.check", self.set_picc)))
        section(layout, "RF & timing")
        self.timeout_mode = combo(["Finite timeout", "00: No timeout check", "FF: Wait indefinitely"])
        self.timeout_units = spin(1, 254, 1, " x 5 seconds")
        self.timeout_mode.currentIndexChanged.connect(lambda index: self.timeout_units.setEnabled(index == 0))
        timing_form = form(layout)
        timing_form.addRow("Chip response timeout", row(self.timeout_mode, self.timeout_units))
        self.detection_buzzer = QCheckBox("Buzzer on card detection")
        self.detection_buzzer.setChecked(True)
        layout.addWidget(row(button("Set timeout", "fa5s.stopwatch", self.set_timeout), self.detection_buzzer,
                             button("Apply buzzer", "fa5s.volume-up", self.set_detection_buzzer)))
        layout.addWidget(row(button("RF antenna on", "fa5s.broadcast-tower", lambda: self.antenna(True)),
                             button("RF antenna off", "fa5s.power-off", lambda: self.antenna(False), "danger")))
        self.controls_result = output(110)
        layout.addWidget(self.controls_result)

    def build_other_tags(self):
        layout = self.page("Other tags", "ISO 14443-4 / ISO 18092")
        tabs = QTabWidget()
        layout.addWidget(tabs)
        desfire_page = QWidget()
        desfire_layout = QVBoxLayout(desfire_page)
        self.desfire_native = combo(["ISO 7816 wrapped", "Native"])
        self.desfire_instruction = line("60")
        self.desfire_payload = line()
        self.desfire_chain = QCheckBox("Continue additional frames (maximum 32)")
        desfire_form = form(desfire_layout)
        desfire_form.addRow("Command mode", self.desfire_native)
        desfire_form.addRow("Instruction (hex)", self.desfire_instruction)
        desfire_form.addRow("Payload (hex)", self.desfire_payload)
        desfire_layout.addWidget(self.desfire_chain)
        desfire_layout.addWidget(row(button("Get version", "fa5s.info-circle", self.desfire_version, "primary"),
                                    button("Auth challenge", "fa5s.key", self.desfire_challenge),
                                    button("Send command", "fa5s.paper-plane", self.send_desfire, "danger")))
        self.desfire_result = output(210)
        desfire_layout.addWidget(self.desfire_result)
        tabs.addTab(desfire_page, "DESFire")
        felica_page = QWidget()
        felica_layout = QVBoxLayout(felica_page)
        self.felica_id = line("", "Empty = read current IDm")
        self.felica_service = line("0109")
        self.felica_block = spin(0, 65535)
        self.felica_pseudo = QCheckBox("PN532 direct-transmit envelope")
        felica_form = form(felica_layout)
        felica_form.addRow("IDm (8 bytes, hex)", self.felica_id)
        felica_form.addRow("Service code (hex)", self.felica_service)
        felica_form.addRow("Block (decimal)", self.felica_block)
        felica_layout.addWidget(self.felica_pseudo)
        felica_layout.addWidget(button("Read without encryption", "fa5s.download", self.read_felica, "primary"))
        self.felica_result = output(210)
        felica_layout.addWidget(self.felica_result)
        tabs.addTab(felica_page, "FeliCa")
        topaz_page = QWidget()
        topaz_layout = QVBoxLayout(topaz_page)
        self.topaz_address = spin(value=8)
        self.topaz_value = line("00")
        self.topaz_pseudo = QCheckBox("PN532 direct-transmit envelope")
        self.topaz_protected = QCheckBox("Allow writes outside user bytes 08..67 hex")
        topaz_form = form(topaz_layout)
        topaz_form.addRow("Byte address (decimal)", self.topaz_address)
        topaz_form.addRow("Byte value (hex)", self.topaz_value)
        topaz_layout.addWidget(self.topaz_pseudo)
        topaz_layout.addWidget(self.topaz_protected)
        topaz_layout.addWidget(row(button("Read byte", "fa5s.download", lambda: self.topaz_operation("read"), "primary"),
                                  button("Read all", "fa5s.th", lambda: self.topaz_operation("all")),
                                  button("Write byte", "fa5s.pen", lambda: self.topaz_operation("write"), "danger")))
        self.topaz_result = output(210)
        topaz_layout.addWidget(self.topaz_result)
        tabs.addTab(topaz_page, "Topaz / Jewel")
        layout.addStretch()

    def build_console(self):
        layout = self.page("APDU console", "ISO 7816 / pseudo-APDU / PN532 / native frames")
        self.console_preset = combo(["Read UID", "Read ATS", "Get Challenge", "Firmware", "RF status", "Custom"])
        self.console_preset.currentIndexChanged.connect(self.fill_console_preset)
        self.console_route = combo(["Transmit APDU", "CCID escape (3500)", "Wrap PN532 payload"])
        self.console_kind = combo([kind.value for kind in api.ResponseKind])
        self.console_redact = QCheckBox("Redact command bytes in activity log")
        console_form = form(layout)
        console_form.addRow("Preset", self.console_preset)
        console_form.addRow("Transport", self.console_route)
        console_form.addRow("Response format", self.console_kind)
        self.console_input = QPlainTextEdit("FF CA 00 00 00")
        self.console_input.setFont(QFont("Consolas", 12))
        self.console_input.setMinimumHeight(125)
        self.console_input.setPlaceholderText("Hex bytes")
        layout.addWidget(self.console_input)
        layout.addWidget(row(self.console_redact, button("Send", "fa5s.paper-plane", self.send_console, "primary")))
        section(layout, "Response")
        self.console_output = output(250)
        layout.addWidget(self.console_output)
        layout.addStretch()

    def build_activity(self):
        layout = self.page("Activity log", "Session-only / last 2,000 exchanges")
        self.log_search = QLineEdit()
        self.log_search.setPlaceholderText("Filter by command, status, or bytes")
        self.log_search.textChanged.connect(self.filter_log)
        self.follow_log = QCheckBox("Follow latest")
        self.follow_log.setChecked(True)
        layout.addWidget(row(self.log_search, self.follow_log,
                             button("Export", "fa5s.file-export", self.export_log),
                             button("Clear", "fa5s.trash-alt", self.clear_log)))
        self.log_table = QTableWidget(0, 6)
        self.log_table.setHorizontalHeaderLabels(["Time", "Command", "Route", "ms", "Status", "Response"])
        self.log_table.setAlternatingRowColors(True)
        self.log_table.setMinimumHeight(340)
        self.log_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.log_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.log_table.verticalHeader().hide()
        self.log_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        for index, width in enumerate((105, 170, 80, 65, 70)):
            self.log_table.setColumnWidth(index, width)
        self.log_table.itemSelectionChanged.connect(self.show_log_detail)
        layout.addWidget(self.log_table)
        self.log_detail = output(140)
        layout.addWidget(self.log_detail)

    def safe(self, operation):
        try:
            operation()
        except Exception as error:
            self.show_error(str(error))

    def show_error(self, message):
        self.notice.setText(message)
        self.notice.show()
        self.statusBar().showMessage("Operation failed")

    def service_error(self, message):
        if message:
            self.show_error(message)

    def submit(self, operation, options, callback=None):
        if self.busy or self.closing:
            return
        self.callback = callback
        self.busy = True
        self.worker.cancel_event.clear()
        self.notice.hide()
        for index in range(self.pages.count()):
            page = self.pages.widget(index)
            page.setEnabled(page is self.manual_view)
        for control in (self.source, self.readers, self.mode, self.connect_button, self.refresh_button):
            control.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress.setRange(0, 0)
        self.statusBar().showMessage("Working...")
        self.request.emit(operation, options)

    def operation_finished(self, payload):
        callback, self.callback = self.callback, None
        self.end_busy()
        self.statusBar().showMessage("Completed", 5000)
        if callback:
            self.safe(lambda: callback(payload["result"]))
        if isinstance(payload["result"], dict) and payload["result"].get("ok") is False:
            self.show_error(payload["result"]["message"])

    def operation_failed(self, message):
        self.callback = None
        self.end_busy()
        self.show_error(message)

    def end_busy(self):
        self.busy = False
        for index in range(self.pages.count()):
            self.pages.widget(index).setEnabled(True)
        self.source.setEnabled(True)
        self.refresh_button.setEnabled(True)
        self.connect_button.setEnabled(True)
        self.readers.setEnabled(not self.state["connected"])
        self.mode.setEnabled(not self.state["connected"])
        self.cancel_button.setEnabled(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(100)

    def cancel_operation(self):
        self.worker.cancel_event.set()
        self.statusBar().showMessage("Cancellation requested. Waiting for the in-flight command.")

    def update_state(self, state):
        previous = self.state
        self.state = state
        selected = self.readers.currentText()
        names = list(state["readers"])
        current_names = [self.readers.itemText(index) for index in range(self.readers.count())]
        if current_names != names:
            self.readers.clear()
            self.readers.addItems(names)
            if selected in names:
                self.readers.setCurrentText(selected)
        connected = state["connected"]
        self.connect_button.setText("Disconnect" if connected else "Connect")
        if not self.busy:
            self.readers.setEnabled(not connected)
            self.mode.setEnabled(not connected)
        demo = self.source.currentIndex() == 1
        self.source_badge.setText("DEMO / SIMULATED DATA\nNo hardware access" if demo else "LOCAL PC/SC\nACS API v2.04")
        if connected:
            self.connection_status.setText(("DEMO  |  " if demo else "LIVE  |  ") + ("Reader direct connection" if state["direct"] else "Card connected / T=1"))
        elif names:
            present = any(item["present"] for item in state["readers"].values())
            self.connection_status.setText("Card detected / not connected" if present else "Reader available / no card")
        else:
            self.connection_status.setText("No PC/SC reader found")
        if state["generation"] != previous.get("generation") or state.get("atr") != previous.get("atr"):
            self.uid.setText("No UID read")
            self.ats_label.setText("-")
            self.atr_label.setText(api.hex_text(state["atr"]) or "-")
            self.card_type.setText(api.identify_atr(state["atr"]) if state["atr"] else "No active card")
            self.protected_write.setChecked(False)
            self.topaz_protected.setChecked(False)
            detected = api.identify_atr(state["atr"])
            if detected in api.PROFILES:
                self.profile.setCurrentText(detected)
            if self.dump["rows"]:
                self.dump_label.setText("Previous capture / not live | " + self.dump["profile"])

    def toggle_connection(self):
        if self.state["connected"]:
            self.submit("disconnect", {})
        elif self.readers.currentText():
            self.submit("connect", {"name": self.readers.currentText(), "direct": self.mode.currentIndex() == 1})
        else:
            self.show_error("No reader available. Connect an ACR122U or select Demo.")

    def change_source(self, *_):
        demo = self.source.currentIndex() == 1
        self.demo_panel.setVisible(demo)
        self.demo_present.blockSignals(True)
        self.demo_present.setChecked(True)
        self.demo_present.blockSignals(False)
        self.submit("source", {"demo": demo, "profile": self.demo_profile.currentText()})

    def command(self, command, callback=None, escape=False):
        def display(result):
            if not result["ok"]:
                self.show_error(result["message"])
            if callback:
                callback(result)
        self.submit("command", {"command": command, "escape": escape}, display)

    def confirm(self, title, detail):
        if not self.state["connected"]:
            self.show_error("Connect and inspect the current card before sending this command.")
            return None
        generation = self.state["generation"]
        source = "DEMO ONLY" if self.source.currentIndex() else self.state.get("name", "Hardware")
        dialog = QMessageBox(QMessageBox.Icon.Warning, title,
                             f"{source}\n\n{detail}\n\nAn operation already sent cannot be undone.",
                             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, self)
        dialog.setDefaultButton(QMessageBox.StandardButton.Cancel)
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        return generation if dialog.exec() == QMessageBox.StandardButton.Yes else None

    def show_uid(self, result):
        if result["ok"]:
            self.uid.setText(api.hex_text(result["data"]))

    def show_ats(self, result):
        self.ats_label.setText(api.hex_text(result["data"]) if result["ok"] else result["message"])

    def show_overview(self, result):
        self.overview_output.setPlainText(pretty(result))

    def get_rf_status(self):
        def display(result):
            self.overview_output.setPlainText(pretty(api.rf_status(result["data"]) if result["ok"] else result))
        self.command(api.RF_STATUS, display)

    def key_options(self):
        needs_key = self.auto_auth.isChecked() and api.PROFILES[self.profile.currentText()][1] == 16
        return {"key": api.hex_bytes(self.key.text(), 6) if needs_key else b"", "slot": self.key_slot.currentIndex(),
                "key_type": 0x60 + self.key_type.currentIndex(), "legacy": self.legacy_auth.isChecked(),
                "auto_auth": self.auto_auth.isChecked(), "profile": self.profile.currentText()}

    def update_memory_limits(self):
        count, size = api.PROFILES[self.profile.currentText()]
        for control in (self.start_address, self.end_address, self.write_address):
            control.setMaximum(count - 1)
        self.write_data.setPlaceholderText(f"Exactly {size} bytes in hexadecimal")
        for control in (self.key, self.key_slot, self.key_type, self.auto_auth, self.legacy_auth):
            control.setEnabled(size == 16)

    def update_value_profile(self, *_):
        self.value_profile_label.setText(self.profile.currentText() + " | Authentication: Memory panel")

    def load_key(self):
        self.safe(lambda: self.command(api.load_key(api.hex_bytes(self.key.text(), 6), self.key_slot.currentIndex()),
                                      lambda result: self.memory_result.setPlainText(pretty(result))))

    def authenticate(self):
        self.safe(lambda: self.command(api.authenticate(self.start_address.value(), 0x60 + self.key_type.currentIndex(),
                                                       self.key_slot.currentIndex(), self.legacy_auth.isChecked()),
                                      lambda result: self.memory_result.setPlainText(pretty(result))))

    def read_memory(self, all_blocks=False):
        def run():
            options = self.key_options()
            options.update(start=0 if all_blocks else self.start_address.value(),
                           end=api.PROFILES[options["profile"]][0] - 1 if all_blocks else self.end_address.value(),
                           ndef_delay=self.ndef_delay.isChecked())
            self.dump = {"profile": options["profile"], "atr": api.hex_text(self.state.get("atr", b"")), "rows": []}
            self.memory_table.setRowCount(0)
            self.dump_label.setText("Reading / partial capture")
            self.submit("read_memory", options, self.memory_read_finished)
        self.safe(run)

    def append_memory_row(self, record):
        index = self.memory_table.rowCount()
        self.memory_table.insertRow(index)
        address, data = record["address"], api.hex_bytes(record["data"])
        size = api.PROFILES[self.dump["profile"]][1]
        region = "System" if (size == 4 and address < 4) or address == 0 else "Data"
        if size == 16:
            region = f"S{api.sector_of(address)} / " + ("Trailer" if api.is_trailer(address) else region)
        values = [f"{address:03d} / {address:02X}", region, api.hex_text(data),
                  "".join(chr(item) if 32 <= item < 127 else "." for item in data)]
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setFont(QFont("Consolas", 10))
            item.setToolTip(value)
            self.memory_table.setItem(index, column, item)

    def update_progress(self, progress):
        self.progress.setRange(0, progress["total"])
        self.progress.setValue(progress["done"])
        if "row" in progress:
            self.dump["rows"].append(progress["row"])
            self.append_memory_row(progress["row"])
            self.dump_label.setText(f"Partial capture: {progress['done']} / {progress['total']} addresses")

    def memory_read_finished(self, result):
        self.dump = result
        self.dump_label.setText(f"Captured {len(result['rows'])} addresses | {result['profile']}")

    def select_memory_row(self):
        index = self.memory_table.currentRow()
        if 0 <= index < len(self.dump["rows"]):
            record = self.dump["rows"][index]
            self.write_address.setValue(record["address"])
            self.write_data.setText(record["data"])

    def write_memory(self):
        def run():
            options = self.key_options()
            size = api.validate_address(options["profile"], self.write_address.value(), True, self.protected_write.isChecked())
            data = api.hex_bytes(self.write_data.text(), size)
            generation = self.confirm("Confirm memory write", f"Overwrite address {self.write_address.value()} ({self.write_address.value():02X} hex) on {options['profile']}?\nData: {api.hex_text(data)}\nProtected override: {self.protected_write.isChecked()}")
            if generation is not None:
                options.update(address=self.write_address.value(), data=data,
                               allow_protected=self.protected_write.isChecked(), expected_generation=generation)
                self.submit("write_memory", options, lambda result: self.memory_result.setPlainText(pretty(result)))
        self.safe(run)

    def import_dump(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import memory dump", "", "Memory JSON (*.json)")
        if not path:
            return
        def load():
            if Path(path).stat().st_size > 1024 * 1024:
                raise ValueError("Memory dump is too large (maximum 1 MiB).")
            self.dump = parse_dump(Path(path).read_text(encoding="utf-8"))
            self.profile.setCurrentText(self.dump["profile"])
            self.memory_table.setRowCount(0)
            for record in self.dump["rows"]:
                self.append_memory_row(record)
            self.dump_label.setText("Imported / offline capture | " + self.dump["profile"])
        self.safe(load)

    def export_dump(self):
        if not self.dump["rows"]:
            self.show_error("No memory rows to export.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export memory", "memory.json", "Memory JSON (*.json)")
        if path:
            self.safe(lambda: Path(path).write_text(pretty(self.dump), encoding="utf-8"))

    def inspect_ndef(self):
        self.safe(lambda: self.memory_result.setPlainText("\n\n".join(decode_ndef(self.dump))))

    def value_operation(self, operation):
        def run():
            options = self.key_options()
            options.update(operation=operation, address=self.value_address.value(),
                           value=self.value_amount.value(), target=self.value_target.value())
            if operation != "read":
                generation = self.confirm("Confirm value operation", f"{operation.title()} at block {options['address']}?\nValue / delta: {options['value']}\nRestore target: {options['target']}\nStore replaces the block with value-block data.")
                if generation is None:
                    return
                options["expected_generation"] = generation
            self.submit("value", options, lambda result: self.value_result.setPlainText(pretty(result)))
        self.safe(run)

    def fill_led_preset(self, *_):
        data = api.hex_bytes(api.LED_EXAMPLES[self.led_presets.currentText()])
        for index, control in enumerate(self.led_bits):
            control.setChecked(bool(data[3] & (1 << index)))
        self.first_duration.setValue(data[5])
        self.second_duration.setValue(data[6])
        self.repetitions.setValue(data[7])
        self.buzzer_link.setCurrentIndex(data[8])

    def control_command(self, command):
        self.command(command, lambda result: self.controls_result.setPlainText(pretty(result)))

    def run_led(self):
        duration = (self.first_duration.value() + self.second_duration.value()) * self.repetitions.value() / 10
        if duration > 10 and self.confirm("Long peripheral sequence", f"This sequence may occupy the reader for {duration:.1f} seconds.") is None:
            return
        control = sum(1 << index for index, check in enumerate(self.led_bits) if check.isChecked())
        self.control_command(api.led(control, self.first_duration.value(), self.second_duration.value(), self.repetitions.value(), self.buzzer_link.currentIndex()))

    def show_picc(self, result):
        if result["ok"]:
            for index, control in enumerate(self.picc_bits):
                control.setChecked(bool(result["data"][0] & (1 << index)))
        self.controls_result.setPlainText(pretty(result))

    def set_picc(self):
        parameter = sum(1 << index for index, check in enumerate(self.picc_bits) if check.isChecked())
        generation = self.confirm("Change polling parameter", f"Set PICC parameter to {parameter:02X}?\nDisabling polling or tag types can stop detection. The manual recommends disabling Auto ATS for MIFARE detection.")
        if generation is not None:
            self.submit("command", {"command": api.reader_command("Set PICC parameter", 0x51, parameter, api.ResponseKind.PICC),
                                    "expected_generation": generation}, self.show_picc)

    def set_timeout(self):
        parameter = [self.timeout_units.value(), 0, 255][self.timeout_mode.currentIndex()]
        if parameter in (0, 255) and self.confirm("Unbounded device timeout", "This setting can leave a PC/SC call blocked until the reader responds or is unplugged.") is None:
            return
        self.control_command(api.reader_command("Set timeout", 0x41, parameter))

    def set_detection_buzzer(self):
        self.control_command(api.reader_command("Detection buzzer", 0x52, 255 if self.detection_buzzer.isChecked() else 0))

    def antenna(self, enabled):
        if not enabled and self.confirm("Disable RF antenna", "The current card connection may be lost. Use Direct / Escape mode to turn RF back on.") is None:
            return
        self.control_command(api.direct(bytes([0xD4, 0x32, 1, int(enabled)])))

    def desfire_version(self):
        self.submit("desfire", {"native": bool(self.desfire_native.currentIndex()), "instruction": 0x60, "chain": True},
                    lambda result: self.desfire_result.setPlainText(pretty(result)))

    def desfire_challenge(self):
        self.submit("desfire", {"native": bool(self.desfire_native.currentIndex()), "instruction": 0x0A, "payload": b"\x00"},
                    lambda result: self.desfire_result.setPlainText("Initial authentication challenge only; mutual authentication is not complete.\n\n" + pretty(result)))

    def send_desfire(self):
        def run():
            instruction = api.hex_bytes(self.desfire_instruction.text(), 1)[0]
            payload = api.hex_bytes(self.desfire_payload.text())
            generation = self.confirm("Send custom DESFire command", "A custom command may change card data, keys or access rights. Use the card's command specification.")
            if generation is not None:
                self.submit("desfire", {"native": bool(self.desfire_native.currentIndex()), "instruction": instruction,
                                        "payload": payload, "chain": self.desfire_chain.isChecked(), "expected_generation": generation},
                            lambda result: self.desfire_result.setPlainText(pretty(result)))
        self.safe(run)

    def read_felica(self):
        def run():
            identifier = api.hex_bytes(self.felica_id.text(), 8) if self.felica_id.text().strip() else None
            service = int.from_bytes(api.hex_bytes(self.felica_service.text(), 2), "big")
            self.submit("felica", {"identifier": identifier, "service": service, "block": self.felica_block.value(), "pseudo": self.felica_pseudo.isChecked()},
                        lambda result: self.felica_result.setPlainText(pretty(result)))
        self.safe(run)

    def topaz_operation(self, operation):
        def run():
            options = {"operation": operation, "address": self.topaz_address.value(),
                       "value": api.hex_bytes(self.topaz_value.text(), 1)[0], "pseudo": self.topaz_pseudo.isChecked(),
                       "allow_protected": self.topaz_protected.isChecked()}
            if operation == "write":
                generation = self.confirm("Confirm Topaz byte write", f"Write {options['value']:02X} to byte address {options['address']}?\nLock/OTP and reserved bytes may be irreversible.")
                if generation is None:
                    return
                options["expected_generation"] = generation
            self.submit("topaz", options, lambda result: self.topaz_result.setPlainText(pretty(result)))
        self.safe(run)

    def fill_console_preset(self, index):
        commands = [api.get_data(), api.get_data(True), api.GET_CHALLENGE, api.FIRMWARE, api.RF_STATUS]
        if index < len(commands):
            command = commands[index]
            self.console_input.setPlainText(api.hex_text(command.data))
            self.console_kind.setCurrentText(command.kind.value)
            self.console_route.setCurrentIndex(0)

    def send_console(self):
        def run():
            data = api.hex_bytes(self.console_input.toPlainText())
            if not 1 <= len(data) <= 261:
                raise ValueError("Console frame must contain 1..261 bytes; extended APDUs are not supported.")
            kind = api.ResponseKind(self.console_kind.currentText())
            route = self.console_route.currentIndex()
            command = api.direct(data) if route == 2 else api.Command("Console", data, kind,
                       reader_only=data[:2] == b"\xFF\x00", sensitive=self.console_redact.isChecked())
            if route == 2 and self.console_redact.isChecked():
                command = api.Command(command.name, command.data, command.kind, True, True)
            generation = self.confirm("Send raw command", f"Transmit {len(command.data)} bytes using {self.console_route.currentText()}?\nRaw commands bypass memory-area guards and may change card data or reader settings.")
            if generation is not None:
                self.submit("command", {"command": command, "escape": route == 1, "expected_generation": generation},
                            lambda result: self.console_output.setPlainText(pretty(result)))
        self.safe(run)

    def add_activity(self, entry):
        self.activity_entries.append(entry)
        if len(self.activity_entries) > 2000:
            self.activity_entries.pop(0)
            self.log_table.removeRow(0)
        index = self.log_table.rowCount()
        self.log_table.insertRow(index)
        values = [entry["time"].split("T")[-1][:12], entry["command"], entry["route"], str(entry["ms"]),
                  "OK" if entry["ok"] else "ERROR", entry["rx"] or entry["message"]]
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setToolTip(value)
            self.log_table.setItem(index, column, item)
        self.filter_log()
        if self.follow_log.isChecked():
            self.log_table.scrollToBottom()

    def filter_log(self, *_):
        query = self.log_search.text().lower()
        for index, entry in enumerate(self.activity_entries):
            self.log_table.setRowHidden(index, bool(query) and query not in pretty(entry).lower())

    def show_log_detail(self):
        index = self.log_table.currentRow()
        if 0 <= index < len(self.activity_entries):
            self.log_detail.setPlainText(pretty(self.activity_entries[index]))

    def clear_log(self):
        self.activity_entries.clear()
        self.log_table.setRowCount(0)
        self.log_detail.clear()

    def export_log(self):
        path, selected = QFileDialog.getSaveFileName(self, "Export activity log", "activity.json", "JSON (*.json);;CSV (*.csv)")
        if not path:
            return
        def save():
            if selected.startswith("CSV"):
                buffer = io.StringIO(newline="")
                writer = csv.DictWriter(buffer, fieldnames=["time", "command", "route", "tx", "rx", "ok", "message", "ms"])
                writer.writeheader()
                writer.writerows(self.activity_entries)
                content = buffer.getvalue()
            else:
                content = pretty(self.activity_entries)
            Path(path).write_text(content, encoding="utf-8")
        self.safe(save)

    def open_manual(self):
        location = Path(sys.executable).parent if getattr(sys, "frozen", False) else ROOT
        path = location / "API-ACR122U-2.04.pdf"
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        else:
            QDesktopServices.openUrl(QUrl("https://www.acs.com.hk/download-manual/419/API-ACR122U-2.04.pdf"))

    def closeEvent(self, event: QCloseEvent):
        if self.busy:
            self.show_error("Wait for the current operation before closing. Cancel stops between commands; unplug the reader if its driver is blocked.")
            event.ignore()
            return
        if self.started and self.thread.isRunning():
            self.closing = True
            self.setEnabled(False)
            self.shutdown.emit()
            event.ignore()
        else:
            event.accept()

    def thread_finished(self):
        if self.closing:
            self.started = False
            self.close()