"""Qt worker: all PC/SC handles and operations stay on one thread."""

import threading

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from .device import Session
from .simulator import DemoTransport


class ReaderWorker(QObject):
    state = Signal(object)
    activity = Signal(object)
    progress = Signal(object)
    finished = Signal(object)
    failed = Signal(str)
    service_error = Signal(str)
    stopped = Signal()

    def __init__(self, demo=False):
        super().__init__()
        self.demo = demo
        self.session = None
        self.timer = None
        self.cancel_event = threading.Event()

    @Slot()
    def start(self):
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.poll)
        self.replace_session(self.demo)
        self.timer.start()

    def replace_session(self, demo, profile="MIFARE Classic 1K"):
        if self.session:
            self.session.transport.close()
        self.session = Session(DemoTransport(profile) if demo else None, self.activity.emit)
        self.session.cancel = self.cancel_event
        self.demo = demo
        self.poll()

    @Slot()
    def poll(self):
        if self.session is None:
            return
        try:
            self.state.emit(self.session.snapshot())
            self.service_error.emit("")
        except Exception as error:
            self.session.disconnect()
            self.session.transport.close()
            self.state.emit({"readers": {}, "connected": False, "name": "", "atr": b"",
                             "generation": self.session.generation, "direct": False})
            self.service_error.emit(str(error))

    @Slot(str, object)
    def execute(self, operation, options):
        try:
            if operation == "source":
                self.replace_session(options["demo"], options["profile"])
                result = {"source": "Demo" if self.demo else "Hardware"}
            elif operation == "demo_card":
                if not self.demo:
                    raise ValueError("Only available in demo mode.")
                self.session.transport.present = options["present"]
                self.session.transport.counter += 1
                result = {"present": options["present"]}
            else:
                result = self.session.execute(operation, options, self.progress.emit)
            self.finished.emit({"operation": operation, "result": result})
        except Exception as error:
            self.failed.emit(str(error))
        finally:
            self.poll()

    @Slot()
    def stop(self):
        if self.timer:
            self.timer.stop()
        if self.session:
            self.session.transport.close()
        self.stopped.emit()