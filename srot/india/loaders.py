# -*- coding: utf-8 -*-
"""Turning Indian data sources into QGIS layers.

Every loader is split in two on purpose:

``fetch_*``
    Pure network and file work.  Safe to run inside a ``QgsTask``, must never
    touch ``QgsProject`` or any widget.

``build_*``
    Constructs the layer from what ``fetch_*`` produced.  Must run on the GUI
    thread.

Keeping that split explicit is what stops the plugin from freezing QGIS during
a 10 MB boundary download, and what stops it from crashing by building layers
off-thread.
"""

import json
import os
import re
import tempfile

from qgis.core import (
    QgsDataSourceUri,
    QgsRasterLayer,
    QgsVectorLayer,
)

from ..core import net, settings
from . import catalog, places


#: Bhuvan's GetCapabilities is 7-10 MB and has been observed taking 19-47 s;
#: past 60 s the QGIS default cuts the connection and the layer silently fails.
BHUVAN_TIMEOUT_MS = 180000


class LoaderError(Exception):
    """A data source could not be used, with a message fit for the user."""


def _cache_dir():
    path = os.path.join(tempfile.gettempdir(), "srot_cache")
    os.makedirs(path, exist_ok=True)
    return path


def _safe(name):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(name))[:80]


def describe_layer_error(layer):
    """Read a layer's error text without crashing the QGIS process.

    ``QgsError.summary()`` reads the last entry of an internal message list and
    does not guard against that list being empty -- calling it on a layer whose
    error is empty segfaults QGIS 3.34. A layer that failed to load normally has
    a message, but not every provider failure populates one, and a crash is a
    far worse outcome than a vague message. So check first.
    """
    try:
        error = layer.error()
        if error is None or error.isEmpty():
            return "no detail reported"
        return error.summary() or "no detail reported"
    except Exception:
        return "no detail reported"


# ---------------------------------------------------------------------------
# Bhuvan WMS
# ---------------------------------------------------------------------------


def build_bhuvan_wms_layer(layer_name, host_id="vec1", title=None, image_format="image/png"):
    """Build a Bhuvan WMS raster layer.  GUI thread.

    Note for the caller: the QGIS WMS provider fetches GetCapabilities when the
    layer is constructed, and Bhuvan's is 7-10 MB and can take up to a minute
    on a first, uncached request.  Warn the user before calling this.
    """
    if host_id == "tilecache":
        return build_bhuvan_imagery_layer(layer_name, title)

    url = catalog.bhuvan_host_url(host_id)
    uri = QgsDataSourceUri()
    uri.setParam("crs", "EPSG:4326")
    uri.setParam("format", image_format)
    uri.setParam("layers", layer_name)
    uri.setParam("styles", "")
    uri.setParam("url", url)
    encoded = bytes(uri.encodedUri()).decode("utf-8")

    # Constructing a WMS layer makes the provider fetch GetCapabilities, and
    # Bhuvan's is 7-10 MB. That regularly runs past the 60 s QGIS allows by
    # default, and the layer then comes back invalid for what looks like no
    # reason. Give the provider room for one call.
    with net.extended_timeout(BHUVAN_TIMEOUT_MS):
        layer = QgsRasterLayer(encoded, title or layer_name, "wms")
        valid = layer.isValid()
    if not valid:
        raise LoaderError(
            "Bhuvan did not serve '{0}'. Layer names are case sensitive and "
            "namespaced. The closest names in the catalogue are: {1}. "
            "Detail: {2}".format(
                layer_name, _nearest_layer_names(layer_name), describe_layer_error(layer)
            )
        )
    return layer, _wms_snippet(encoded, title or layer_name)


def build_bhuvan_imagery_layer(layer_name="bhuvan_imagery", title=None):
    """Bhuvan satellite imagery from the WMS-C tilecache.  GUI thread.

    The tilecache 302-redirects GetMap to a JPEG, so redirect following must
    stay on -- QGIS does that by default and we do not override it.
    """
    uri = QgsDataSourceUri()
    uri.setParam("crs", "EPSG:4326")
    uri.setParam("format", "image/jpeg")
    uri.setParam("layers", layer_name)
    uri.setParam("styles", "")
    uri.setParam("url", catalog.BHUVAN_TILECACHE)
    encoded = bytes(uri.encodedUri()).decode("utf-8")

    with net.extended_timeout(BHUVAN_TIMEOUT_MS):
        layer = QgsRasterLayer(encoded, title or "Bhuvan imagery", "wms")
        valid = layer.isValid()
    if not valid:
        raise LoaderError(
            "Could not load Bhuvan imagery layer '{0}'. Known tilecache layers "
            "are: bhuvan_imagery, bhuvan_img, bhuvan_imagery2, "
            "bhuvan_imagery_2018to20, bhuvan_img_3d.".format(layer_name)
        )
    return layer, _wms_snippet(encoded, title or "Bhuvan imagery")


def _nearest_layer_names(layer_name, limit=5):
    """The catalogued names closest to what was asked for.

    A refused name is nearly always a near miss, so answering with the
    neighbours turns a dead end into a one-step correction.
    """
    import difflib

    known = [entry["name"] for entry in catalog.BHUVAN_LAYERS]
    known += [entry["name"] for entry in catalog.bhuvan_layers.all_layers()]
    close = difflib.get_close_matches(layer_name, known, n=limit, cutoff=0.55)
    if not close:
        stem = layer_name.split(":")[-1].lower()
        close = [n for n in known if stem[:6] and stem[:6] in n.lower()][:limit]
    return ", ".join(close) if close else "use search_india_data to list what is available"


def probe_bhuvan_layer(layer_name, host_id="vec1", bbox=None, feedback=None):
    """Ask Bhuvan for a small tile and report whether anything is actually on it.

    A WMS layer can be perfectly valid and still be useless: Bhuvan answers a
    GetMap for an empty layer with a 256x256 PNG carrying nothing but its own
    watermark, and it aborts anything that takes its renderer over 60 seconds
    with a ServiceException. Both look like success to a status-code check, and
    both leave the user staring at a blank canvas wondering what they did wrong.

    Off-thread. Returns a verdict: ``draws``, ``empty``, ``too_slow``,
    ``error`` or ``unknown``.
    """
    from qgis.PyQt.QtGui import QImage

    west, south, east, north = bbox or (68.0, 6.0, 97.5, 37.6)
    url = "{0}?{1}".format(
        catalog.bhuvan_host_url(host_id),
        "&".join(
            [
                "service=WMS", "version=1.1.1", "request=GetMap",
                "layers=" + layer_name, "styles=", "srs=EPSG:4326",
                "bbox={0},{1},{2},{3}".format(west, south, east, north),
                "width=256", "height=256", "format=image/png",
            ]
        ),
    )
    try:
        # Bhuvan's own renderer gives up at 60 s and then sends a
        # ServiceException. QGIS's default network timeout is also 60 s, so
        # without headroom the connection is cut a moment before that
        # explanation arrives and a slow layer looks like a dead server.
        with net.extended_timeout(BHUVAN_TIMEOUT_MS):
            response = net.get(url, feedback=feedback)
    except Exception as exc:
        return {"verdict": "error", "detail": str(exc)[:200]}

    head = response.content[:400].decode("utf-8", errors="replace")
    if "ServiceException" in head or "<?xml" in head[:10]:
        message = " ".join(head.split())
        if "more time than allowed" in message or "Max rendering time" in message:
            return {
                "verdict": "too_slow",
                "detail": (
                    "Bhuvan aborted the render: its server gives up after 60 seconds. "
                    "This layer is a group of per-district layers, so it only draws "
                    "over a district-sized extent, not a whole state."
                ),
            }
        return {"verdict": "error", "detail": message[:220]}

    image = QImage()
    if not image.loadFromData(response.content):
        return {"verdict": "unknown", "detail": "the response was not a readable image"}

    width, height = image.width(), image.height()
    if width == 0 or height == 0:
        return {"verdict": "unknown", "detail": "empty image"}

    counts = {}
    step = max(1, min(width, height) // 48)
    total = 0
    for y in range(0, height, step):
        for x in range(0, width, step):
            key = image.pixel(x, y)
            counts[key] = counts.get(key, 0) + 1
            total += 1
    dominant = max(counts.values()) if counts else total
    ink = 100.0 * (total - dominant) / max(1, total)

    # Bhuvan stamps its own watermark on an otherwise empty tile, which lands
    # at roughly 1.5% of the pixels. Anything at or under 3% is blank in every
    # way that matters to a user.
    if ink <= 3.0:
        return {
            "verdict": "empty",
            "detail": (
                "Bhuvan returned a tile with nothing on it but its watermark "
                "({0:.1f}% ink). The layer exists on the server but has no "
                "features here.".format(ink)
            ),
            "ink": round(ink, 1),
        }
    return {"verdict": "draws", "detail": "{0:.1f}% of the tile is drawn".format(ink),
            "ink": round(ink, 1)}


def _wms_snippet(uri, name):
    # {var} is filled in by the tool with the journal's variable name for this
    # layer, so later steps in the exported script can refer back to it.
    return (
        '{{var}} = QgsRasterLayer({uri!r}, {name!r}, "wms")\n'
        'project.addMapLayer({{var}})'
    ).format(uri=uri, name=name)


def fetch_bhuvan_layer_names(host_id="vec1", search_term="", feedback=None):
    """Parse GetCapabilities for layer names.  Off-thread, slow (7-10 MB).

    We stream-match on the XML rather than building a DOM, because a full parse
    of a 10 MB capabilities document inside QGIS is needlessly expensive.
    """
    url = catalog.bhuvan_host_url(host_id)
    full = "{0}?service=WMS&version=1.1.1&request=GetCapabilities".format(url)
    cache_file = os.path.join(_cache_dir(), "bhuvan_caps_{0}.xml".format(_safe(host_id)))

    if os.path.exists(cache_file) and os.path.getsize(cache_file) > 1024:
        with open(cache_file, "rb") as handle:
            body = handle.read()
    else:
        body = net.get(full, feedback=feedback).content
        with open(cache_file, "wb") as handle:
            handle.write(body)

    text = body.decode("utf-8", errors="replace")
    if "ServiceUnavailable" in text[:4000]:
        raise LoaderError(
            "Bhuvan answered with a service exception. Note that Bhuvan's WFS "
            "is disabled server-side and returns HTTP 200 with an exception "
            "body; only WMS is usable."
        )

    names = re.findall(r"<Name>([^<]{2,200})</Name>", text)
    titles = dict(zip(names, re.findall(r"<Title>([^<]{0,300})</Title>", text[1:])))

    term = (search_term or "").strip().lower()
    hits = []
    for name in names:
        if ":" not in name:
            continue
        if term and term not in name.lower() and term not in titles.get(name, "").lower():
            continue
        hits.append({"name": name, "title": titles.get(name, "")})
        if len(hits) >= 60:
            break
    return {"host": host_id, "url": url, "count": len(names), "layers": hits}


# ---------------------------------------------------------------------------
# Boundaries
# ---------------------------------------------------------------------------


def fetch_boundary(level, feedback=None):
    """Download a boundary dataset to the cache.  Off-thread.

    Returns a dict with the local path and the source metadata.
    """
    source = catalog.BOUNDARY_SOURCES.get(level)
    if source is None:
        raise LoaderError(
            "Unknown boundary level '{0}'. Available: {1}".format(
                level, ", ".join(sorted(catalog.BOUNDARY_SOURCES))
            )
        )

    url = source["url"]
    stem = _safe(level)
    if source["format"] == "geojson":
        path = os.path.join(_cache_dir(), stem + ".geojson")
        if not (os.path.exists(path) and os.path.getsize(path) > 1024):
            net.download_to(url, path, feedback=feedback)
    else:
        base_url = url[: -len(".shp")]
        path = os.path.join(_cache_dir(), stem + ".shp")
        if not (os.path.exists(path) and os.path.getsize(path) > 1024):
            net.download_to(url, path, feedback=feedback)
            for ext in source.get("sidecars", []):
                net.download_to(base_url + ext, os.path.join(_cache_dir(), stem + ext), feedback=feedback)

    return {"path": path, "level": level, "source": source}


def build_boundary_layer(payload, state=None, district=None, name=None):
    """Build the boundary layer and optionally filter it.  GUI thread."""
    source = payload["source"]
    path = payload["path"]

    layer = QgsVectorLayer(path, name or source["title"], "ogr")
    if not layer.isValid():
        raise LoaderError("QGIS could not open the downloaded boundary file at {0}".format(path))

    if source["format"] == "shapefile":
        # Datameet publishes no .cpg alongside the shapefile, so OGR has to
        # guess the encoding and gets Indian place names wrong. Set it
        # explicitly through the provider rather than via a URI suffix.
        try:
            layer.setProviderEncoding("UTF-8")
        except Exception:
            pass

    clauses = []
    notes = []
    if not source.get("official_boundary", False):
        # India's Geospatial Data Guidelines make Survey of India maps and SoI
        # digital boundary data the standard for political maps of India. These
        # community and GADM-derived files are not that, and their depiction of
        # disputed boundaries differs. Say so rather than letting the layer pass
        # as authoritative.
        notes.append(
            "{0} is community or GADM-derived, not Survey of India data. Use it "
            "for analysis; for a published map of India the SoI outline "
            "(add_boundary level='country') is the standard, and administrative "
            "boundaries should be checked against SoI.".format(source["title"])
        )
    if state:
        state_field = source.get("state_field")
        if state_field:
            clauses.append(_ilike(state_field, state))
    if district:
        join_field = source.get("join_field")
        if join_field:
            clauses.append(_ilike(join_field, district))

    if clauses:
        expression = " AND ".join(clauses)
        _apply_subset(layer, expression, source)

        # Telangana is the one case where an empty result is expected rather
        # than a mistake: boundary files published before the 2014 bifurcation
        # have no Telangana at all, and file its districts under Andhra
        # Pradesh. Which file this is cannot be assumed -- the default district
        # source does carry Telangana -- so probe the data instead of rewriting
        # the query up front, which would silently return Andhra Pradesh's own
        # districts to someone who asked for Telangana.
        if layer.featureCount() == 0 and state and places.normalise(state) == "telangana":
            fallback = _telangana_fallback(layer, source, district)
            if fallback is not None:
                expression, clauses = fallback, [fallback]
                notes.append(
                    "This file predates the 2014 bifurcation and has no "
                    "Telangana, so its districts are filed under Andhra "
                    "Pradesh. Selected them by district name instead. For a "
                    "post-2014 boundary set use add_boundary level='district'."
                )

        if layer.featureCount() == 0:
            available = _sample_values(layer, source.get("state_field") or source.get("join_field"))
            layer.setSubsetString("")
            raise LoaderError(
                "The filter {0!r} matched no features in {1}. Values in that "
                "file look like: {2}".format(expression, source["title"], available)
            )

    code = (
        '{{var}} = QgsVectorLayer({path!r}, {name!r}, "ogr")\n'
        '{enc}{filt}'
        'project.addMapLayer({{var}})'
    ).format(
        path=path,
        name=layer.name(),
        enc=(
            '{var}.setProviderEncoding("UTF-8")\n'
            if source["format"] == "shapefile"
            else ""
        ),
        filt=(
            "{{var}}.setSubsetString({0!r})\n".format(" AND ".join(clauses))
            if clauses
            else ""
        ),
    )
    return layer, code, " ".join(notes) or None


def _sql_lit(text):
    return str(text).replace("'", "''")


def _ilike(field, value):
    """A case-insensitive equality test OGR will actually accept.

    OGR's GeoJSON driver rejects ``lower("field") = 'value'`` outright --
    setSubsetString returns False and the layer is left unfiltered. ILIKE is
    supported, and is case-insensitive, which is what was wanted anyway.
    """
    return "\"{0}\" ILIKE '{1}'".format(field, _sql_lit(value))


def _apply_subset(layer, expression, source):
    if not layer.setSubsetString(expression):
        layer.setSubsetString("")
        raise LoaderError(
            "QGIS refused the filter {0!r} on {1}. Available fields: {2}".format(
                expression, source["title"], ", ".join(f.name() for f in layer.fields())
            )
        )


def _sample_values(layer, field):
    """A few real values from a field, to put in an error message."""
    if not field:
        return "(unknown field)"
    try:
        layer.setSubsetString("")
        index = layer.fields().indexOf(field)
        if index < 0:
            return "(no field {0!r})".format(field)
        values = sorted({str(v) for v in layer.uniqueValues(index, 8)})
        return ", ".join(values[:8])
    except Exception:
        return "(could not be read)"


def _telangana_fallback(layer, source, district=None):
    """Select Telangana's districts from a pre-2014 file, by district name.

    Returns the expression that worked, or None if this file is not one of the
    pre-bifurcation sets after all.
    """
    state_field = source.get("state_field")
    join_field = source.get("join_field")
    if not (state_field and join_field):
        return None

    wanted = sorted(places.TELANGANA_IN_CENSUS_AP)
    if district:
        if places.normalise(district) not in places.TELANGANA_IN_CENSUS_AP:
            return None
        wanted = [district]

    names = " OR ".join(_ilike(join_field, name) for name in wanted)
    expression = "{0} AND ({1})".format(_ilike(state_field, "Andhra Pradesh"), names)
    if not layer.setSubsetString(expression):
        layer.setSubsetString("")
        return None
    if layer.featureCount() == 0:
        layer.setSubsetString("")
        return None
    return expression


# ---------------------------------------------------------------------------
# data.gov.in
# ---------------------------------------------------------------------------


def fetch_datagov(resource_id, filters=None, limit=500, feedback=None):
    """Page through a data.gov.in resource.  Off-thread."""
    from urllib.parse import urlencode

    api_key = settings.datagov_api_key()
    collected = []
    offset = 0
    page_size = min(int(limit), 1000)
    fields_meta = []

    while len(collected) < int(limit):
        params = [
            ("api-key", api_key),
            ("format", "json"),
            ("limit", str(min(page_size, int(limit) - len(collected)))),
            ("offset", str(offset)),
        ]
        for key, value in (filters or {}).items():
            if value not in (None, ""):
                params.append(("filters[{0}]".format(key), str(value)))

        url = catalog.DATAGOV_BASE.format(resource_id=resource_id) + "?" + urlencode(params)
        try:
            data = net.get_json(url, feedback=feedback)
        except net.HttpError as exc:
            if exc.status == 429:
                raise LoaderError(
                    "data.gov.in rate-limited the request. {0}".format(
                        "You are using the portal's shared sample key, which runs "
                        "out within a few calls. Register a free key at "
                        "data.gov.in and set it in the plugin settings."
                        if settings.datagov_key_is_shared()
                        else "Wait a moment and try again."
                    )
                )
            if exc.status == 403:
                raise LoaderError(
                    "data.gov.in rejected the API key. Register a free key at "
                    "data.gov.in (My Account -> APIs) and set it in the plugin settings."
                )
            raise

        records = data.get("records") or []
        fields_meta = data.get("field") or fields_meta
        collected.extend(records)
        if len(records) < int(params[2][1]):
            break
        offset += len(records)

    return {
        "resource_id": resource_id,
        "records": collected,
        "fields": fields_meta,
        "filters": filters or {},
    }


def build_datagov_layer(payload, name=None):
    """Build a point layer (if geocodable) or a table.  GUI thread."""
    resource_id = payload["resource_id"]
    records = payload["records"]
    meta = catalog.find_datagov_resource(resource_id) or {}

    if not records:
        raise LoaderError(
            "data.gov.in returned no records for that query. Try relaxing the "
            "filters -- their values are case sensitive."
        )

    lat_field = meta.get("lat_field")
    lon_field = meta.get("lon_field")
    location_field = meta.get("location_field")

    if not (lat_field or location_field):
        lat_field, lon_field = _sniff_coordinate_fields(records[0])
    if not (lat_field or location_field):
        return _build_table_layer(records, name or meta.get("title") or resource_id)

    features = []
    skipped = 0
    for record in records:
        lon, lat = _record_coordinates(record, lat_field, lon_field, location_field)
        if lon is None:
            skipped += 1
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {k: _scalar(v) for k, v in record.items()},
            }
        )

    if not features:
        return _build_table_layer(records, name or meta.get("title") or resource_id)

    collection = {"type": "FeatureCollection", "features": features}
    path = os.path.join(
        _cache_dir(), "datagov_{0}.geojson".format(_safe(resource_id)[:20])
    )
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(collection, handle)

    layer = QgsVectorLayer(path, name or meta.get("title") or resource_id, "ogr")
    if not layer.isValid():
        raise LoaderError("Could not build a layer from the data.gov.in response.")

    note = None
    if skipped:
        note = "{0} of {1} records had no usable coordinates and were dropped.".format(
            skipped, len(records)
        )
    code = (
        '# {n} features written by Srot from data.gov.in resource {rid}\n'
        '{{var}} = QgsVectorLayer({path!r}, {name!r}, "ogr")\n'
        'project.addMapLayer({{var}})'
    ).format(n=len(features), rid=resource_id, path=path, name=layer.name())
    return layer, code, note


def _sniff_coordinate_fields(record):
    lat_key = lon_key = None
    for key in record:
        low = key.lower()
        if lat_key is None and ("latitude" in low or low.endswith("_lat") or low == "lat"):
            lat_key = key
        if lon_key is None and (
            "longitude" in low or low.endswith("_long") or low.endswith("_lon") or low in ("lon", "lng")
        ):
            lon_key = key
    if lat_key and lon_key:
        return lat_key, lon_key
    return None, None


def _record_coordinates(record, lat_field, lon_field, location_field):
    try:
        if location_field:
            raw = str(record.get(location_field) or "")
            parts = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
            if len(parts) < 2:
                return None, None
            return float(parts[1]), float(parts[0])
        lat = float(str(record.get(lat_field)).strip())
        lon = float(str(record.get(lon_field)).strip())
    except (TypeError, ValueError):
        return None, None
    # Reject anything outside India's envelope plus a margin - these feeds
    # contain 0,0 placeholders and swapped pairs.
    if not (60.0 <= lon <= 100.0 and 5.0 <= lat <= 40.0):
        return None, None
    return lon, lat


def _scalar(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def _build_table_layer(records, name):
    keys = list(records[0].keys())
    fields = "&".join("field={0}:string".format(re.sub(r"\W+", "_", k)) for k in keys)
    layer = QgsVectorLayer("None?{0}".format(fields), name, "memory")
    if not layer.isValid():
        raise LoaderError("Could not build an attribute-only layer.")
    provider = layer.dataProvider()
    from qgis.core import QgsFeature

    feats = []
    for record in records:
        feature = QgsFeature(layer.fields())
        feature.setAttributes([str(_scalar(record.get(k, ""))) for k in keys])
        feats.append(feature)
    provider.addFeatures(feats)
    layer.updateExtents()
    note = (
        "This dataset has no coordinates, so it was loaded as an attribute table. "
        "Join it to a boundary layer to map it."
    )
    return layer, "# attribute-only layer with {0} rows".format(len(records)), note


# ---------------------------------------------------------------------------
# OpenStreetMap via Overpass
# ---------------------------------------------------------------------------


def fetch_osm(feature, bbox, feedback=None, timeout=90, custom_filter=None):
    """Query Overpass for a preset feature inside ``bbox``.  Off-thread.

    ``bbox`` is (west, south, east, north); Overpass wants south,west,north,east.
    """
    if custom_filter:
        tag_filter, element_types = custom_filter, "node,way,relation"
    else:
        preset = catalog.OSM_PRESETS.get(feature)
        if preset is None:
            raise LoaderError(
                "Unknown OSM feature '{0}'. Available: {1}".format(
                    feature, ", ".join(sorted(catalog.OSM_PRESETS))
                )
            )
        tag_filter, element_types = preset

    west, south, east, north = bbox
    box = "{0},{1},{2},{3}".format(south, west, north, east)

    areal = element_types != "node" and feature not in ("road", "river", "power_line")
    out_mode = "geom" if areal else "center"

    parts = []
    for element in element_types.split(","):
        parts.append("{0}{1}({2});".format(element, tag_filter, box))
    query = "[out:json][timeout:{0}];\n({1});\nout {2};".format(
        int(timeout), "".join(parts), out_mode
    )

    last_error = None
    # Overpass regularly needs longer than the 60 s QGIS allows by default.
    # The server-side [timeout:] above and this ceiling have to agree, or the
    # request is cut off before the server has finished thinking.
    with net.extended_timeout(int(timeout) * 1000 + 60000):
        for endpoint in catalog.OVERPASS_ENDPOINTS:
            try:
                data = net.post_form(endpoint, {"data": query}, feedback=feedback).json()
                return {"query": query, "endpoint": endpoint, "data": data, "feature": feature}
            except Exception as exc:  # try the next mirror
                last_error = exc
    raise LoaderError(
        "Every Overpass mirror failed. Last error: {0}\n"
        "Overpass is a shared free service and throttles heavy users; a 429 or "
        "503 here usually means wait a minute, not that the query is wrong.\n"
        "Query was:\n{1}".format(last_error, query)
    )


def fetch_osm_admin(level, bbox, feedback=None):
    """Fetch administrative boundaries at an Indian admin level.  Off-thread."""
    admin_level = catalog.OSM_ADMIN_LEVELS.get(level)
    if admin_level is None:
        raise LoaderError(
            "Unknown admin level '{0}'. Available: {1}".format(
                level, ", ".join(catalog.OSM_ADMIN_LEVELS)
            )
        )
    return fetch_osm(
        "admin_" + level,
        bbox,
        feedback=feedback,
        custom_filter='["boundary"="administrative"]["admin_level"="{0}"]'.format(admin_level),
    )


def build_osm_layer(payload, name=None):
    """Convert an Overpass response into a layer.  GUI thread."""
    data = payload["data"]
    elements = data.get("elements") or []
    if not elements:
        raise LoaderError(
            "OpenStreetMap returned no features for that area. Try a larger "
            "extent, or a different feature type."
        )

    features = []
    dropped_relations = 0
    for element in elements:
        geometry = _osm_geometry(element)
        if geometry is None:
            if element.get("type") == "relation":
                dropped_relations += 1
            continue
        props = dict(element.get("tags") or {})
        props["osm_id"] = element.get("id")
        props["osm_type"] = element.get("type")
        features.append({"type": "Feature", "geometry": geometry, "properties": props})

    if not features:
        raise LoaderError("Overpass returned elements but none had usable geometry.")

    collection = {"type": "FeatureCollection", "features": features}
    path = os.path.join(_cache_dir(), "osm_{0}.geojson".format(_safe(payload["feature"])))
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(collection, handle, ensure_ascii=False)

    layer_name = name or "OSM {0}".format(payload["feature"].replace("_", " "))
    layer = QgsVectorLayer(path, layer_name, "ogr")
    if not layer.isValid():
        raise LoaderError("Could not build a layer from the Overpass response.")

    note = None
    if dropped_relations:
        note = (
            "{0} multipolygon relations were skipped -- this version builds "
            "geometry from nodes and ways only.".format(dropped_relations)
        )
    code = (
        '# Overpass query:\n# {q}\n'
        '{{var}} = QgsVectorLayer({path!r}, {name!r}, "ogr")\n'
        'project.addMapLayer({{var}})'
    ).format(q=payload["query"].replace("\n", "\n# "), path=path, name=layer_name)
    return layer, code, note


_AREA_TAGS = ("building", "landuse", "leisure", "natural", "amenity", "boundary")


def _osm_geometry(element):
    kind = element.get("type")
    if kind == "node" and element.get("lat") is not None:
        return {"type": "Point", "coordinates": [element["lon"], element["lat"]]}

    if "center" in element and element["center"].get("lat") is not None:
        return {
            "type": "Point",
            "coordinates": [element["center"]["lon"], element["center"]["lat"]],
        }

    geom = element.get("geometry")
    if geom:
        coords = [[p["lon"], p["lat"]] for p in geom if p.get("lat") is not None]
        if len(coords) < 2:
            return None
        closed = len(coords) >= 4 and coords[0] == coords[-1]
        tags = element.get("tags") or {}
        if closed and any(tag in tags for tag in _AREA_TAGS):
            return {"type": "Polygon", "coordinates": [coords]}
        return {"type": "LineString", "coordinates": coords}
    return None


# ---------------------------------------------------------------------------
# Weather (Open-Meteo, no key)
# ---------------------------------------------------------------------------


def fetch_weather(lat, lon, days=3, feedback=None):
    """Forecast plus modelled air quality for a point.  Off-thread."""
    from urllib.parse import urlencode

    forecast_url = catalog.OPEN_METEO_FORECAST + "?" + urlencode(
        {
            "latitude": "{0:.4f}".format(float(lat)),
            "longitude": "{0:.4f}".format(float(lon)),
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
            "current": "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m",
            "timezone": "Asia/Kolkata",
            "forecast_days": str(int(days)),
        }
    )
    air_url = catalog.OPEN_METEO_AIR + "?" + urlencode(
        {
            "latitude": "{0:.4f}".format(float(lat)),
            "longitude": "{0:.4f}".format(float(lon)),
            "current": "pm2_5,pm10,us_aqi",
            "timezone": "Asia/Kolkata",
        }
    )
    result = {"forecast": net.get_json(forecast_url, feedback=feedback)}
    try:
        result["air_quality_modelled"] = net.get_json(air_url, feedback=feedback)
        result["air_quality_note"] = (
            "This air quality is modelled, not a CPCB station reading. For real "
            "station measurements use the CPCB resource on data.gov.in."
        )
    except Exception:
        result["air_quality_modelled"] = None
    return result
