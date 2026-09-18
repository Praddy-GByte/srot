# -*- coding: utf-8 -*-
"""Plugin entry point: menu, toolbar, dock, and wiring to the agent."""

import os

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QFileDialog, QMessageBox
from qgis.core import QgsMessageLog

from .core import settings
from .core.compat import (
    DOCK_RIGHT,
    MSG_CRITICAL,
    MSG_INFO,
    MSG_SUCCESS,
    QAction,
    standard_button,
)

LOG_TAG = "Srot"
MENU = "&Srot"


def log(message, level=None):
    QgsMessageLog.logMessage(str(message), LOG_TAG, level or MSG_INFO)


class SrotPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.dock = None
        self.runner = None

    # -- QGIS lifecycle -------------------------------------------------

    def initGui(self):  # noqa: N802
        icon_path = os.path.join(self.plugin_dir, "icon.png")
        icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()

        self.open_action = QAction(icon, "Srot", self.iface.mainWindow())
        self.open_action.setToolTip(
            "Verified Indian government geodata, inside QGIS"
        )
        self.open_action.triggered.connect(self.show_dock)
        self.iface.addToolBarIcon(self.open_action)
        self.iface.addPluginToWebMenu(MENU, self.open_action)
        self.actions.append(self.open_action)

        self.settings_action = QAction("Settings...", self.iface.mainWindow())
        self.settings_action.triggered.connect(self.show_settings)
        self.iface.addPluginToWebMenu(MENU, self.settings_action)
        self.actions.append(self.settings_action)

        self.catalogue_action = QAction(
            "Show the India data catalogue", self.iface.mainWindow()
        )
        self.catalogue_action.triggered.connect(self.show_catalogue)
        self.iface.addPluginToWebMenu(MENU, self.catalogue_action)
        self.actions.append(self.catalogue_action)

    def unload(self):
        for action in self.actions:
            self.iface.removePluginWebMenu(MENU, action)
            self.iface.removeToolBarIcon(action)
        self.actions = []

        if self.runner is not None:
            try:
                self.runner.cancel()
            except Exception:
                pass
            self.runner = None

        if self.dock is not None:
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None

    # -- UI -------------------------------------------------------------

    def show_dock(self):
        if self.dock is None:
            self._build()
        self.dock.show()
        self.dock.raise_()
        if settings.model_name():
            self.dock.input.setFocus()
        else:
            self.dock.browser.search.setFocus()

    def _build(self):
        from .agent.loop import AgentRunner
        from .ui.dock import SrotDock

        self.dock = SrotDock(self.iface.mainWindow())
        self.iface.addDockWidget(DOCK_RIGHT, self.dock)

        self.runner = AgentRunner(self.iface, self.dock)
        # The Browse tab adds layers through the same context the agent uses,
        # so browsed layers share the journal and the exported script.
        self.dock.set_context_provider(lambda: self.runner.context)

        self.dock.send_requested.connect(self.runner.send)
        self.dock.stop_requested.connect(self.runner.cancel)
        self.dock.settings_requested.connect(self.show_settings)
        self.dock.save_script_requested.connect(self.save_script)
        self.dock.clear_requested.connect(self.runner.reset)

        self.runner.message.connect(self.dock.add_message)
        self.runner.tool_started.connect(self.dock.add_tool_start)
        self.runner.tool_finished.connect(self.dock.add_tool_result)
        self.runner.status.connect(self.dock.set_status)
        self.runner.busy_changed.connect(self.dock.set_busy)
        self.runner.failed.connect(self._on_failed)
        self.runner.confirmation_requested.connect(self._confirm)

    def show_settings(self):
        from .ui import settings_dialog

        settings_dialog.show(self.iface.mainWindow())
        if self.dock is not None:
            self.dock.set_status(
                "Using {0} / {1}.".format(
                    settings.provider_spec()["label"], settings.model_name() or "no model set"
                )
            )

    def show_catalogue(self):
        from .india import catalog

        lines = [
            "Srot - India data catalogue",
            "=" * 44,
            "",
            "ISRO Bhuvan WMS hosts:",
        ]
        for host in catalog.BHUVAN_WMS_HOSTS:
            lines.append(
                "  {0:<10} {1}  [{2}]".format(
                    host["id"], host["url"], "verified" if host["verified"] else "unverified"
                )
            )
        lines += ["", "Bhuvan layers in the catalogue: {0}".format(catalog.bhuvan_layer_count())]
        lines += ["States and union territories covered: {0}".format(
            len(catalog.bhuvan_states_covered()))]
        lines += ["  " + ", ".join(catalog.bhuvan_states_covered())]
        lines += ["", "Curated entries:"]
        for entry in catalog.BHUVAN_LAYERS:
            lines.append("  {0:<34} {1}".format(entry["name"], entry["title"]))
        lines += ["", "State-wise families (expanded per state):"]
        for family in catalog.bhuvan_layers.FAMILIES:
            lines.append("  {0:<34} {1} states".format(
                family["pattern"], len(family["codes"])))

        lines += ["", "data.gov.in resources ({0}):".format(len(catalog.DATAGOV_RESOURCES))]
        for entry in catalog.DATAGOV_RESOURCES:
            lines.append("  {0}".format(entry["title"]))
            lines.append("      {0}".format(entry["id"]))

        lines += ["", "Boundary datasets:"]
        for key, entry in catalog.BOUNDARY_SOURCES.items():
            lines.append("  {0:<20} {1}".format(key, entry["title"]))

        lines += ["", "OpenStreetMap presets:", "  " + ", ".join(sorted(catalog.OSM_PRESETS))]

        lines += ["", "Documented but unverified from the build machine:"]
        for key, entry in catalog.UNVERIFIED_SOURCES.items():
            lines.append("  {0:<14} {1}".format(key, entry["title"]))

        text = "\n".join(lines)
        log(text)
        self.iface.messageBar().pushMessage(
            "Srot",
            "The India data catalogue was written to the Log Messages panel "
            "(View > Panels > Log Messages, tab 'Srot').",
            level=MSG_INFO,
            duration=8,
        )

    # -- callbacks ------------------------------------------------------

    def _on_failed(self, text):
        self.dock.add_error(text)
        log(text, MSG_CRITICAL)

    def _confirm(self, tool_name, arguments):
        detail = "\n".join("  {0} = {1}".format(k, v) for k, v in sorted(arguments.items()))
        answer = QMessageBox.question(
            self.iface.mainWindow(),
            "Srot",
            "The agent wants to run:\n\n  {0}\n{1}\n\nAllow it?".format(tool_name, detail),
        )
        self.runner.answer_confirmation(answer == standard_button(QMessageBox, "Yes"))

    def save_script(self):
        if self.runner is None or self.runner.journal.is_empty():
            QMessageBox.information(
                self.iface.mainWindow(),
                "Srot",
                "Nothing to save yet - the agent has not done anything in this session.",
            )
            return

        path, _ = QFileDialog.getSaveFileName(
            self.iface.mainWindow(),
            "Save the session as a PyQGIS script",
            os.path.join(os.path.expanduser("~"), "srot_session.py"),
            "Python (*.py)",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(self.runner.journal.to_script())
        except OSError as exc:
            QMessageBox.warning(
                self.iface.mainWindow(), "Srot", "Could not write the file: {0}".format(exc)
            )
            return

        self.iface.messageBar().pushMessage(
            "Srot",
            "Saved {0} steps to {1}".format(self.runner.journal.step_count(), path),
            level=MSG_SUCCESS,
            duration=8,
        )
