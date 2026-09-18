# -*- coding: utf-8 -*-
"""The chat dock."""

import html
import json
import os

from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtGui import QKeySequence, QTextCursor
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..core import settings
from ..core.compat import QShortcut
from .browser import CatalogueBrowser

EXAMPLES = [
    "Try an example...",
    "Map the live air quality monitoring stations in Delhi",
    "Load Maharashtra district boundaries and shade them by name",
    "Show Bhuvan satellite imagery over Bengaluru",
    "Get every hospital in Pune from OpenStreetMap",
    "Add the river basins of India and style them by basin",
    "Load Kerala district boundaries, then buffer them by 5 km",
    "Show the districts of Telangana using Census 2011 boundaries",
    "Make an A3 landscape print layout titled 'Rajasthan Districts'",
    "Which data.gov.in datasets do you have for rainfall?",
]


class SrotDock(QDockWidget):
    """Chat panel: transcript, input box, and the session controls."""

    send_requested = pyqtSignal(str)
    stop_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    save_script_requested = pyqtSignal()
    clear_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Srot", parent)
        self.setObjectName("SrotDock")

        self._context_provider = None

        self.tabs = QTabWidget(self)

        # --- browse: the catalogue, with no model involved ------------------
        # Deliberately first, and selected by default until a model is set up.
        # Someone who wants one Bhuvan layer should not have to configure a
        # provider to get it.
        self.browser = CatalogueBrowser(self._resolve_context, self.tabs)
        self.browser.status.connect(self.set_status)
        browse_page = QWidget(self.tabs)
        browse_layout = QVBoxLayout(browse_page)
        browse_layout.setContentsMargins(6, 6, 6, 6)
        browse_layout.addWidget(self.browser)
        self.tabs.addTab(browse_page, "Browse")

        container = QWidget(self.tabs)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # --- transcript ----------------------------------------------------
        self.transcript = QTextBrowser(container)
        self.transcript.setOpenExternalLinks(True)
        self.transcript.setMinimumHeight(240)
        layout.addWidget(self.transcript, 1)

        # --- status --------------------------------------------------------
        status_row = QHBoxLayout()
        self.status = QLabel("Ready.", container)
        self.status.setWordWrap(True)
        status_row.addWidget(self.status, 1)
        self.progress = QProgressBar(container)
        self.progress.setRange(0, 0)
        self.progress.setMaximumWidth(90)
        self.progress.setVisible(False)
        status_row.addWidget(self.progress)
        layout.addLayout(status_row)

        # --- examples ------------------------------------------------------
        self.examples = QComboBox(container)
        self.examples.addItems(EXAMPLES)
        self.examples.currentIndexChanged.connect(self._example_picked)
        layout.addWidget(self.examples)

        # --- input ---------------------------------------------------------
        self.input = QPlainTextEdit(container)
        self.input.setPlaceholderText(
            "Describe the map or the analysis you want.\nCtrl+Enter to send."
        )
        self.input.setMaximumHeight(90)
        layout.addWidget(self.input)

        # --- buttons -------------------------------------------------------
        buttons = QHBoxLayout()
        self.send_button = QPushButton("Send", container)
        self.send_button.setDefault(True)
        self.send_button.clicked.connect(self._send)
        buttons.addWidget(self.send_button)

        self.stop_button = QPushButton("Stop", container)
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_requested)
        buttons.addWidget(self.stop_button)

        buttons.addStretch(1)

        self.script_button = QPushButton("Save script", container)
        self.script_button.setToolTip(
            "Write everything this session did as a runnable PyQGIS script."
        )
        self.script_button.clicked.connect(self.save_script_requested)
        buttons.addWidget(self.script_button)

        clear_button = QPushButton("Clear", container)
        clear_button.clicked.connect(self._clear)
        buttons.addWidget(clear_button)

        settings_button = QPushButton("Settings", container)
        settings_button.clicked.connect(self.settings_requested)
        buttons.addWidget(settings_button)

        layout.addLayout(buttons)

        self.tabs.addTab(container, "Ask")
        self.setWidget(self.tabs)
        self.show_best_tab()
        self._greet()

        shortcut = QShortcut(QKeySequence("Ctrl+Return"), self.input)
        shortcut.activated.connect(self._send)
        shortcut2 = QShortcut(QKeySequence("Ctrl+Enter"), self.input)
        shortcut2.activated.connect(self._send)

    # -- tabs -----------------------------------------------------------

    def set_context_provider(self, provider):
        """Give the Browse tab somewhere to add layers.

        Called once the runner exists; the browser only resolves it at the
        moment a layer is added, so binding it late is safe.
        """
        self._context_provider = provider

    def _resolve_context(self):
        if self._context_provider is None:
            raise RuntimeError(
                "The panel is still starting up. Try again in a moment."
            )
        return self._context_provider()

    def show_best_tab(self):
        """Open on Browse until a model is configured, then on Ask."""
        self.tabs.setCurrentIndex(1 if settings.model_name() else 0)

    # -- input ----------------------------------------------------------

    def _example_picked(self, index):
        if index > 0:
            self.input.setPlainText(EXAMPLES[index])
            self.examples.setCurrentIndex(0)
            self.input.setFocus()

    def _send(self):
        text = self.input.toPlainText().strip()
        if not text:
            return
        self.input.clear()
        self.send_requested.emit(text)

    def _clear(self):
        self.transcript.clear()
        self._greet()
        self.clear_requested.emit()

    # -- transcript -----------------------------------------------------

    def _greet(self):
        provider = settings.provider_spec()["label"]
        self._html(
            "<div style='margin:6px 0'>"
            "<b>Srot</b> &mdash; verified Indian government geodata, "
            "inside QGIS.<br>"
            "The <b>Browse</b> tab lists the whole catalogue and needs no model at "
            "all. Here you can ask for several things at once and put any "
            "Processing algorithm to work on the result.<br>"
            "<span style='color:#777'>Provider: {0}. No generated code is ever run &mdash; "
            "every action is a declared, validated tool.</span>"
            "</div><hr>".format(html.escape(provider))
        )

    def add_message(self, role, text):
        if role == "user":
            self._html(
                "<div style='margin:8px 0'><b style='color:#0b5394'>You</b><br>{0}</div>".format(
                    _format(text)
                )
            )
        elif role == "assistant":
            self._html(
                "<div style='margin:8px 0'><b style='color:#38761d'>Agent</b><br>{0}</div>".format(
                    _format(text)
                )
            )
        else:
            self._html(
                "<div style='margin:4px 0;color:#8a6d00'>&#9432; {0}</div>".format(
                    _format(text)
                )
            )

    def add_tool_start(self, name, arguments):
        detail = ", ".join(
            "{0}={1}".format(k, _short(v)) for k, v in sorted(arguments.items())
        )
        self._html(
            "<div style='margin:2px 0 2px 12px;color:#555;font-family:monospace;"
            "font-size:11px'>&#9654; {0}({1})</div>".format(
                html.escape(name), html.escape(detail)
            )
        )

    def add_tool_result(self, name, content, ok):
        colour = "#666" if ok else "#a61b1b"
        summary = _summarise(content, ok)
        self._html(
            "<div style='margin:0 0 6px 24px;color:{0};font-family:monospace;"
            "font-size:11px'>{1}</div>".format(colour, html.escape(summary))
        )

    def add_error(self, text):
        self._html(
            "<div style='margin:8px 0;padding:6px;background:#fdecea;color:#a61b1b'>"
            "<b>Problem</b><br>{0}</div>".format(_format(text))
        )

    def _html(self, fragment):
        self.transcript.append(fragment)
        move = getattr(QTextCursor, "MoveOperation", QTextCursor)
        self.transcript.moveCursor(move.End)

    # -- state ----------------------------------------------------------

    def set_busy(self, busy):
        self.send_button.setEnabled(not busy)
        self.stop_button.setEnabled(busy)
        self.input.setReadOnly(busy)
        self.progress.setVisible(busy)

    def set_status(self, text):
        self.status.setText(text)


def _format(text):
    escaped = html.escape(str(text))
    return escaped.replace("\n", "<br>")


def _short(value):
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    text = " ".join(str(text).split())
    return text if len(text) <= 60 else text[:57] + "..."


def _summarise(content, ok):
    if not ok:
        return "✗ " + " ".join(str(content).split())[:300]
    try:
        data = json.loads(content)
    except (TypeError, ValueError):
        return "✓ " + " ".join(str(content).split())[:200]

    if isinstance(data, dict):
        if "added" in data:
            bits = ["added {0!r}".format(data["added"])]
            if data.get("feature_count") is not None:
                bits.append("{0} features".format(data["feature_count"]))
            return "✓ " + ", ".join(bits)
        if "results" in data:
            return "✓ {0} catalogue matches".format(len(data["results"]))
        if "algorithms" in data:
            return "✓ {0} algorithms".format(len(data["algorithms"]))
        if "layers" in data and isinstance(data["layers"], list):
            return "✓ {0} layers in project".format(len(data["layers"]))
        if "written" in data:
            return "✓ wrote {0}".format(os.path.basename(str(data["written"])))
        if "layers_added" in data:
            names = [l["name"] for l in data["layers_added"]]
            return "✓ " + (", ".join(names) if names else "ran, no layer added")
    return "✓ " + " ".join(str(content).split())[:200]
