# -*- coding: utf-8 -*-
"""Settings dialog.

The API key is written to ``QgsAuthManager`` (encrypted) rather than
``QgsSettings`` (plaintext).  If the auth database is unavailable or the user
cancels the master-password prompt, we say so and fall back to the environment
variable rather than silently writing the key somewhere insecure.
"""

from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from ..core import settings
from ..core.compat import exec_dialog, standard_button


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Srot settings")
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)

        # --- model ---------------------------------------------------------
        model_box = QGroupBox("Language model", self)
        model_form = QFormLayout(model_box)

        self.provider = QComboBox(self)
        for key, spec in settings.PROVIDERS.items():
            self.provider.addItem(spec["label"], key)
        index = self.provider.findData(settings.provider_id())
        self.provider.setCurrentIndex(max(0, index))
        self.provider.currentIndexChanged.connect(self._provider_changed)
        model_form.addRow("Provider", self.provider)

        self.model = QLineEdit(settings.get("model"), self)
        model_form.addRow("Model", self.model)

        self.base_url = QLineEdit(settings.get("base_url"), self)
        self.base_url.setPlaceholderText("leave empty to use the provider default")
        model_form.addRow("Base URL", self.base_url)

        key_row = QHBoxLayout()
        self.api_key = QLineEdit(self)
        self.api_key.setEchoMode(getattr(QLineEdit, "EchoMode", QLineEdit).Password)
        self.api_key.setPlaceholderText(
            "stored encrypted in the QGIS Authentication Manager"
        )
        if settings.get("auth_config_id"):
            self.api_key.setPlaceholderText("a key is stored - type to replace it")
        key_row.addWidget(self.api_key)
        clear_key = QPushButton("Forget", self)
        clear_key.clicked.connect(self._forget_key)
        key_row.addWidget(clear_key)
        model_form.addRow("API key", key_row)

        self.key_hint = QLabel(self)
        self.key_hint.setWordWrap(True)
        model_form.addRow("", self.key_hint)

        test_row = QHBoxLayout()
        self.test_button = QPushButton("Test connection", self)
        self.test_button.clicked.connect(self._test)
        test_row.addWidget(self.test_button)
        self.test_result = QLabel("", self)
        self.test_result.setWordWrap(True)
        test_row.addWidget(self.test_result, 1)
        model_form.addRow("", test_row)

        layout.addWidget(model_box)

        # --- india ---------------------------------------------------------
        india_box = QGroupBox("Indian data sources", self)
        india_form = QFormLayout(india_box)

        self.datagov_key = QLineEdit(settings.get("datagov_api_key"), self)
        self.datagov_key.setPlaceholderText(
            "optional - without one, the shared sample key is used"
        )
        india_form.addRow("data.gov.in key", self.datagov_key)

        note = QLabel(
            "data.gov.in's shared sample key is rate limited after a handful of "
            "calls. A personal key is free: register at data.gov.in, then "
            "My Account &rarr; APIs.",
            self,
        )
        note.setWordWrap(True)
        india_form.addRow("", note)
        layout.addWidget(india_box)

        # --- behaviour -----------------------------------------------------
        behaviour_box = QGroupBox("Behaviour", self)
        behaviour_form = QFormLayout(behaviour_box)

        self.max_steps = QSpinBox(self)
        self.max_steps.setRange(1, 60)
        self.max_steps.setValue(settings.get_int("max_steps", 12))
        behaviour_form.addRow("Max steps per request", self.max_steps)

        self.confirm_writes = QCheckBox(
            "Ask before writing files or removing layers", self
        )
        self.confirm_writes.setChecked(settings.get_bool("confirm_writes"))
        behaviour_form.addRow("", self.confirm_writes)

        safety = QLabel(
            "The agent can only use its declared tools. It cannot write or run "
            "Python, and every Processing call is checked against the algorithm "
            "registry before it executes.",
            self,
        )
        safety.setWordWrap(True)
        behaviour_form.addRow("", safety)
        layout.addWidget(behaviour_box)

        buttons = QDialogButtonBox(
            standard_button(QDialogButtonBox, "Ok")
            | standard_button(QDialogButtonBox, "Cancel"),
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._provider_changed()

    # -----------------------------------------------------------------

    def _provider_changed(self):
        key = self.provider.currentData()
        spec = settings.PROVIDERS.get(key, {})
        if not self.model.text().strip():
            self.model.setPlaceholderText(spec.get("default_model", ""))
        self.base_url.setPlaceholderText(
            spec.get("default_base") or "e.g. https://your-endpoint.example.com"
        )
        if spec.get("needs_key"):
            env = spec.get("env")
            self.key_hint.setText(
                "Required. Stored encrypted. You can also set the {0} environment "
                "variable instead, which avoids the master-password prompt.".format(env)
            )
            self.api_key.setEnabled(True)
        else:
            self.key_hint.setText(
                "Ollama runs on your own machine and needs no key. Start it with "
                "<code>ollama serve</code> and pull a tool-capable model, for "
                "example <code>ollama pull qwen3:8b</code>. Nothing leaves your computer."
            )
            self.api_key.setEnabled(False)

    def _forget_key(self):
        settings.remove_api_key(settings.get("auth_config_id"))
        settings.set_value("auth_config_id", "")
        self.api_key.clear()
        self.api_key.setPlaceholderText("no key stored")
        QMessageBox.information(self, "Srot", "The stored API key was removed.")

    def _test(self):
        self.save()
        self.test_button.setEnabled(False)
        self.test_result.setText("Testing...")

        from qgis.core import QgsApplication as App

        from ..agent import providers
        from ..agent.loop import _CallableTask  # noqa: WPS437 - internal by design

        task = _CallableTask("Srot: connection test", providers.test_connection)

        def done():
            # The dialog may already be gone -- it is modal, and the user can
            # close it while the test is still in flight. Touching a deleted
            # widget from a Qt slot raises inside the event loop, so check.
            try:
                from qgis.PyQt import sip

                if sip.isdeleted(self):
                    return
            except Exception:
                pass
            try:
                self.test_button.setEnabled(True)
                if task.error is not None:
                    self.test_result.setText("Failed: {0}".format(task.error))
                else:
                    self.test_result.setText(
                        "Connected. Model replied: {0!r}".format(task.value)
                    )
            except RuntimeError:  # the C++ widget was destroyed
                return
            self._task = None

        task.taskCompleted.connect(done)
        task.taskTerminated.connect(done)
        self._task = task
        App.taskManager().addTask(task)

    def save(self):
        settings.set_value("provider", self.provider.currentData())
        settings.set_value("model", self.model.text().strip())
        settings.set_value("base_url", self.base_url.text().strip())
        settings.set_value("max_steps", str(self.max_steps.value()))
        settings.set_value(
            "confirm_writes", "true" if self.confirm_writes.isChecked() else "false"
        )
        settings.set_value("datagov_api_key", self.datagov_key.text().strip())

        typed = self.api_key.text().strip()
        if typed:
            try:
                old = settings.get("auth_config_id")
                config_id = settings.store_api_key(
                    "Srot - {0}".format(self.provider.currentText()),
                    self.base_url.text().strip() or None,
                    "api_key",
                    typed,
                )
                settings.set_value("auth_config_id", config_id)
                settings.remove_api_key(old)
                self.api_key.clear()
                self.api_key.setPlaceholderText("a key is stored - type to replace it")
            except Exception as exc:
                QMessageBox.warning(
                    self,
                    "Srot",
                    "The API key could not be stored securely: {0}\n\n"
                    "It was NOT saved. Set the environment variable instead, or "
                    "set a QGIS master password under Settings > Options > "
                    "Authentication.".format(exc),
                )

    def accept(self):
        self.save()
        super().accept()


def show(parent=None):
    dialog = SettingsDialog(parent)
    return exec_dialog(dialog)
