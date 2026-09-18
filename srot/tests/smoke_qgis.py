# -*- coding: utf-8 -*-
"""Smoke test against a REAL QGIS installation.

The offline suite (``tests/run.py``) proves the logic against a stub.  This one
proves the plugin actually works with PyQGIS: real layer classes, the real
Processing registry, the real renderers, the real layout and export APIs, and
the real authentication manager.

It needs no network -- every check uses memory layers and local files -- so it
is safe to run in CI.

Run it with the Python that QGIS was built for::

    QT_QPA_PLATFORM=offscreen python3.12 -m srot.tests.smoke_qgis

Exit code 0 means the plugin loads and its tools work in this QGIS build.
"""

import os
import sys
import tempfile
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# QGIS ships its bundled plugins (including `processing`) outside site-packages.
for candidate in (
    "/usr/share/qgis/python",
    "/usr/share/qgis/python/plugins",
    "/Applications/QGIS.app/Contents/Resources/python",
    "/Applications/QGIS.app/Contents/Resources/python/plugins",
):
    if os.path.isdir(candidate) and candidate not in sys.path:
        sys.path.append(candidate)

from qgis.PyQt.QtXml import QDomDocument  # noqa: E402
from qgis.core import (  # noqa: E402
    Qgis,
    QgsApplication,
    QgsLayerMetadata,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsVectorLayer,
)

RESULTS = []

#: Widgets built during the tests. A headless harness runs no event loop, so
#: deleteLater() would queue a deletion that never happens and then be freed a
#: second time during interpreter teardown. Holding a reference instead lets
#: the process own them until it exits.
WIDGETS = []


def keep(widget):
    """Keep a widget alive for the rest of the run, and return it."""
    WIDGETS.append(widget)
    return widget


def check(name, condition, detail=""):
    RESULTS.append((name, bool(condition), str(detail)[:400]))
    return bool(condition)


def section(name, function):
    print("  .. {0}".format(name), flush=True)
    try:
        function()
    except Exception as exc:
        RESULTS.append(
            (name + " (raised)", False, "{0}: {1}".format(type(exc).__name__, exc))
        )
        traceback.print_exc()


# ---------------------------------------------------------------------------


def start_qgis():
    QgsApplication.setPrefixPath(os.environ.get("QGIS_PREFIX_PATH", "/usr"), True)
    app = QgsApplication([b"srot"], True)  # GUI=True so widgets can be built
    app.initQgis()

    from qgis.analysis import QgsNativeAlgorithms

    QgsApplication.processingRegistry().addProvider(QgsNativeAlgorithms())
    try:
        from processing.core.Processing import Processing

        Processing.initialize()
    except Exception as exc:  # pragma: no cover
        print("WARNING: Processing could not be initialised:", exc)
    return app


def make_layer(name="Districts", count=6):
    layer = QgsVectorLayer(
        "Polygon?crs=EPSG:4326&field=district:string&field=st_nm:string&field=value:double",
        name,
        "memory",
    )
    provider = layer.dataProvider()
    features = []
    names = ["Pune", "Nagpur", "Nashik", "Thane", "Satara", "Latur"]
    for index in range(count):
        feature = QgsFeature(layer.fields())
        x, y = 73.0 + index * 0.5, 18.0 + index * 0.4
        feature.setGeometry(
            QgsGeometry.fromPolygonXY(
                [[
                    QgsPointXY(x, y),
                    QgsPointXY(x + 0.3, y),
                    QgsPointXY(x + 0.3, y + 0.3),
                    QgsPointXY(x, y + 0.3),
                    QgsPointXY(x, y),
                ]]
            )
        )
        feature.setAttributes([names[index % len(names)], "Maharashtra", float(index * 7 + 3)])
        features.append(feature)
    provider.addFeatures(features)
    layer.updateExtents()
    return layer


# ---------------------------------------------------------------------------


def test_imports():
    # Importing every module IS the test here: these are the imports that fail
    # on a real QGIS if a Qt or PyQGIS name has moved.
    import srot
    from srot import plugin  # noqa: F401,F811
    from srot.agent import loop, prompts, providers, tools  # noqa: F401,F811
    from srot.core import compat, journal, net, settings  # noqa: F401,F811
    from srot.india import catalog, loaders, places  # noqa: F401,F811
    from srot.ui import dock, settings_dialog  # noqa: F401,F811

    check("every plugin module imports under real PyQGIS", True)
    check("version is exposed", srot.__version__ == "0.1.2")
    check(
        "classFactory exists",
        callable(getattr(srot, "classFactory", None)),
    )
    check(
        "compat resolved the Qt enums",
        compat.DOCK_RIGHT is not None and compat.MSG_CRITICAL is not None,
        "dock={0} crit={1}".format(compat.DOCK_RIGHT, compat.MSG_CRITICAL),
    )
    check("compat resolved QAction", compat.QAction is not None)
    check("compat resolved QShortcut", compat.QShortcut is not None)


def test_tool_registry():
    from srot.agent import tools

    check("registry populated", len(tools.REGISTRY) >= 18, len(tools.REGISTRY))
    import json

    json.dumps(tools.schemas())
    check("schemas serialise", True)


def test_processing_against_real_registry():
    from srot.agent import tools
    from srot.core.journal import Journal

    registry = QgsApplication.processingRegistry()
    total = len(registry.algorithms())
    check("real Processing registry is loaded", total > 100, "{0} algorithms".format(total))

    ctx = tools.Context(None, Journal())
    project = QgsProject.instance()
    layer = make_layer()
    project.addMapLayer(layer)

    found = tools.REGISTRY["list_processing_algorithms"].apply({"query": "buffer"}, ctx, None)
    check("algorithm search finds buffer", found["count"] >= 1, found["algorithms"][:2])

    helped = tools.REGISTRY["algorithm_help"].apply({"algorithm_id": "native:buffer"}, ctx, None)
    names = {p["name"] for p in helped["parameters"]}
    check("algorithm_help reads real parameters", {"INPUT", "DISTANCE", "OUTPUT"} <= names, sorted(names))
    optional = {p["name"]: p["optional"] for p in helped["parameters"]}
    check(
        "optional flags resolve on this build",
        optional.get("INPUT") is False and optional.get("SEGMENTS") in (True, False),
        optional,
    )

    # a wrong parameter name must be refused before Processing sees it
    try:
        tools.REGISTRY["run_processing"].apply(
            {"algorithm_id": "native:buffer", "parameters": {"DISTENCE": 1}}, ctx, None
        )
        check("bad parameter refused", False)
    except tools.ToolError as exc:
        check("bad parameter refused", "DISTANCE" in str(exc), str(exc)[:160])

    result = tools.REGISTRY["run_processing"].apply(
        {
            "algorithm_id": "native:buffer",
            "parameters": {"INPUT": "Districts", "DISTANCE": 0.05, "SEGMENTS": 5},
        },
        ctx,
        None,
    )
    check("a real Processing run succeeds", bool(result["layers_added"]), result)
    added = [
        project.mapLayer(entry["id"])
        for entry in result["layers_added"]
        if project.mapLayer(entry["id"])
    ]
    check("the buffered layer is valid and populated",
          added and added[0].isValid() and added[0].featureCount() == 6,
          [(l.name(), l.featureCount()) for l in added])

    centroids = tools.REGISTRY["run_processing"].apply(
        {"algorithm_id": "native:centroids", "parameters": {"INPUT": "Districts"}}, ctx, None
    )
    check("a second algorithm runs", bool(centroids["layers_added"]), centroids)


def test_styling_against_real_renderers():
    from qgis.core import (
        QgsCategorizedSymbolRenderer,
        QgsGraduatedSymbolRenderer,
        QgsSingleSymbolRenderer,
    )

    from srot.agent import tools
    from srot.core.journal import Journal

    ctx = tools.Context(None, Journal())
    project = QgsProject.instance()
    layer = make_layer("Styling target")
    project.addMapLayer(layer)

    tools.REGISTRY["style_layer"].apply(
        {"layer": "Styling target", "mode": "single", "color": "#d62728"}, ctx, None
    )
    check(
        "single symbol renderer applied",
        isinstance(layer.renderer(), QgsSingleSymbolRenderer),
        type(layer.renderer()).__name__,
    )
    check(
        "colour applied",
        layer.renderer().symbol().color().name() == "#d62728",
        layer.renderer().symbol().color().name(),
    )

    tools.REGISTRY["style_layer"].apply(
        {"layer": "Styling target", "mode": "categorized", "field": "district"}, ctx, None
    )
    renderer = layer.renderer()
    check(
        "categorized renderer applied with categories",
        isinstance(renderer, QgsCategorizedSymbolRenderer) and len(renderer.categories()) >= 5,
        "{0} categories".format(len(renderer.categories()) if hasattr(renderer, "categories") else -1),
    )

    # This is the call that was a TypeError before the colour ramp was passed.
    tools.REGISTRY["style_layer"].apply(
        {"layer": "Styling target", "mode": "graduated", "field": "value", "classes": 4},
        ctx,
        None,
    )
    renderer = layer.renderer()
    check(
        "graduated renderer applied with classes",
        isinstance(renderer, QgsGraduatedSymbolRenderer) and len(renderer.ranges()) >= 2,
        "{0} ranges".format(len(renderer.ranges()) if hasattr(renderer, "ranges") else -1),
    )

    # back to single, from a graduated renderer that has no setSymbol
    tools.REGISTRY["style_layer"].apply(
        {"layer": "Styling target", "mode": "single", "color": "darkgreen"}, ctx, None
    )
    check(
        "single styling works after graduated",
        isinstance(layer.renderer(), QgsSingleSymbolRenderer),
        type(layer.renderer()).__name__,
    )


def test_layout_and_export():
    from srot.agent import tools
    from srot.core.journal import Journal

    ctx = tools.Context(None, Journal())
    project = QgsProject.instance()

    created = tools.REGISTRY["create_print_layout"].apply(
        {"title": "Maharashtra Districts", "page_size": "A3", "orientation": "landscape"},
        ctx,
        None,
    )
    layout = project.layoutManager().layoutByName(created["layout"])
    check("layout was created", layout is not None, created)
    if layout is not None:
        page = layout.pageCollection().page(0)
        check(
            "A3 landscape page size applied",
            abs(page.pageSize().width() - 420.0) < 1.0,
            "{0} x {1}".format(page.pageSize().width(), page.pageSize().height()),
        )
        kinds = sorted({type(item).__name__ for item in layout.items()})
        check(
            "layout has map, label, legend and scalebar",
            {"QgsLayoutItemMap", "QgsLayoutItemLabel", "QgsLayoutItemLegend",
             "QgsLayoutItemScaleBar"} <= set(kinds),
            kinds,
        )

    out_dir = tempfile.mkdtemp(prefix="srot_smoke_")

    pdf_path = os.path.join(out_dir, "layout.pdf")
    tools.REGISTRY["export_layout"].apply(
        {"layout": created["layout"], "path": pdf_path}, ctx, None
    )
    check(
        "layout exported to PDF",
        os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 1000,
        "{0} bytes".format(os.path.getsize(pdf_path) if os.path.exists(pdf_path) else 0),
    )

    png_path = os.path.join(out_dir, "layout.png")
    tools.REGISTRY["export_layout"].apply(
        {"layout": created["layout"], "path": png_path, "dpi": 96}, ctx, None
    )
    check("layout exported to PNG", os.path.exists(png_path), png_path)

    layer = make_layer("Export me")
    project.addMapLayer(layer)
    for extension, expected_driver in ((".gpkg", "GPKG"), (".geojson", "GeoJSON")):
        path = os.path.join(out_dir, "out" + extension)
        written = tools.REGISTRY["export_layer"].apply(
            {"layer": "Export me", "path": path}, ctx, None
        )
        check(
            "export_layer wrote {0}".format(extension),
            os.path.exists(path) and written["driver"] == expected_driver,
            written,
        )
        reopened = QgsVectorLayer(path, "check", "ogr")
        check(
            "the written {0} reopens with all features".format(extension),
            reopened.isValid() and reopened.featureCount() == 6,
            "valid={0} n={1}".format(reopened.isValid(), reopened.featureCount()),
        )

    try:
        tools.REGISTRY["export_layer"].apply(
            {"layer": "Export me", "path": os.path.join(out_dir, "nope.xyz")}, ctx, None
        )
        check("unsupported extension refused", False)
    except tools.ToolError as exc:
        check("unsupported extension refused", ".gpkg" in str(exc), str(exc)[:120])


def test_wms_uri_shape():
    from qgis.core import QgsDataSourceUri

    from srot.india import catalog

    uri = QgsDataSourceUri()
    uri.setParam("crs", "EPSG:4326")
    uri.setParam("format", "image/png")
    uri.setParam("layers", "basemap:AP_LULC")
    uri.setParam("styles", "")
    uri.setParam("url", catalog.bhuvan_host_url("vec1"))
    encoded = bytes(uri.encodedUri()).decode("utf-8")
    check("encodedUri decodes to text", "layers=" in encoded, encoded[:120])
    check("the Bhuvan host is encoded into the uri", "nrsc.gov.in" in encoded, encoded[:160])


def test_layer_tools():
    from srot.agent import tools
    from srot.core.journal import Journal

    ctx = tools.Context(None, Journal())
    project = QgsProject.instance()
    layer = make_layer("Info target")
    project.addMapLayer(layer)

    info = tools.REGISTRY["layer_info"].apply(
        {"layer": "Info target", "sample_field": "district"}, ctx, None
    )
    check("layer_info reports the CRS", info["crs"] == "EPSG:4326", info["crs"])
    check("layer_info reports fields", len(info["fields"]) == 3, info["fields"])
    check(
        "layer_info samples distinct values",
        "Pune" in info["unique_values"],
        info.get("unique_values"),
    )

    listed = tools.REGISTRY["list_layers"].apply({}, ctx, None)
    check("list_layers sees the project", listed["count"] >= 1, listed["count"])

    resolved = tools.REGISTRY["resolve_place"].apply({"name": "Bangalore"}, ctx, None)
    check(
        "resolve_place works offline",
        resolved["canonical"] == "Bengaluru" and len(resolved["bbox"]) == 4,
        resolved,
    )

    searched = tools.REGISTRY["search_india_data"].apply({"query": "rainfall district"}, ctx, None)
    check("catalogue search returns hits", bool(searched["results"]), searched["results"][:2])

    removed = tools.REGISTRY["remove_layer"].apply({"layer": "Info target"}, ctx, None)
    check("remove_layer works", removed["removed"] == "Info target", removed)


def test_provenance_against_real_metadata():
    """QgsLayerMetadata is the real target; prove the fields survive a write."""
    from srot.agent import tools
    from srot.core import provenance
    from srot.core.journal import Journal

    project = QgsProject.instance()
    for layer_id in list(project.mapLayers()):
        project.removeMapLayer(layer_id)

    layer = make_layer("Kerala districts")
    project.addMapLayer(layer)
    provenance.describe(
        layer, "census", source_url="https://example.org/districts.geojson"
    )

    metadata = layer.metadata()
    check("real QGIS keeps the licence", bool(metadata.licenses()), metadata.licenses())
    check(
        "real QGIS keeps the citation",
        "Census of India 2011" in (metadata.rights() or [""])[0],
        metadata.rights(),
    )
    check(
        "real QGIS keeps the custodian",
        bool(metadata.contacts()) and metadata.contacts()[0].role == "custodian",
        [c.organization for c in metadata.contacts()],
    )
    check(
        "real QGIS keeps the source link",
        any(link.url.endswith("districts.geojson") for link in metadata.links()),
        [link.url for link in metadata.links()],
    )
    check(
        "the spatial extent is recorded",
        bool(metadata.extent().spatialExtents()),
        len(metadata.extent().spatialExtents()),
    )
    check(
        "the temporal extent records the retrieval",
        bool(metadata.extent().temporalExtents()),
        len(metadata.extent().temporalExtents()),
    )
    check("the CRS is recorded", metadata.crs().authid() == "EPSG:4326",
          metadata.crs().authid())

    # ISO 19115 export is what makes this useful outside QGIS.
    document = QDomDocument("qgis")
    element = document.createElement("resourceMetadata")
    document.appendChild(element)
    check("metadata serialises to XML", metadata.writeMetadataXml(element, document))
    restored = QgsLayerMetadata()
    check("metadata reads back from XML", restored.readMetadataXml(element))
    check(
        "the citation survives the round trip",
        restored.rights() == metadata.rights(),
        restored.rights(),
    )

    second = make_layer("Bengaluru hospitals")
    project.addMapLayer(second)
    provenance.describe(second, "openstreetmap")

    ctx = tools.Context(None, Journal())
    path = os.path.join(tempfile.mkdtemp(), "sources.md")
    result = tools.REGISTRY["export_citations"].apply(
        {"path": path, "style": "markdown"}, ctx, None
    )
    check("export_citations writes a file", os.path.isfile(path), path)
    check("export_citations covers both layers", result["layers"] == 2, result["layers"])
    written = open(path, encoding="utf-8").read()
    check("the file cites OpenStreetMap", "OpenStreetMap" in written, written[:200])
    check("the file cites the Census boundaries", "Census of India" in written,
          written[:400])

    for style in ("plain", "bibtex"):
        other = os.path.join(os.path.dirname(path), "sources." + style)
        tools.REGISTRY["export_citations"].apply(
            {"path": other, "style": style}, ctx, None
        )
        check("export_citations writes {0} style".format(style), os.path.isfile(other),
              other)

    info = tools.REGISTRY["layer_info"].apply({"layer": "Kerala districts"}, ctx, None)
    check("layer_info surfaces provenance", "provenance" in info, sorted(info))

    for layer_id in list(project.mapLayers()):
        project.removeMapLayer(layer_id)


def test_auth_manager():
    from srot.core import settings

    manager = QgsApplication.authManager()
    check("an auth manager exists", manager is not None)
    if manager is None:
        return

    if not manager.masterPasswordIsSet():
        manager.setMasterPassword("srot-smoke-test", True)

    try:
        config_id = settings.store_api_key(
            "Srot smoke test", None, "api_key", "sk-smoke-1234"
        )
    except RuntimeError as exc:
        check("storing a key works or fails loudly", False, str(exc))
        return

    check("store_api_key returns an id", bool(config_id), config_id)
    check(
        "the key round-trips through the encrypted store",
        settings.read_api_key(config_id, "api_key") == "sk-smoke-1234",
    )
    settings.remove_api_key(config_id)
    check(
        "a removed key no longer reads back",
        settings.read_api_key(config_id, "api_key") == "",
    )


def test_journal_script_runs():
    """The exported script must be valid PyQGIS, not just valid Python."""
    from srot.agent import tools
    from srot.core.journal import Journal

    out_dir = tempfile.mkdtemp(prefix="srot_journal_")
    source = os.path.join(out_dir, "source.geojson")

    project = QgsProject.instance()
    layer = make_layer("Journal source")
    project.addMapLayer(layer)

    ctx = tools.Context(None, Journal())
    tools.REGISTRY["export_layer"].apply(
        {"layer": "Journal source", "path": source}, ctx, None
    )
    tools.REGISTRY["run_processing"].apply(
        {
            "algorithm_id": "native:centroids",
            "parameters": {"INPUT": "Journal source"},
        },
        ctx,
        None,
    )

    script = ctx.journal.to_script()
    compile(script, "<journal>", "exec")
    check("the session script compiles", True)
    check("the script imports PyQGIS", "from qgis.core import" in script)
    check("the script records the processing call", "processing.run" in script, script[-400:])
    # Layer ids are generated per session and mean nothing on a re-run, so the
    # script must never refer to one.
    check(
        "the script has no session-specific layer ids",
        "project.mapLayer('" not in script and 'project.mapLayer("' not in script,
        script[-500:],
    )
    check(
        "pre-existing layers are looked up by name",
        "_existing(" in script,
        script[-500:],
    )

    # Execute the generated script for real, in a namespace that mirrors the
    # QGIS Python console.
    namespace = {"__name__": "__journal__"}
    try:
        exec(compile(script, "<journal>", "exec"), namespace)
        check("the exported script executes inside QGIS", True)
    except Exception as exc:
        check("the exported script executes inside QGIS", False, "{0}: {1}".format(type(exc).__name__, exc))

    # A replayed session must reproduce provenance too, or the script rebuilds
    # layers that can no longer say where they came from.
    from srot.core import provenance

    for layer_id in list(project.mapLayers()):
        project.removeMapLayer(layer_id)
    ctx = tools.Context(None, Journal())
    boundary = make_layer("Replay districts")
    project.addMapLayer(boundary)
    tools._record_layer(
        ctx,
        "add_boundary",
        boundary,
        "{var} = _existing('Replay districts')",
        "Boundary layer",
        source="district_current",
        source_url="https://example.org/districts.geojson",
    )
    sources_path = os.path.join(out_dir, "replay_sources.md")
    tools.REGISTRY["export_citations"].apply(
        {"path": sources_path, "style": "markdown"}, ctx, None
    )
    replay = ctx.journal.to_script()
    check("the script records the provenance call", "_describe(" in replay, replay[-500:])

    os.remove(sources_path)
    boundary.setMetadata(provenance.QgsLayerMetadata())
    check("metadata is cleared before the replay",
          provenance.summarise(boundary) is None)
    try:
        exec(compile(replay, "<journal-provenance>", "exec"), {"__name__": "__journal__"})
        check("the provenance script executes inside QGIS", True)
    except Exception as exc:
        check("the provenance script executes inside QGIS", False,
              "{0}: {1}".format(type(exc).__name__, exc))

    restored = provenance.summarise(boundary)
    check("the replay restores the citation",
          restored and "India Maps Data" in restored["citation"], restored)
    check("the replay restores the licence", restored and bool(restored["licence"]),
          restored)
    check("the replay restores the publisher's dataset name",
          restored and restored["source_title"].startswith("India district"),
          restored)
    check("the replay rewrites the source list", os.path.isfile(sources_path))
    if os.path.isfile(sources_path):
        text = open(sources_path, encoding="utf-8").read()
        check("the replayed source list names the publisher",
              "India Maps Data" in text, text[:200])

    for layer_id in list(project.mapLayers()):
        project.removeMapLayer(layer_id)


def test_catalogue_browser_against_real_qt():
    """The Browse tab must build, list, filter and add with real Qt widgets."""
    from srot.agent import tools
    from srot.core.journal import Journal
    from srot.ui.browser import CatalogueBrowser
    from srot.ui.dock import SrotDock

    project = QgsProject.instance()
    for layer_id in list(project.mapLayers()):
        project.removeMapLayer(layer_id)

    ctx = tools.Context(None, Journal())
    panel = CatalogueBrowser(lambda: ctx)
    check("the browser builds with real Qt", panel is not None)
    check("it lists the catalogue on open", panel.results.count() > 0,
          panel.results.count())
    check("Add is disabled until something is selected",
          not panel.add_button.isEnabled())

    panel.search.setText("kerala land use")
    check("typing filters the list", panel.results.count() >= 1, panel.results.count())
    panel.results.setCurrentRow(0)
    check("selecting enables Add", panel.add_button.isEnabled())
    check("the selected entry is the Kerala land-cover layer",
          panel.current_entry()["id"] == "basemap:KL_LULC", panel.current_entry())
    check("the place box is disabled for a Bhuvan layer", not panel.place.isEnabled())

    panel.source.setCurrentIndex(4)  # OpenStreetMap
    panel.search.setText("hospital")
    panel.results.setCurrentRow(0)
    check("an OpenStreetMap entry enables the area box", panel.place.isEnabled())
    check("the area box is labelled Place for OpenStreetMap",
          panel.place_label.text() == "Place", panel.place_label.text())

    panel.source.setCurrentIndex(2)  # Boundaries
    panel.search.setText("districts")
    panel.results.setCurrentRow(0)
    check("a boundary entry enables the area box", panel.place.isEnabled())
    check("the area box is relabelled State for a boundary set",
          panel.place_label.text().startswith("State"), panel.place_label.text())
    panel.search.setText("")

    panel.source.setCurrentIndex(0)
    panel.search.setText("zzzz qqqq")
    check("a search with no matches empties the list", panel.results.count() == 0)
    check("Add is disabled again with nothing selected",
          not panel.add_button.isEnabled())

    # The apply half of the add path, with a payload standing in for the
    # download, so this stays offline.
    panel.search.setText("")
    panel.source.setCurrentIndex(2)  # Boundaries
    panel.results.setCurrentRow(0)
    entry = panel.current_entry()
    check("a boundary entry is selectable", entry["kind"] == "boundary", entry)

    added = []
    panel.layer_added.connect(lambda name: added.append(name))
    messages = []
    panel.status.connect(lambda text: messages.append(text))

    source_layer = make_layer("Browsed districts")
    project.addMapLayer(source_layer)

    class _FakeTool(object):
        fetch = None
        tier = tools.SAFE

        def apply(self, arguments, context, payload):
            return {"added": "Browsed districts", "feature_count": 6}

    panel._apply(_FakeTool(), {}, None, entry)
    check("adding emits the layer name", added == ["Browsed districts"], added)
    check("adding reports the feature count",
          any("6 features" in m for m in messages), messages[-1:])

    # A failing apply must report, not raise.
    class _BrokenTool(object):
        fetch = None
        tier = tools.SAFE

        def apply(self, arguments, context, payload):
            raise tools.ToolError("the source refused the request")

    panel._apply(_BrokenTool(), {}, None, entry)
    check("a failed add is reported rather than raised",
          any("refused" in m for m in messages), messages[-1:])

    # And the dock must carry the tab, defaulting to Browse with no model.
    keep(panel)
    dock = SrotDock()
    check("the dock has two tabs", dock.tabs.count() == 2, dock.tabs.count())
    check("the first tab is Browse", dock.tabs.tabText(0) == "Browse",
          dock.tabs.tabText(0))
    check("the second tab is Ask", dock.tabs.tabText(1) == "Ask")
    check("the dock exposes the browser", hasattr(dock, "browser"))
    dock.set_context_provider(lambda: ctx)
    check("a late-bound context resolves", dock._resolve_context() is ctx)
    keep(dock)

    for layer_id in list(project.mapLayers()):
        project.removeMapLayer(layer_id)


def test_widgets_construct():
    """The dock and the settings dialog must build under the real Qt."""
    from srot.ui.dock import SrotDock
    from srot.ui.settings_dialog import SettingsDialog

    dock = SrotDock(None)
    check("the dock widget constructs", dock is not None)
    dock.add_message("user", "Map the air quality stations in Delhi")
    dock.add_message("assistant", "Loading the CPCB feed.")
    dock.add_tool_start("add_datagov_layer", {"resource_id": "3b01bcb8", "limit": 500})
    dock.add_tool_result("add_datagov_layer", '{"added": "CPCB stations", "feature_count": 44}', True)
    dock.add_tool_result("layer_info", "No layer matches 'x'", False)
    dock.add_error("Something went wrong")
    dock.set_busy(True)
    dock.set_busy(False)
    dock.set_status("Ready.")
    text = dock.transcript.toPlainText()
    check("the transcript renders messages", "Delhi" in text, text[:160])
    check("tool results render", "CPCB stations" in text, text[-200:])
    check("example prompts are loaded", dock.examples.count() >= 8, dock.examples.count())

    dialog = SettingsDialog(None)
    check("the settings dialog constructs", dialog is not None)
    check("all providers are listed", dialog.provider.count() == 4, dialog.provider.count())
    dialog.provider.setCurrentIndex(0)
    check("switching provider updates the hint", bool(dialog.key_hint.text()))

    keep(dock)
    keep(dialog)


def test_agent_loop_with_real_tasks():
    """Drive the whole loop through the real QgsTaskManager."""
    from qgis.PyQt.QtCore import QCoreApplication, QEventLoop, QTimer

    from srot.agent import loop, providers
    from srot.core import settings

    project = QgsProject.instance()
    project.addMapLayer(make_layer("Loop districts"))

    script = [
        providers.Completion("Checking the project.", [providers.ToolCall("c1", "list_layers", {})]),
        providers.Completion("", [providers.ToolCall("c2", "resolve_place", {"name": "Pune"})]),
        providers.Completion(
            "",
            [providers.ToolCall("c3", "algorithm_help", {"algorithm_id": "native:buffer"})],
        ),
        providers.Completion(
            "",
            [
                providers.ToolCall(
                    "c4",
                    "run_processing",
                    {
                        "algorithm_id": "native:buffer",
                        "parameters": {"INPUT": "Loop districts", "DISTANCE": 0.02},
                    },
                )
            ],
        ),
        providers.Completion("Done - the buffered layer has been added.", []),
    ]
    calls = {"n": 0}

    def fake_complete(messages, tool_schemas, system_prompt, feedback=None):
        index = calls["n"]
        calls["n"] += 1
        return script[min(index, len(script) - 1)]

    original = loop.providers.complete
    loop.providers.complete = fake_complete
    try:
        settings.set_value("max_steps", "12")
        runner = loop.AgentRunner(None)
        seen = {"tools": [], "errors": [], "done": False}
        runner.tool_finished.connect(lambda n, c, ok: seen["tools"].append((n, ok)))
        runner.failed.connect(seen["errors"].append)
        runner.run_finished.connect(lambda: seen.__setitem__("done", True))

        runner.send("Buffer the districts by 0.02 degrees")

        # The loop runs on real background tasks, so pump the event loop.
        waiter = QEventLoop()
        timeout = QTimer()
        timeout.setSingleShot(True)
        timeout.timeout.connect(waiter.quit)
        runner.run_finished.connect(waiter.quit)
        runner.failed.connect(lambda _t: waiter.quit())
        timeout.start(30000)
        if not seen["done"]:
            waiter.exec()
        for _ in range(50):
            QCoreApplication.processEvents()

        check("the loop completed on real QgsTasks", seen["done"], seen["errors"])
        check("no failures were raised", not seen["errors"], seen["errors"])
        check(
            "all four tools ran and succeeded",
            [ok for _n, ok in seen["tools"]] == [True, True, True, True],
            seen["tools"],
        )
        check(
            "the buffer output reached the project",
            any("buffer" in l.name().lower() for l in project.mapLayers().values()),
            [l.name() for l in project.mapLayers().values()][:8],
        )
    finally:
        loop.providers.complete = original


def test_plugin_lifecycle():
    """initGui / unload against a stand-in iface, the real crash risk on install."""
    from qgis.PyQt.QtWidgets import QMainWindow, QMenu, QToolBar

    from srot.plugin import SrotPlugin

    class FakeIface:
        """Implements only the QgisInterface calls the plugin actually makes."""

        def __init__(self):
            self.window = QMainWindow()
            self.toolbar = QToolBar()
            self.menu = QMenu("Web")
            self.docks = []
            self.calls = []

        def mainWindow(self):
            return self.window

        def addToolBarIcon(self, action):
            self.calls.append("addToolBarIcon")
            self.toolbar.addAction(action)

        def removeToolBarIcon(self, action):
            self.calls.append("removeToolBarIcon")
            self.toolbar.removeAction(action)

        def addPluginToWebMenu(self, name, action):
            self.calls.append("addPluginToWebMenu")
            self.menu.addAction(action)

        def removePluginWebMenu(self, name, action):
            self.calls.append("removePluginWebMenu")
            self.menu.removeAction(action)

        def addDockWidget(self, area, dock):
            self.calls.append("addDockWidget")
            self.docks.append(dock)
            self.window.addDockWidget(area, dock)

        def removeDockWidget(self, dock):
            self.calls.append("removeDockWidget")
            self.window.removeDockWidget(dock)

        def mapCanvas(self):
            from qgis.gui import QgsMapCanvas

            if not hasattr(self, "_canvas"):
                self._canvas = QgsMapCanvas()
            return self._canvas

        def messageBar(self):
            from qgis.gui import QgsMessageBar

            if not hasattr(self, "_bar"):
                self._bar = QgsMessageBar()
            return self._bar

        def layerTreeView(self):
            return None

    iface = FakeIface()
    plugin = SrotPlugin(iface)

    plugin.initGui()
    check("initGui ran without raising", True)
    check("a toolbar icon was added", "addToolBarIcon" in iface.calls, iface.calls)
    check("menu entries were added", iface.calls.count("addPluginToWebMenu") == 3, iface.calls)
    check("the plugin icon file exists", os.path.exists(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icon.png")))

    plugin.show_dock()
    check("the dock opens", plugin.dock is not None and "addDockWidget" in iface.calls)
    check("a runner was wired up", plugin.runner is not None)

    plugin.show_catalogue()
    check("the catalogue action runs", True)

    plugin.unload()
    check("unload ran without raising", True)
    check("the dock was removed", "removeDockWidget" in iface.calls, iface.calls)
    check("the toolbar icon was removed", "removeToolBarIcon" in iface.calls)

    # A second load/unload cycle is what happens on plugin reload.
    plugin2 = SrotPlugin(iface)
    plugin2.initGui()
    plugin2.unload()
    check("a reload cycle is clean", True)


def test_metadata_matches_this_build():
    import configparser

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parser = configparser.ConfigParser()
    parser.read(os.path.join(root, "metadata.txt"))
    general = parser["general"]

    minimum = tuple(int(p) for p in general["qgisMinimumVersion"].split("."))
    running = tuple(int(p) for p in Qgis.QGIS_VERSION.split("-")[0].split(".")[:2])
    check(
        "this QGIS satisfies qgisMinimumVersion",
        running >= minimum[:2],
        "running {0}, minimum {1}".format(running, minimum),
    )
    check("category is valid", general["category"] in
          ("Raster", "Vector", "Database", "Mesh", "Web"), general["category"])


# ---------------------------------------------------------------------------


def main():
    app = start_qgis()
    print("QGIS {0}".format(Qgis.QGIS_VERSION))

    for name, function in [
        ("imports", test_imports),
        ("tool registry", test_tool_registry),
        ("processing", test_processing_against_real_registry),
        ("styling", test_styling_against_real_renderers),
        ("layout and export", test_layout_and_export),
        ("wms uri", test_wms_uri_shape),
        ("layer tools", test_layer_tools),
        ("provenance", test_provenance_against_real_metadata),
        ("auth manager", test_auth_manager),
        ("journal script", test_journal_script_runs),
        ("catalogue browser", test_catalogue_browser_against_real_qt),
        ("widgets", test_widgets_construct),
        ("agent loop", test_agent_loop_with_real_tasks),
        ("plugin lifecycle", test_plugin_lifecycle),
        ("metadata", test_metadata_matches_this_build),
    ]:
        section(name, function)

    failed = [row for row in RESULTS if not row[1]]
    for name, ok, detail in RESULTS:
        if not ok:
            print("FAIL  {0}\n      {1}".format(name, detail))
    print(
        "\n{0} checks against real QGIS, {1} passed, {2} failed".format(
            len(RESULTS), len(RESULTS) - len(failed), len(failed)
        )
    )
    sys.stdout.flush()
    sys.stderr.flush()

    # Every result is computed and flushed by this point. Qt objects created
    # without an event loop are destroyed in an unpredictable order during
    # interpreter teardown, which is a crash this harness has nothing to learn
    # from, so the process leaves before that happens. os._exit skips teardown
    # while still carrying the exit code CI reads.
    os._exit(1 if failed else 0)


if __name__ == "__main__":
    main()
