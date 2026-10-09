"""Qt polling adapter for the existing queue-based Pipeline workers."""
# SPDX-License-Identifier: MPL-2.0
import queue
import threading

from PySide6.QtCore import QObject, QTimer, Signal


class Jobs(QObject):
    progress = Signal(dict)
    finished = Signal(str, object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.events = queue.Queue()
        self.worker = None
        self.kind = ""
        self.terminal = None
        self.cancel_event = threading.Event()
        self.timer = QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self.poll)

    @property
    def busy(self):
        return self.worker is not None

    def start(self, kind, function=None, worker=None):
        if self.busy:
            raise RuntimeError("Another task is running")
        self.kind, self.terminal = kind, None
        self.cancel_event.clear()
        if worker is None:
            def execute():
                try:
                    result = function()
                    self.events.put({"type": "done", "result": result})
                except Exception as error:
                    self.events.put({"type": "error", "error": str(error)})
            worker = threading.Thread(target=execute, name=f"GameAssetKeyer-{kind}", daemon=True)
        self.worker = worker
        worker.start()
        self.timer.start()

    def cancel(self):
        self.cancel_event.set()
        if self.worker is not None and hasattr(self.worker, "cancel"):
            self.worker.cancel()

    def poll(self):
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            if event["type"] in ("done", "error", "cancelled"):
                self.terminal = event
            else:
                self.progress.emit(event)
        if self.terminal is None or self.worker.is_alive():
            return
        event, kind = self.terminal, self.kind
        self.worker = self.terminal = None
        self.timer.stop()
        error = event.get("error", "")
        if event["type"] == "cancelled":
            error = "Cancelled"
        self.finished.emit(kind, event.get("result"), error)
