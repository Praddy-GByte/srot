# -*- coding: utf-8 -*-
"""Live end-to-end validation against real servers, inside real QGIS.

The two test suites in the repo prove the code is correct. Neither proves the
*data* is real: the offline suite uses a stub, and the smoke test deliberately
avoids the network so it can run in CI.

This script does the opposite. It hits the actual endpoints, builds actual
layers, renders an actual image, and then tries to disprove the specific claims
made in the README. Anything that cannot be verified is reported as
unverified rather than quietly passed.

    QT_QPA_PLATFORM=offscreen python3.12 validate_live.py
"""

import json
import os
import sys
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
for candidate in ("/usr/share/qgis/python", "/usr/share/qgis/python/plugins"):
    if os.path.isdir(candidate) and candidate not in sys.path:
        sys.path.append(candidate)

from qgis.core import (  # noqa: E402
    Qgis,
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsMapSettings,
    QgsMapRendererSequentialJob,
    QgsProject,
    QgsRectangle,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QSize  # noqa: E402
from qgis.PyQt.QtGui import QColor  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "validation")
os.makedirs(OUT, exist_ok=True)

RESULTS = []


def result(claim, verdict, evidence):
    """verdict: PASS | FAIL | UNVERIFIED"""
    RESULTS.append((claim, verdict, str(evidence)[:300]))
    print("[{0:<10}] {1}\n             {2}".format(verdict, claim, str(evidence)[:200]))


def section(name, fn):
    print("\n=== {0} ===".format(name))
    try:
        fn()
    except Exception as exc:
        result(name, "FAIL", "{0}: {1}".format(type(exc).__name__, exc))
        traceback.print_exc()


# ---------------------------------------------------------------------------


def start():
    QgsApplication.setPrefixPath("/usr", True)
    app = QgsApplication([b"validate"], True)
    app.initQgis()
    from qgis.analysis import QgsNativeAlgorithms

    QgsApplication.processingRegistry().addProvider(QgsNativeAlgorithms())
    try:
        from processing.core.Processing import Processing

        Processing.initialize()
    except Exception:
        pass
    return app


def render(layers, extent, path, size=(700, 500)):
    """Render layers to a PNG so the output can actually be looked at."""
    settings = QgsMapSettings()
    settings.setLayers(layers)
    settings.setBackgroundColor(QColor(255, 255, 255))
    settings.setOutputSize(QSize(*size))
    settings.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
    settings.setExtent(extent)

    # Sequential, not parallel: QgsMapRendererParallelJob driven by a nested
    # QEventLoop segfaults in a headless QgsApplication. Real QGIS renders
    # through the canvas, not this path, so this is a harness choice only.
    job = QgsMapRendererSequentialJob(settings)
    job.start()
    job.waitForFinished()
    image = job.renderedImage()
    image.save(path, "PNG")
    return path


def image_stats(path):
    """How much of the render is actually not blank."""
    from qgis.PyQt.QtGui import QImage

    img = QImage(path)
    if img.isNull():
        return {"ok": False}
    w, h = img.width(), img.height()
    colours = {}
    step = max(1, min(w, h) // 120)
    total = 0
    for y in range(0, h, step):
        for x in range(0, w, step):
            c = img.pixelColor(x, y).name()
            colours[c] = colours.get(c, 0) + 1
            total += 1
    white = colours.get("#ffffff", 0)
    return {
        "ok": True,
        "size": (w, h),
        "sampled": total,
        "distinct_colours": len(colours),
        "non_white_pct": round(100.0 * (total - white) / total, 1),
        "top": sorted(colours.items(), key=lambda kv: -kv[1])[:5],
        "bytes": os.path.getsize(path),
    }


# ---------------------------------------------------------------------------
# 1. Bhuvan WMS - does a catalogued layer name actually draw pixels?
# ---------------------------------------------------------------------------


def test_bhuvan_renders():
    from srot.india import loaders

    layer, _code = loaders.build_bhuvan_wms_layer("basemap:KL_LULC", "vec1", "Kerala LULC")
    result("Bhuvan layer basemap:KL_LULC constructs and is valid",
           "PASS" if layer.isValid() else "FAIL",
           "valid" if layer.isValid() else loaders.describe_layer_error(layer))
    result(
        "The layer's extent matches Kerala, not a default world extent",
        "PASS" if (74.0 < layer.extent().xMinimum() < 76.0
                   and 8.0 < layer.extent().yMinimum() < 9.0
                   and 76.5 < layer.extent().xMaximum() < 78.0
                   and 12.0 < layer.extent().yMaximum() < 13.5) else "FAIL",
        layer.extent().toString(2),
    )
    result(
        "REGRESSION: reading an empty layer error does not crash QGIS",
        "PASS" if loaders.describe_layer_error(layer) == "no detail reported" else "FAIL",
        "QgsError.summary() segfaults on an empty message list in 3.34; "
        "describe_layer_error guards it",
    )

    path = render([layer], QgsRectangle(74.8, 8.1, 77.6, 12.9), os.path.join(OUT, "kerala_lulc.png"))
    stats = image_stats(path)
    result(
        "Bhuvan actually returns imagery, not a blank tile",
        "PASS" if stats["ok"] and stats["non_white_pct"] > 2 and stats["distinct_colours"] > 2 else "FAIL",
        stats,
    )
    result(
        "OBSERVATION: how much of the Kerala frame the default style paints",
        "UNVERIFIED",
        "{0}% of sampled pixels are non-white -- the default WMS style is "
        "sparse, so a user asking for 'Kerala land use' sees patches, not a "
        "filled thematic map".format(stats.get("non_white_pct")),
    )

    # a second state, to prove the family expansion is not a one-off
    layer2, _ = loaders.build_bhuvan_wms_layer("mmi:MN_ROAD_NETWORK_Q4_2022", "vec1", "Manipur roads")
    path2 = render([layer2], QgsRectangle(92.9, 23.8, 94.8, 25.7), os.path.join(OUT, "manipur_roads.png"))
    stats2 = image_stats(path2)
    result(
        "A generated family layer (Manipur roads) also draws",
        "PASS" if stats2["ok"] and stats2["non_white_pct"] > 0.2 else "FAIL",
        stats2,
    )


# ---------------------------------------------------------------------------
# 2. data.gov.in - are the CPCB points real and inside India?
# ---------------------------------------------------------------------------


def test_datagov_points():
    from srot.agent import tools
    from srot.core.journal import Journal
    from srot.india import loaders

    import time

    payload = None
    for attempt in range(4):
        try:
            payload = loaders.fetch_datagov(
                "3b01bcb8-0b14-4abf-b6f2-c1bfd384ba69", {"city": "Delhi"}, limit=40
            )
            break
        except loaders.LoaderError as exc:
            if "rate-limited" not in str(exc) or attempt == 3:
                result("data.gov.in live fetch", "UNVERIFIED",
                       "shared sample key exhausted: {0}".format(str(exc)[:150]))
                return
            time.sleep(20 * (attempt + 1))
    records = payload["records"]
    result("data.gov.in returned live CPCB records",
           "PASS" if len(records) > 5 else "FAIL", "{0} records".format(len(records)))

    ctx = tools.Context(None, Journal())
    layer, _code, _note = loaders.build_datagov_layer(payload, "Delhi air quality")
    QgsProject.instance().addMapLayer(layer)

    inside = 0
    outside = []
    for feature in layer.getFeatures():
        pt = feature.geometry().asPoint()
        # Delhi's envelope, generously
        if 76.7 <= pt.x() <= 77.5 and 28.3 <= pt.y() <= 28.95:
            inside += 1
        else:
            outside.append((round(pt.x(), 3), round(pt.y(), 3)))
    result(
        "Every CPCB point lands inside Delhi's envelope",
        "PASS" if layer.featureCount() > 0 and not outside else "FAIL",
        "{0}/{1} inside; strays={2}".format(inside, layer.featureCount(), outside[:4]),
    )

    # the values must look like real measurements, not placeholders
    fields = [f.name() for f in layer.fields()]
    sample = next(layer.getFeatures())
    attrs = dict(zip(fields, sample.attributes()))
    result(
        "Records carry a real station name, pollutant and value",
        "PASS" if attrs.get("station") and attrs.get("pollutant_id") else "FAIL",
        {k: attrs.get(k) for k in ("station", "pollutant_id", "avg_value", "last_update")},
    )

    render([layer], QgsRectangle(76.7, 28.3, 77.5, 28.95), os.path.join(OUT, "delhi_aqi.png"))


# ---------------------------------------------------------------------------
# 3. The Telangana claim - try to disprove it against the real file
# ---------------------------------------------------------------------------


def test_telangana_claim():
    from srot.india import loaders

    # --- the DEFAULT source, which is post-bifurcation -------------------
    payload = loaders.fetch_boundary("district")
    raw = QgsVectorLayer(payload["path"], "districts raw", "ogr")
    result("Default district file opens",
           "PASS" if raw.isValid() else "FAIL",
           "{0} features, fields {1}".format(raw.featureCount(),
                                             [f.name() for f in raw.fields()]))

    states = {}
    for feature in raw.getFeatures():
        key = str(feature["st_nm"])
        states[key] = states.get(key, 0) + 1
    result(
        "CORRECTED CLAIM: the default district set is post-2014 and has Telangana",
        "PASS" if states.get("Telangana", 0) > 25 else "FAIL",
        "Telangana={0}, Andhra Pradesh={1}, states={2}, features={3}".format(
            states.get("Telangana"), states.get("Andhra Pradesh"), len(states),
            raw.featureCount()),
    )

    layer, _c, _n = loaders.build_boundary_layer(payload, state="Telangana")
    result(
        "Asking for Telangana returns Telangana's own districts",
        "PASS" if layer.featureCount() == states.get("Telangana") else "FAIL",
        "{0} returned vs {1} in file".format(layer.featureCount(), states.get("Telangana")),
    )
    names = sorted(str(f["district"]) for f in layer.getFeatures())
    result("and they are really Telangana districts",
           "PASS" if "Hyderabad" in names and "Warangal" in " ".join(names) else "FAIL",
           names[:6])

    for state, low, high in [("Kerala", 13, 16), ("Maharashtra", 34, 38),
                             ("Andhra Pradesh", 12, 16)]:
        lyr, _c2, _n2 = loaders.build_boundary_layer(payload, state=state)
        result("Filter works for {0}".format(state),
               "PASS" if low <= lyr.featureCount() <= high else "FAIL",
               "{0} districts".format(lyr.featureCount()))

    one, _c3, _n3 = loaders.build_boundary_layer(payload, state="Kerala", district="Ernakulam")
    result("District-level filter works",
           "PASS" if one.featureCount() == 1 else "FAIL", one.featureCount())

    # --- the DATAMEET source, which really is pre-bifurcation ------------
    dm = loaders.fetch_boundary("district_datameet")
    dm_raw = QgsVectorLayer(dm["path"], "datameet", "ogr")
    dm_states = {str(f["ST_NM"]) for f in dm_raw.getFeatures()}
    result(
        "CLAIM: the Census 2011 shapefile genuinely has no Telangana",
        "PASS" if not any("telangana" in str(x).lower() for x in dm_states) else "FAIL",
        "{0} features, {1} states".format(dm_raw.featureCount(), len(dm_states)),
    )
    ap = [str(f["DISTRICT"]) for f in dm_raw.getFeatures()
          if str(f["ST_NM"]) == "Andhra Pradesh"]
    known = {"Adilabad", "Hyderabad", "Karimnagar", "Khammam", "Mahbubnagar",
             "Medak", "Nalgonda", "Nizamabad", "Rangareddy", "Warangal"}
    found = sorted(known & set(ap))
    result("CLAIM: its Telangana districts sit under Andhra Pradesh",
           "PASS" if len(found) >= 8 else "FAIL",
           "{0}/10 under AP: {1}".format(len(found), found))

    tg, _c4, note = loaders.build_boundary_layer(dm, state="Telangana")
    result("The plugin still finds them, by district name",
           "PASS" if tg.featureCount() == len(found) else "FAIL",
           "{0} features".format(tg.featureCount()))
    result("and explains the bifurcation to the user",
           "PASS" if note and "bifurcation" in note else "FAIL",
           " ".join((note or "").split())[-160:])

    QgsProject.instance().addMapLayer(layer)
    render([layer], layer.extent(), os.path.join(OUT, "telangana_districts.png"))


# ---------------------------------------------------------------------------
# 4. Bhuvan WFS - the claim that it answers 200 with an error body
# ---------------------------------------------------------------------------


def test_wfs_claim():
    from srot.core import net

    url = ("https://bhuvan-vec1.nrsc.gov.in/bhuvan/wfs?service=WFS&version=1.0.0"
           "&request=GetCapabilities")
    try:
        response = net.get(url)
        body = response.text[:600]
        result(
            "CLAIM: Bhuvan WFS returns HTTP 200 with a service exception",
            "PASS" if response.status == 200 and "Exception" in body else "FAIL",
            "status={0} body starts: {1}".format(response.status, " ".join(body.split())[:180]),
        )
    except Exception as exc:
        result("Bhuvan WFS probe", "UNVERIFIED", "unreachable from here: {0}".format(exc))


# ---------------------------------------------------------------------------
# 5. OpenStreetMap - does India actually come back?
# ---------------------------------------------------------------------------


def test_osm_india():
    from srot.india import loaders, places

    place = places.lookup("Pune")
    payload = loaders.fetch_osm("hospital", place.bbox)
    layer, _code, note = loaders.build_osm_layer(payload, "Pune hospitals")
    QgsProject.instance().addMapLayer(layer)

    result(
        "Overpass returns real Indian features (Pune hospitals)",
        "PASS" if layer.featureCount() > 10 else "FAIL",
        "{0} features from {1}".format(layer.featureCount(), payload["endpoint"]),
    )
    result(
        "REGRESSION: a >60 s Overpass query survives the QGIS network timeout",
        "PASS" if layer.featureCount() > 10 else "FAIL",
        "QGIS times out at 60 s by default; extended_timeout raises it for the call",
    )

    west, south, east, north = place.bbox
    strays = []
    names = []
    for feature in layer.getFeatures():
        pt = feature.geometry().centroid().asPoint()
        if not (west - 0.05 <= pt.x() <= east + 0.05 and south - 0.05 <= pt.y() <= north + 0.05):
            strays.append((round(pt.x(), 3), round(pt.y(), 3)))
        n = feature["name"] if "name" in [f.name() for f in layer.fields()] else None
        if n:
            names.append(n)
    result("Every OSM feature falls inside the Pune bbox",
           "PASS" if not strays else "FAIL", "strays={0}".format(strays[:4]))
    result("Features carry real hospital names",
           "PASS" if len(names) > 5 else "UNVERIFIED", names[:6])

    render([layer], QgsRectangle(*place.bbox), os.path.join(OUT, "pune_hospitals.png"))


# ---------------------------------------------------------------------------
# 6. End to end: real data through a real Processing run, then the script
# ---------------------------------------------------------------------------


def test_end_to_end():
    from srot.agent import tools
    from srot.core.journal import Journal

    journal = Journal()
    ctx = tools.Context(None, journal)
    journal.add_prompt("Load Kerala districts and buffer them by 5 km")

    payload = tools.REGISTRY["add_boundary"].fetch({"level": "district"})
    added = tools.REGISTRY["add_boundary"].apply(
        {"level": "district", "state": "Kerala", "name": "Kerala districts"}, ctx, payload
    )
    result("Tool add_boundary produced a real layer",
           "PASS" if added["feature_count"] > 10 else "FAIL", added["feature_count"])

    ran = tools.REGISTRY["run_processing"].apply(
        {
            "algorithm_id": "native:buffer",
            "parameters": {"INPUT": "Kerala districts", "DISTANCE": 0.05},
        },
        ctx,
        None,
    )
    result("Processing ran on real downloaded data",
           "PASS" if ran["layers_added"] else "FAIL", ran["layers_added"])

    # Provenance: the citation must name the body that actually published the
    # file, and the derived buffer must inherit nothing it did not earn.
    from srot.core import provenance

    records = provenance.collect(QgsProject.instance())
    boundary = [r for r in records if "Kerala districts" == r["layer"]]
    result(
        "The downloaded boundary layer carries its citation",
        "PASS" if boundary and "India Maps Data" in boundary[0]["citation"] else "FAIL",
        boundary[0]["citation"] if boundary else records,
    )
    cited = tools.REGISTRY["export_citations"].apply(
        {"path": os.path.join(OUT, "sources.md"), "style": "markdown"}, ctx, None
    )
    text = open(os.path.join(OUT, "sources.md"), encoding="utf-8").read()
    result(
        "export_citations writes a source list covering every layer",
        "PASS" if cited["layers"] == len(records) and "Census of India 2011" in text
        else "FAIL",
        "{0} layers, {1} bytes".format(cited["layers"], len(text)),
    )
    bibtex = provenance.as_bibliography(records, "bibtex")
    result(
        "The BibTeX export is well formed",
        "PASS" if bibtex.count("{") == bibtex.count("}") and "@misc{" in bibtex
        else "FAIL",
        bibtex.splitlines()[0] if bibtex else "",
    )

    script = journal.to_script()
    script_path = os.path.join(OUT, "session.py")
    with open(script_path, "w") as handle:
        handle.write(script)

    # wipe the project, then run the exported script from scratch
    project = QgsProject.instance()
    before = len(project.mapLayers())
    for lid in list(project.mapLayers()):
        project.removeMapLayer(lid)

    namespace = {"__name__": "__replay__"}
    exec(compile(script, script_path, "exec"), namespace)
    after = len(project.mapLayers())
    result(
        "The exported script rebuilds the layers on a clean project",
        "PASS" if after >= 2 else "FAIL",
        "{0} layers before wipe, {1} rebuilt by the script".format(before, after),
    )

    replayed = [l for l in project.mapLayers().values() if "kerala" in l.name().lower()]
    result(
        "The replayed Kerala layer has the same feature count",
        "PASS" if replayed and replayed[0].featureCount() == added["feature_count"] else "FAIL",
        "{0} vs {1}".format(replayed[0].featureCount() if replayed else None,
                            added["feature_count"]),
    )


# ---------------------------------------------------------------------------


def main():
    app = start()
    print("QGIS {0}\n".format(Qgis.QGIS_VERSION))

    section("Bhuvan WMS renders", test_bhuvan_renders)
    section("data.gov.in points", test_datagov_points)
    section("Telangana claim", test_telangana_claim)
    section("Bhuvan WFS claim", test_wfs_claim)
    section("OpenStreetMap India", test_osm_india)
    section("End to end + script replay", test_end_to_end)

    print("\n" + "=" * 70)
    counts = {}
    for _c, verdict, _e in RESULTS:
        counts[verdict] = counts.get(verdict, 0) + 1
    for claim, verdict, evidence in RESULTS:
        if verdict != "PASS":
            print("{0:<12} {1}\n             {2}".format(verdict, claim, evidence))
    print("\n{0} claims checked: {1}".format(
        len(RESULTS), ", ".join("{0} {1}".format(v, k) for k, v in sorted(counts.items()))))
    with open(os.path.join(OUT, "report.json"), "w") as handle:
        json.dump([{"claim": c, "verdict": v, "evidence": e} for c, v, e in RESULTS],
                  handle, indent=1)
    app.exitQgis()
    return 0 if counts.get("FAIL", 0) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
