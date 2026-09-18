# -*- coding: utf-8 -*-
"""Browse the India catalogue and add a layer, with no model involved.

Most people who want a Bhuvan layer want exactly that and nothing else. This
panel gives them the whole catalogue -- every Bhuvan layer, every boundary set,
every data.gov.in resource and every OpenStreetMap preset -- as a searchable
list with an Add button, and asks for no API key, no provider and no model.

It calls the same tools the agent calls, so a layer added here behaves
identically, carries the same provenance, and appears in the same exported
script.
"""

from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from qgis.core import QgsApplication

from ..agent import tools
from ..core.tasks import CallableTask
from ..india import catalog

#: Which catalogue families the filter offers, and how each entry is turned
#: into a tool call.
SOURCES = (
    ("all", "Everything"),
    ("bhuvan", "ISRO Bhuvan"),
    ("boundaries", "Boundaries"),
    ("datagov", "data.gov.in"),
    ("osm", "OpenStreetMap"),
)

#: OpenStreetMap presets need somewhere to look, so the panel asks for a place
#: rather than silently downloading the whole country.
DEFAULT_PLACE = "Bengaluru"


def entries(source="all", query=""):
    """Every catalogue entry matching the filter, as plain dictionaries.

    Kept free of Qt so the selection logic can be tested without a GUI.
    """
    found = []

    if source in ("all", "bhuvan"):
        for layer in catalog.all_bhuvan_layers():
            found.append({
                "kind": "bhuvan",
                "id": layer["name"],
                "title": layer.get("title") or layer["name"],
                "detail": "ISRO Bhuvan WMS",
                "state": layer.get("state") or "",
                "theme": " ".join(
                    [layer.get("theme") or ""] + list(layer.get("keywords") or [])
                ),
            })

    if source in ("all", "boundaries"):
        for key, entry in catalog.BOUNDARY_SOURCES.items():
            found.append({
                "kind": "boundary",
                "id": key,
                "title": entry["title"],
                "detail": ("Survey of India derived" if entry.get("official_boundary")
                           else "Community or Census derived")
                          + (", can be filtered to one state"
                             if entry.get("state_field") else ""),
                "state": "",
                "theme": "admin",
            })

    if source in ("all", "datagov"):
        for entry in catalog.DATAGOV_RESOURCES:
            found.append({
                "kind": "datagov",
                "id": entry["id"],
                "title": entry["title"],
                "detail": "data.gov.in resource",
                "state": "",
                "theme": " ".join(
                    [entry.get("theme") or ""] + list(entry.get("keywords") or [])
                ),
            })

    if source in ("all", "osm"):
        for preset in sorted(catalog.OSM_PRESETS):
            found.append({
                "kind": "osm",
                "id": preset,
                "title": preset.replace("_", " ").capitalize(),
                "detail": "OpenStreetMap, needs a place",
                "state": "",
                "theme": "osm",
            })

    words = [w for w in str(query).lower().split() if w]
    if not words:
        return found

    def matches(entry):
        haystack = " ".join(
            str(entry.get(field) or "")
            for field in ("id", "title", "detail", "state", "theme")
        ).lower()
        return all(word in haystack for word in words)

    return [entry for entry in found if matches(entry)]


#: Entry kinds that take a free-text area, and what to call it. Boundaries are
#: national files filtered on load, so "Kerala districts" is the district set
#: plus a state; OpenStreetMap is fetched for one place at a time.
AREA_FIELD = {
    "boundary": ("State (optional)", "state"),
    "osm": ("Place", "place"),
}


def tool_call(entry, area=""):
    """Turn a catalogue entry into the tool name and arguments that add it.

    ``area`` is the contents of the area box: a state for a boundary set, a
    place for an OpenStreetMap preset, and ignored for everything else.
    """
    kind = entry["kind"]
    area = (area or "").strip()
    if kind == "bhuvan":
        return "add_bhuvan_layer", {"layer": entry["id"]}
    if kind == "boundary":
        arguments = {"level": entry["id"]}
        if area:
            arguments["state"] = area
        return "add_boundary", arguments
    if kind == "datagov":
        return "add_datagov_layer", {"resource_id": entry["id"], "limit": 500}
    if kind == "osm":
        return "add_osm_features", {
            "feature": entry["id"],
            "place": area or DEFAULT_PLACE,
        }
    raise ValueError("Unknown catalogue entry kind: {0!r}".format(kind))


class CatalogueBrowser(QWidget):
    """Search the catalogue and add a layer directly."""

    #: (text) - something worth showing in the panel's status line
    status = pyqtSignal(str)
    #: (name) - a layer was added
    layer_added = pyqtSignal(str)

    def __init__(self, context_provider, parent=None):
        super().__init__(parent)
        self._context_provider = context_provider
        self._entries = []
        self._task = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        intro = QLabel(
            "Search {0} layers and datasets from ISRO Bhuvan, data.gov.in, "
            "the boundary sets and OpenStreetMap. No account or model "
            "needed.".format(catalog.bhuvan_layer_count() + len(catalog.DATAGOV_RESOURCES)
                              + len(catalog.BOUNDARY_SOURCES) + len(catalog.OSM_PRESETS)),
            self,
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        filter_row = QHBoxLayout()
        self.search = QLineEdit(self)
        self.search.setPlaceholderText("Search: kerala land use, rainfall, districts...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        filter_row.addWidget(self.search, 1)

        self.source = QComboBox(self)
        for key, label in SOURCES:
            self.source.addItem(label, key)
        self.source.currentIndexChanged.connect(self.refresh)
        filter_row.addWidget(self.source)
        layout.addLayout(filter_row)

        self.results = QListWidget(self)
        self.results.setMinimumHeight(220)
        self.results.currentRowChanged.connect(self._selection_changed)
        self.results.itemDoubleClicked.connect(lambda _item: self.add_selected())
        layout.addWidget(self.results, 1)

        self.detail = QLabel("", self)
        self.detail.setWordWrap(True)
        layout.addWidget(self.detail)

        place_row = QHBoxLayout()
        self.place_label = QLabel("Area", self)
        place_row.addWidget(self.place_label)
        self.place = QLineEdit(DEFAULT_PLACE, self)
        self.place.setToolTip(
            "A state narrows a boundary set; a place is where OpenStreetMap "
            "features are fetched from."
        )
        place_row.addWidget(self.place, 1)
        layout.addLayout(place_row)

        button_row = QHBoxLayout()
        self.add_button = QPushButton("Add to map", self)
        self.add_button.setEnabled(False)
        self.add_button.clicked.connect(self.add_selected)
        button_row.addWidget(self.add_button)
        self.progress = QProgressBar(self)
        self.progress.setRange(0, 0)
        self.progress.setMaximumWidth(90)
        self.progress.setVisible(False)
        button_row.addWidget(self.progress)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        self.refresh()

    # -- listing --------------------------------------------------------

    def refresh(self):
        source = self.source.currentData() or "all"
        self._entries = entries(source, self.search.text())
        self.results.clear()
        for entry in self._entries[:500]:
            item = QListWidgetItem("{0}  --  {1}".format(entry["title"], entry["id"]))
            self.results.addItem(item)
        if len(self._entries) > 500:
            self.status.emit(
                "{0} matches; showing the first 500. Narrow the search to see "
                "the rest.".format(len(self._entries))
            )
        else:
            self.status.emit("{0} matches.".format(len(self._entries)))
        self._selection_changed(self.results.currentRow())

    def _selection_changed(self, row):
        entry = self.current_entry()
        self.add_button.setEnabled(entry is not None)
        field = AREA_FIELD.get(entry["kind"]) if entry is not None else None
        self.place.setEnabled(field is not None)
        self.place_label.setEnabled(field is not None)
        self.place_label.setText(field[0] if field else "Area")
        if entry is None:
            self.detail.setText("")
            return
        self.detail.setText("{0} - {1}".format(entry["detail"], entry["id"]))

    def current_entry(self):
        row = self.results.currentRow()
        if row < 0 or row >= len(self._entries):
            return None
        return self._entries[row]

    # -- adding ---------------------------------------------------------

    def add_selected(self):
        entry = self.current_entry()
        if entry is None or self._task is not None:
            return

        try:
            name, arguments = tool_call(entry, self.place.text().strip())
            tool = tools.get(name)
        except Exception as exc:
            self.status.emit(str(exc))
            return

        self._set_busy(True)
        self.status.emit("Fetching {0}...".format(entry["title"]))

        def fetch():
            if tool.fetch is None:
                return None
            return tool.fetch(arguments)

        task = CallableTask("Add {0}".format(entry["title"]), fetch)

        def completed():
            self._task = None
            self._set_busy(False)
            self._apply(tool, arguments, task.value, entry)

        def terminated():
            self._task = None
            self._set_busy(False)
            self.status.emit(
                "Could not fetch {0}: {1}".format(
                    entry["title"], task.error or "the source did not respond"
                )
            )

        task.taskCompleted.connect(completed)
        task.taskTerminated.connect(terminated)
        # Hold a reference for the life of the task, or QGIS may collect the
        # wrapper mid-run and take the process down with it.
        self._task = task
        QgsApplication.taskManager().addTask(task)

    def _apply(self, tool, arguments, payload, entry):
        context = self._context_provider()
        try:
            result = tool.apply(arguments, context, payload)
        except Exception as exc:
            self.status.emit("Could not add {0}: {1}".format(entry["title"], exc))
            return

        added = result.get("added") or entry["title"]
        note = result.get("note")
        count = result.get("feature_count")
        message = "Added {0}".format(added)
        if count is not None:
            message += " ({0} features)".format(count)
        if result.get("substitute_layer"):
            message += ", plus {0}".format(result["substitute_layer"])
        self.status.emit(message + ("  " + note if note else ""))
        self.layer_added.emit(added)

    def _set_busy(self, busy):
        self.progress.setVisible(busy)
        self.add_button.setEnabled(not busy and self.current_entry() is not None)
        self.search.setEnabled(not busy)
        self.source.setEnabled(not busy)
