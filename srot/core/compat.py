# -*- coding: utf-8 -*-
"""Qt5 / Qt6 and QGIS 3 / QGIS 4 compatibility helpers.

PyQt6 moved every enum into a scoped class (``Qt.CursorShape.WaitCursor``
instead of ``Qt.WaitCursor``).  The scoped spelling also works on recent PyQt5
builds, but not on every 3.28-era one, so we resolve each enum once, at import,
and fall back to the unscoped name.

Nothing here imports anything outside ``qgis.PyQt`` / ``qgis.core``.
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.core import (
    Qgis,
    QgsBlockingNetworkRequest,
    QgsGraduatedSymbolRenderer,
    QgsLayoutExporter,
    QgsTask,
    QgsUnitTypes,
    QgsVectorFileWriter,
)


def _enum(owner, scope, name, default=None):
    """Return ``owner.scope.name`` if it exists, else ``owner.name``."""
    holder = getattr(owner, scope, None)
    if holder is not None:
        value = getattr(holder, name, None)
        if value is not None:
            return value
    value = getattr(owner, name, None)
    if value is not None:
        return value
    return default


# --- Qt --------------------------------------------------------------------
ALIGN_LEFT = _enum(Qt, "AlignmentFlag", "AlignLeft")
ALIGN_RIGHT = _enum(Qt, "AlignmentFlag", "AlignRight")
ALIGN_TOP = _enum(Qt, "AlignmentFlag", "AlignTop")
ALIGN_VCENTER = _enum(Qt, "AlignmentFlag", "AlignVCenter")
ORIENT_HORIZONTAL = _enum(Qt, "Orientation", "Horizontal")
ORIENT_VERTICAL = _enum(Qt, "Orientation", "Vertical")
DOCK_RIGHT = _enum(Qt, "DockWidgetArea", "RightDockWidgetArea")
ITEM_NO_FLAGS = _enum(Qt, "ItemFlag", "NoItemFlags")
TEXT_SELECTABLE = _enum(Qt, "TextInteractionFlag", "TextSelectableByMouse")
KEY_RETURN = _enum(Qt, "Key", "Key_Return")
KEY_ENTER = _enum(Qt, "Key", "Key_Enter")
MOD_CONTROL = _enum(Qt, "KeyboardModifier", "ControlModifier")
TEXT_SELECTABLE = _enum(Qt, "TextInteractionFlag", "TextBrowserInteraction")
CURSOR_WAIT = _enum(Qt, "CursorShape", "WaitCursor")
SCROLLBAR_AS_NEEDED = _enum(Qt, "ScrollBarPolicy", "ScrollBarAsNeeded")

# --- QNetworkRequest -------------------------------------------------------
HEADER_CONTENT_TYPE = _enum(QNetworkRequest, "KnownHeaders", "ContentTypeHeader")
ATTR_HTTP_STATUS = _enum(
    QNetworkRequest, "Attribute", "HttpStatusCodeAttribute"
)
ATTR_REDIRECT_POLICY = _enum(
    QNetworkRequest, "Attribute", "RedirectPolicyAttribute"
)
REDIRECT_POLICY_SAME_ORIGIN = _enum(
    QNetworkRequest, "RedirectPolicy", "NoLessSafeRedirectPolicy"
)

# --- QGIS ------------------------------------------------------------------
TASK_CAN_CANCEL = _enum(QgsTask, "Flag", "CanCancel")
LAYOUT_MM = _enum(QgsUnitTypes, "LayoutUnit", "LayoutMillimeters")
EXPORT_SUCCESS = _enum(QgsLayoutExporter, "ExportResult", "Success")
WRITER_NO_ERROR = _enum(QgsVectorFileWriter, "WriterError", "NoError")
GRADUATED_QUANTILE = _enum(QgsGraduatedSymbolRenderer, "Mode", "Quantile")
REQUEST_NO_ERROR = _enum(QgsBlockingNetworkRequest, "ErrorCode", "NoError")
MSG_INFO = _enum(Qgis, "MessageLevel", "Info")
MSG_WARNING = _enum(Qgis, "MessageLevel", "Warning")
MSG_CRITICAL = _enum(Qgis, "MessageLevel", "Critical")
MSG_SUCCESS = _enum(Qgis, "MessageLevel", "Success", MSG_INFO)


# --- classes that moved between QtWidgets and QtGui in Qt6 -----------------
try:  # Qt6
    from qgis.PyQt.QtGui import QAction, QShortcut  # noqa: F401
except ImportError:  # Qt5
    from qgis.PyQt.QtWidgets import QAction, QShortcut  # noqa: F401


def standard_button(cls, name):
    """``QMessageBox.Yes`` on Qt5, ``QMessageBox.StandardButton.Yes`` on Qt6."""
    holder = getattr(cls, "StandardButton", None)
    if holder is not None and hasattr(holder, name):
        return getattr(holder, name)
    return getattr(cls, name)


def exec_dialog(dialog):
    """Run a modal dialog. ``exec()`` is present on PyQt5 and PyQt6 alike."""
    return dialog.exec()
