# -*- coding: utf-8 -*-
"""The tool registry.

The safety model, which is the point of this plugin:

* The agent **cannot execute generated Python.** There is no ``exec`` here and
  no code-execution tool. Everything it can do is one of the declared tools
  below, with a JSON schema the model must satisfy.
* Processing calls are validated against the live algorithm registry -- the
  algorithm must exist, and every parameter name must be one the algorithm
  actually declares -- before anything runs.
* Tools are tiered. ``SAFE`` tools read or add layers and run without asking.
  ``WRITE`` tools touch the user's disk or destroy project state, and are
  confirmed unless the user turns that off.

Each tool is split into an optional off-thread ``fetch`` and a GUI-thread
``apply``, so a slow download never freezes QGIS.
"""

import json
import os

from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsLayoutExporter,
    QgsLayoutItemLabel,
    QgsLayoutItemLegend,
    QgsLayoutItemMap,
    QgsLayoutItemScaleBar,
    QgsLayoutPoint,
    QgsLayoutSize,
    QgsPrintLayout,
    QgsProject,
    QgsRectangle,
    QgsVectorFileWriter,
    QgsVectorLayer,
)

from ..core import provenance
from ..core.compat import (
    EXPORT_SUCCESS,
    GRADUATED_QUANTILE,
    LAYOUT_MM,
    WRITER_NO_ERROR,
)
from ..india import catalog, loaders, places

SAFE = "safe"
WRITE = "write"


def _record_layer(
    ctx,
    tool_name,
    layer,
    code_template,
    comment,
    source=None,
    source_url=None,
    abstract=None,
):
    """Record a step that created ``layer``, naming it in the exported script.

    ``code_template`` carries a literal ``{var}`` placeholder.  We substitute by
    replace() rather than str.format() so that braces occurring anywhere else in
    the snippet -- a filter expression, an Overpass query -- are left alone.

    ``source`` is a key into :mod:`..core.provenance`.  Passing it writes the
    publisher, licence, citation and retrieval date into the layer's own
    metadata, so the answer to "where did this come from" travels with the
    project rather than living in somebody's memory.
    """
    variable = ctx.journal.alias(layer.id(), layer.name())
    code = code_template.replace("{var}", variable)
    if source:
        record = provenance.describe(
            layer, source, source_url=source_url, abstract=abstract
        )
        # The exported script attaches the same metadata, so a replayed session
        # produces layers that can still say where they came from.
        code += (
            "\n_describe({var}, {title!r}, {org!r}, {licence!r},\n"
            "          {citation!r},\n"
            "          {url!r}, {retrieved!r})".format(
                var=variable,
                title=record["source"],
                org=record["organisation"],
                licence=record["licence"],
                citation=record["citation"],
                url=record["url"],
                retrieved=record["retrieved"][:10],
            )
        )
    ctx.journal.add_step(tool_name, code, comment)
    return variable


class ToolError(Exception):
    """A tool failed in a way the model should see and can recover from."""


class Context:
    """Everything a tool is allowed to touch."""

    def __init__(self, iface, journal):
        self.iface = iface
        self.journal = journal
        self.notes = []

    @property
    def project(self):
        return QgsProject.instance()

    def note(self, text):
        if text:
            self.notes.append(text)

    def add_layer(self, layer):
        self.project.addMapLayer(layer)
        return layer

    def find_layer(self, reference):
        """Resolve a layer by id, exact name, or unambiguous partial name."""
        if not reference:
            raise ToolError("No layer was named. Call list_layers to see what is loaded.")
        reference = str(reference).strip()
        layer = self.project.mapLayer(reference)
        if layer is not None:
            return layer

        layers = list(self.project.mapLayers().values())
        exact = [lyr for lyr in layers if lyr.name() == reference]
        if len(exact) == 1:
            return exact[0]
        lowered = reference.lower()
        partial = [lyr for lyr in layers if lowered in lyr.name().lower()]
        if len(partial) == 1:
            return partial[0]
        if not partial:
            raise ToolError(
                "No layer matches {0!r}. Loaded layers: {1}".format(
                    reference, ", ".join(lyr.name() for lyr in layers) or "(none)"
                )
            )
        raise ToolError(
            "{0!r} matches more than one layer ({1}). Use the exact name.".format(
                reference, ", ".join(lyr.name() for lyr in partial)
            )
        )


class Tool:
    def __init__(self, name, description, parameters, apply, fetch=None, tier=SAFE):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.apply = apply
        self.fetch = fetch
        self.tier = tier

    def schema(self):
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


REGISTRY = {}


def register(tool):
    REGISTRY[tool.name] = tool
    return tool


def schemas():
    return [tool.schema() for tool in REGISTRY.values()]


def get(name):
    tool = REGISTRY.get(name)
    if tool is None:
        raise ToolError(
            "There is no tool called {0!r}. Available tools: {1}".format(
                name, ", ".join(sorted(REGISTRY))
            )
        )
    return tool


def _obj(properties, required=None):
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
    }


def _str(description, enum=None):
    schema = {"type": "string", "description": description}
    if enum:
        schema["enum"] = list(enum)
    return schema


def _int(description, default=None):
    schema = {"type": "integer", "description": description}
    if default is not None:
        schema["default"] = default
    return schema


# ===========================================================================
# Discovery
# ===========================================================================


def _t_search_india_data(args, ctx, payload=None):
    query = args.get("query", "")
    results = catalog.search(query, limit=int(args.get("limit", 8) or 8))
    if not results:
        return {
            "results": [],
            "hint": (
                "Nothing in the built-in catalogue matched. Try search_bhuvan_layers "
                "for the full 7800-layer Bhuvan list, or add_osm_features for "
                "OpenStreetMap data."
            ),
        }
    return {"results": results}


register(
    Tool(
        "search_india_data",
        "Search the built-in catalogue of Indian geospatial data (ISRO Bhuvan layers, "
        "data.gov.in datasets, Census boundaries, OpenStreetMap presets). Always call "
        "this first when the user asks for Indian data, so that you work from real "
        "layer names and resource ids rather than guessing.",
        _obj(
            {
                "query": _str("What the user is looking for, e.g. 'district rainfall'."),
                "limit": _int("Maximum results.", 8),
            },
            ["query"],
        ),
        _t_search_india_data,
    )
)


def _t_resolve_place(args, ctx, payload=None):
    name = args.get("name", "")
    place = payload if isinstance(payload, places.Place) else places.lookup(name)
    if place is None:
        raise ToolError(
            "Could not resolve the place {0!r} in India. Try a district or city "
            "name, or give a bounding box directly.".format(name)
        )
    result = place.as_dict()
    if place.kind == "state" and places.normalise(place.canonical) == "telangana":
        result["vintage_note"] = (
            "Two district vintages exist. add_boundary level='district' is the "
            "current 760-district set and has Telangana's own 34 districts; "
            "level='district_datameet' is the Census 2011 snapshot, which "
            "predates the 2014 bifurcation and files them under 'Andhra "
            "Pradesh'. add_boundary picks correctly either way -- do not "
            "substitute a state name yourself."
        )
    return result


def _f_resolve_place(args, feedback=None):
    return places.resolve(args.get("name", ""), feedback=feedback)


register(
    Tool(
        "resolve_place",
        "Resolve an Indian place name to a bounding box. Handles renamed cities "
        "(Bangalore/Bengaluru, Allahabad/Prayagraj, Banaras/Varanasi) and state "
        "abbreviations. Use this before any tool that needs a place or extent.",
        _obj({"name": _str("An Indian place name, in any common spelling.")}, ["name"]),
        _t_resolve_place,
        fetch=_f_resolve_place,
    )
)


def _f_search_bhuvan(args, feedback=None):
    return loaders.fetch_bhuvan_layer_names(
        args.get("host", "vec1"), args.get("query", ""), feedback=feedback
    )


def _t_search_bhuvan(args, ctx, payload=None):
    return {
        "host": payload["host"],
        "total_layers_on_host": payload["count"],
        "matches": payload["layers"],
        "workspaces": catalog.BHUVAN_WORKSPACES,
    }


register(
    Tool(
        "search_bhuvan_layers",
        "Search the full ISRO Bhuvan WMS layer list by name. Slow -- the "
        "capabilities document is 7-10 MB, so it is cached after the first call. "
        "Prefer search_india_data unless the user needs something outside the "
        "curated shortlist.",
        _obj(
            {
                "query": _str("Text to match against layer names and titles."),
                "host": _str("Bhuvan host to search.", ["vec1", "vec3"]),
            },
            ["query"],
        ),
        _t_search_bhuvan,
        fetch=_f_search_bhuvan,
    )
)


# ===========================================================================
# Adding data
# ===========================================================================


def _f_add_bhuvan_layer(args, feedback=None):
    """Check the layer has data, and line up a substitute if it does not.

    Bhuvan serves some layers that are valid and carry no features. Rather than
    hand back a blank map, this looks the layer over first and, where the
    catalogue knows an equivalent source, fetches that in the same step so the
    request is answered with data either way.
    """
    layer_name = args.get("layer")
    if not layer_name:
        return None
    entry = catalog.find_bhuvan_layer(layer_name) or {}
    host = args.get("host") or entry.get("host") or "vec1"
    if host == "tilecache":
        return {"verdict": "skipped"}

    bbox = None
    state = entry.get("state")
    if state:
        place = places.lookup(state)
        if place is not None:
            bbox = place.bbox

    probe = loaders.probe_bhuvan_layer(layer_name, host, bbox, feedback=feedback)

    if probe.get("verdict") == "empty" and bbox and entry.get("family"):
        alternative = catalog.bhuvan_layers.alternative_for(entry["family"])
        if alternative:
            try:
                probe["substitute"] = loaders.fetch_osm(
                    alternative["osm_preset"], bbox, feedback=feedback
                )
                probe["substitute_label"] = alternative["label"]
                probe["substitute_state"] = state
            except Exception:
                probe["substitute"] = None
    return probe


def _t_add_bhuvan_layer(args, ctx, payload=None):
    layer_name = args.get("layer")
    if not layer_name:
        raise ToolError("'layer' is required, e.g. 'basemap:AP_LULC' or 'bhuvan_imagery'.")

    entry = catalog.find_bhuvan_layer(layer_name)
    host = args.get("host") or (entry or {}).get("host") or "vec1"
    title = args.get("name") or (entry or {}).get("title") or layer_name

    probe = payload if isinstance(payload, dict) else {}
    verdict = probe.get("verdict")

    # Bhuvan will happily serve a layer that has nothing on it, or abort a
    # render that takes its server too long. Both produce a perfectly valid
    # QGIS layer over a blank canvas, so say so rather than let the user think
    # they mistyped something.
    if verdict == "too_slow":
        raise ToolError(
            "{0} could not be drawn over that extent. {1} Zoom to a district "
            "and try again, or pick a layer that is not a per-district "
            "group.".format(layer_name, probe.get("detail", ""))
        )

    layer, code = loaders.build_bhuvan_wms_layer(layer_name, host, title)
    ctx.add_layer(layer)
    _record_layer(
        ctx,
        "add_bhuvan_layer",
        layer,
        code,
        "Bhuvan WMS layer " + layer_name,
        source="bhuvan",
        source_url=(
            catalog.BHUVAN_TILECACHE
            if host == "tilecache"
            else catalog.bhuvan_host_url(host)
        ),
        abstract="Bhuvan WMS layer {0} served from the {1} endpoint.".format(
            layer_name, host
        ),
    )

    result = {
        "added": layer.name(),
        "layer_id": layer.id(),
        "type": "raster (WMS)",
        "source": "ISRO Bhuvan {0}".format(host),
        "coverage_check": verdict or "not run",
    }

    # Bhuvan publishes this layer without features. Deliver the equivalent data
    # from a source that has it, so the request is answered with data. The
    # substitution is best-effort by design: if it does not come through, the
    # user still gets a clear next step rather than a failure.
    substituted = False
    if verdict == "empty" and probe.get("substitute"):
        state = probe.get("substitute_state") or ""
        title = "{0} - {1}".format(state, probe.get("substitute_label", "OpenStreetMap"))
        try:
            substitute, code, osm_note = loaders.build_osm_layer(probe["substitute"], title)
            ctx.add_layer(substitute)
            _record_layer(
                ctx,
                "add_bhuvan_layer",
                substitute,
                code,
                title,
                source="openstreetmap",
                abstract="{0}, retrieved through the Overpass API.".format(title),
            )
            ctx.note(osm_note)
            message = (
                "ISRO publishes {0} without features for this area, so {1} were "
                "loaded instead: {2} features. Name the source you used when you "
                "report back.".format(layer_name, probe.get("substitute_label"),
                                      substitute.featureCount())
            )
            ctx.note(message)
            result["substitute_layer"] = substitute.name()
            result["substitute_features"] = substitute.featureCount()
            result["note"] = message
            substituted = True
        except Exception:
            substituted = False

    if verdict == "empty" and not substituted:
        message = (
            "ISRO publishes {0} without features for this area. Offer the user "
            "an equivalent straight away: OpenStreetMap through "
            "add_osm_features over a city or district extent, or the Census "
            "boundary sets through add_boundary.".format(layer_name)
        )
        ctx.note(message)
        result["note"] = message

    return result


register(
    Tool(
        "add_bhuvan_layer",
        "Add an ISRO Bhuvan WMS layer to the project. Layer names are case "
        "sensitive and namespaced, e.g. 'basemap:AP_LULC', 'hydrology:BASIN'. "
        "The layer is probed first: Bhuvan serves plenty of layers that are "
        "valid but empty, and the result tells you whether anything actually "
        "drew. If it says the layer is empty, pass that on to the user rather "
        "than leaving them looking at a blank map. "
        "Use 'bhuvan_imagery' with host='tilecache' for satellite imagery. "
        "The first Bhuvan layer in a session can take up to a minute because "
        "their capabilities document is large.",
        _obj(
            {
                "layer": _str("Bhuvan layer name, namespaced."),
                "host": _str("Which Bhuvan host.", ["vec1", "vec3", "tilecache"]),
                "name": _str("Display name for the layer in QGIS."),
            },
            ["layer"],
        ),
        _t_add_bhuvan_layer,
        fetch=_f_add_bhuvan_layer,
    )
)


def _f_add_boundary(args, feedback=None):
    return loaders.fetch_boundary(args.get("level", "district"), feedback=feedback)


#: Each boundary set has its own compiler and its own terms, so each is
#: credited to the body that actually published the file rather than to the
#: census it ultimately derives from.
BOUNDARY_CREDIT = {
    "district": "district_current",
    "district_datameet": "census",
    "state": "state_boundaries",
    "parliamentary": "parliamentary_boundaries",
    "country": "survey_of_india",
    "country_osm": "openstreetmap",
}


def _boundary_source(level, entry):
    """Which publisher a boundary set should be credited to."""
    if level in BOUNDARY_CREDIT:
        return BOUNDARY_CREDIT[level]
    return "survey_of_india" if entry.get("official_boundary") else "census"


def _t_add_boundary(args, ctx, payload=None):
    layer, code, note = loaders.build_boundary_layer(
        payload,
        state=args.get("state"),
        district=args.get("district"),
        name=args.get("name"),
    )
    ctx.add_layer(layer)
    ctx.note(note)
    level = args.get("level", "district")
    entry = catalog.BOUNDARY_SOURCES.get(level, {})
    _record_layer(
        ctx,
        "add_boundary",
        layer,
        code,
        "Boundary layer: " + layer.name(),
        source=_boundary_source(level, entry),
        source_url=entry.get("url"),
        abstract=entry.get("title") or ("India {0} boundaries".format(level)),
    )
    return {
        "added": layer.name(),
        "layer_id": layer.id(),
        "feature_count": layer.featureCount(),
        "fields": [f.name() for f in layer.fields()],
        "note": note,
    }


register(
    Tool(
        "add_boundary",
        "Add Indian administrative boundaries: districts (Census 2011, 641), "
        "states, parliamentary constituencies, or the national outline. Can be "
        "filtered to one state or district. level='district' is the current 760-district "
        "set including Telangana and Ladakh; level='district_datameet' is the 641-district "
        "Census 2011 snapshot, which predates the 2014 bifurcation -- asking that one for "
        "Telangana still works, because the tool detects the older file and selects those "
        "districts by name. Use level='country' for the Survey of "
        "India national outline, which is the standard for a published map of "
        "India; the other sets are community or GADM-derived and are for "
        "analysis. Pass any note in the result on to the user.",
        _obj(
            {
                "level": _str(
                    "Which boundary set.",
                    [
                        "district",
                        "district_datameet",
                        "state",
                        "parliamentary",
                        "country",
                        "country_osm",
                    ],
                ),
                "state": _str("Optional: keep only features in this state."),
                "district": _str("Optional: keep only this district."),
                "name": _str("Display name for the layer."),
            },
            ["level"],
        ),
        _t_add_boundary,
        fetch=_f_add_boundary,
    )
)


def _f_add_datagov(args, feedback=None):
    filters = args.get("filters") or {}
    if isinstance(filters, str):
        try:
            filters = json.loads(filters)
        except ValueError:
            filters = {}
    return loaders.fetch_datagov(
        args["resource_id"], filters, int(args.get("limit", 500) or 500), feedback=feedback
    )


def _t_add_datagov(args, ctx, payload=None):
    layer, code, note = loaders.build_datagov_layer(payload, args.get("name"))
    ctx.add_layer(layer)
    ctx.note(note)
    meta = catalog.find_datagov_resource(args["resource_id"]) or {}
    _record_layer(
        ctx,
        "add_datagov_layer",
        layer,
        code,
        "data.gov.in: " + layer.name(),
        source="datagov",
        source_url="https://data.gov.in/resource/{0}".format(args["resource_id"]),
        abstract=meta.get("title") or layer.name(),
    )
    return {
        "added": layer.name(),
        "layer_id": layer.id(),
        "feature_count": layer.featureCount(),
        "fields": [f.name() for f in layer.fields()],
        "source_notes": meta.get("notes"),
        "note": note,
    }


register(
    Tool(
        "add_datagov_layer",
        "Fetch a data.gov.in resource and add it to the project, as a point layer "
        "if the records carry coordinates or an attribute table otherwise. Get the "
        "resource_id from search_india_data. Filter values are case sensitive.",
        _obj(
            {
                "resource_id": _str("data.gov.in resource UUID."),
                "filters": {
                    "type": "object",
                    "description": "Field/value pairs, e.g. {\"city\": \"Delhi\", \"pollutant_id\": \"PM2.5\"}.",
                    "additionalProperties": {"type": "string"},
                },
                "limit": _int("Maximum records to fetch.", 500),
                "name": _str("Display name for the layer."),
            },
            ["resource_id"],
        ),
        _t_add_datagov,
        fetch=_f_add_datagov,
    )
)


def _bbox_from_args(args, feedback=None):
    if args.get("bbox"):
        parts = args["bbox"]
        if isinstance(parts, str):
            parts = [p.strip() for p in parts.split(",")]
        if len(parts) != 4:
            raise ToolError("bbox must be four numbers: west, south, east, north.")
        return tuple(float(p) for p in parts), None
    place = places.resolve(args.get("place", ""), feedback=feedback)
    if place is None:
        raise ToolError(
            "Could not resolve the place {0!r}. Give a bbox instead, or try a "
            "different spelling.".format(args.get("place"))
        )
    return place.bbox, place


def _f_add_osm(args, feedback=None):
    bbox, place = _bbox_from_args(args, feedback)
    payload = loaders.fetch_osm(args["feature"], bbox, feedback=feedback)
    payload["place"] = place.as_dict() if place else None
    return payload


def _t_add_osm(args, ctx, payload=None):
    name = args.get("name")
    if not name and payload.get("place"):
        name = "{0} - {1}".format(
            payload["place"]["canonical"], args["feature"].replace("_", " ")
        )
    layer, code, note = loaders.build_osm_layer(payload, name)
    ctx.add_layer(layer)
    ctx.note(note)
    _record_layer(
        ctx,
        "add_osm_features",
        layer,
        code,
        "OpenStreetMap: " + layer.name(),
        source="openstreetmap",
        source_url=payload.get("endpoint"),
        abstract="OpenStreetMap {0}, retrieved through the Overpass API.".format(
            args["feature"].replace("_", " ")
        ),
    )
    return {
        "added": layer.name(),
        "layer_id": layer.id(),
        "feature_count": layer.featureCount(),
        "geometry": layer.geometryType(),
        "endpoint": payload["endpoint"],
        "note": note,
    }


register(
    Tool(
        "add_osm_features",
        "Fetch OpenStreetMap features for an Indian place and add them as a layer. "
        "Good for hospitals, schools, roads, rivers, buildings and other points of "
        "interest that no government feed publishes cleanly.",
        _obj(
            {
                "feature": _str(
                    "Feature preset.", sorted(catalog.OSM_PRESETS)
                ),
                "place": _str("Indian place name to search within."),
                "bbox": _str("Alternative to place: 'west,south,east,north' in EPSG:4326."),
                "name": _str("Display name for the layer."),
            },
            ["feature"],
        ),
        _t_add_osm,
        fetch=_f_add_osm,
    )
)


def _f_get_weather(args, feedback=None):
    bbox, place = _bbox_from_args(args, feedback)
    west, south, east, north = bbox
    lat, lon = (south + north) / 2.0, (west + east) / 2.0
    data = loaders.fetch_weather(lat, lon, int(args.get("days", 3) or 3), feedback=feedback)
    data["place"] = place.as_dict() if place else {"bbox": list(bbox)}
    return data


def _t_get_weather(args, ctx, payload=None):
    return payload


register(
    Tool(
        "get_weather",
        "Current conditions, a short forecast and modelled air quality for an "
        "Indian place. Note that the air quality here is modelled, not a CPCB "
        "station reading -- for real station data use add_datagov_layer with the "
        "CPCB resource.",
        _obj(
            {
                "place": _str("Indian place name."),
                "bbox": _str("Alternative: 'west,south,east,north'."),
                "days": _int("Forecast days.", 3),
            },
        ),
        _t_get_weather,
        fetch=_f_get_weather,
    )
)


# ===========================================================================
# Project inspection
# ===========================================================================


def _t_list_layers(args, ctx, payload=None):
    out = []
    for layer in ctx.project.mapLayers().values():
        entry = {
            "name": layer.name(),
            "id": layer.id(),
            "type": "vector" if isinstance(layer, QgsVectorLayer) else "raster",
            "crs": layer.crs().authid(),
            "valid": layer.isValid(),
        }
        if isinstance(layer, QgsVectorLayer):
            entry["feature_count"] = layer.featureCount()
            entry["fields"] = [f.name() for f in layer.fields()]
            entry["geometry_type"] = ["point", "line", "polygon", "unknown", "null"][
                min(layer.geometryType(), 4)
            ]
            if layer.subsetString():
                entry["filter"] = layer.subsetString()
        out.append(entry)
    return {"layers": out, "count": len(out)}


register(
    Tool(
        "list_layers",
        "List the layers currently in the QGIS project, with their fields, feature "
        "counts and CRS. Call this before any tool that operates on an existing layer.",
        _obj({}),
        _t_list_layers,
    )
)


def _t_layer_info(args, ctx, payload=None):
    layer = ctx.find_layer(args.get("layer"))
    extent = layer.extent()
    info = {
        "name": layer.name(),
        "id": layer.id(),
        "crs": layer.crs().authid(),
        "extent": [extent.xMinimum(), extent.yMinimum(), extent.xMaximum(), extent.yMaximum()],
        "source": layer.publicSource()[:400],
    }
    if isinstance(layer, QgsVectorLayer):
        info["feature_count"] = layer.featureCount()
        info["fields"] = [
            {"name": f.name(), "type": f.typeName()} for f in layer.fields()
        ]
        sample_field = args.get("sample_field")
        if sample_field:
            index = layer.fields().indexOf(sample_field)
            if index < 0:
                raise ToolError(
                    "Field {0!r} not found. Fields: {1}".format(
                        sample_field, ", ".join(f.name() for f in layer.fields())
                    )
                )
            values = sorted({str(v) for v in layer.uniqueValues(index, 40)})
            info["unique_values"] = values
    credit = provenance.summarise(layer)
    if credit:
        info["provenance"] = credit
    return info


register(
    Tool(
        "layer_info",
        "Inspect one layer: CRS, extent, fields, and optionally the distinct values "
        "of a field. Use this to learn the exact spelling of names before filtering.",
        _obj(
            {
                "layer": _str("Layer name or id."),
                "sample_field": _str("Optional: list up to 40 distinct values of this field."),
            },
            ["layer"],
        ),
        _t_layer_info,
    )
)


def _t_zoom_to(args, ctx, payload=None):
    canvas = ctx.iface.mapCanvas() if ctx.iface else None
    if canvas is None:
        raise ToolError("No map canvas is available.")

    if args.get("layer"):
        layer = ctx.find_layer(args["layer"])
        extent = layer.extent()
        source_crs = layer.crs()
    else:
        bbox, place = _bbox_from_args(args, None)
        west, south, east, north = bbox
        extent = QgsRectangle(west, south, east, north)
        source_crs = QgsCoordinateReferenceSystem("EPSG:4326")

    target = canvas.mapSettings().destinationCrs()
    if source_crs.isValid() and target.isValid() and source_crs != target:
        transform = QgsCoordinateTransform(source_crs, target, ctx.project)
        extent = transform.transformBoundingBox(extent)

    extent.scale(1.05)
    canvas.setExtent(extent)
    canvas.refresh()
    ctx.journal.add_step(
        "zoom_to",
        "iface.mapCanvas().setExtent(QgsRectangle({0}, {1}, {2}, {3}))\n"
        "iface.mapCanvas().refresh()".format(
            extent.xMinimum(), extent.yMinimum(), extent.xMaximum(), extent.yMaximum()
        ),
        "Zoom the canvas",
    )
    return {
        "extent": [
            extent.xMinimum(),
            extent.yMinimum(),
            extent.xMaximum(),
            extent.yMaximum(),
        ],
        "crs": target.authid(),
    }


register(
    Tool(
        "zoom_to",
        "Zoom the map canvas to a place name, a bounding box, or a loaded layer.",
        _obj(
            {
                "place": _str("Indian place name."),
                "layer": _str("Layer name or id to zoom to."),
                "bbox": _str("'west,south,east,north' in EPSG:4326."),
            }
        ),
        _t_zoom_to,
    )
)


# ===========================================================================
# Processing
# ===========================================================================


def _algorithm(algorithm_id):
    algorithm = QgsApplication.processingRegistry().algorithmById(algorithm_id)
    if algorithm is None:
        raise ToolError(
            "No Processing algorithm with id {0!r}. Use list_processing_algorithms "
            "to find the right id -- they look like 'native:buffer' or "
            "'qgis:joinattributestable'.".format(algorithm_id)
        )
    return algorithm


def _t_list_algorithms(args, ctx, payload=None):
    query = (args.get("query") or "").lower().strip()
    limit = int(args.get("limit", 25) or 25)
    found = []
    for algorithm in QgsApplication.processingRegistry().algorithms():
        haystack = "{0} {1} {2}".format(
            algorithm.id(), algorithm.displayName(), " ".join(algorithm.tags())
        ).lower()
        if query and query not in haystack:
            continue
        found.append({"id": algorithm.id(), "name": algorithm.displayName()})
        if len(found) >= limit:
            break
    if not found:
        raise ToolError(
            "No Processing algorithm matched {0!r}. Try a simpler word such as "
            "'buffer', 'clip', 'join', 'intersect', 'dissolve', 'centroid'.".format(query)
        )
    return {"algorithms": found, "count": len(found)}


register(
    Tool(
        "list_processing_algorithms",
        "Search the QGIS Processing toolbox for algorithms by keyword. Returns the "
        "algorithm ids you need for run_processing.",
        _obj(
            {
                "query": _str("Keyword, e.g. 'buffer', 'clip', 'zonal statistics'."),
                "limit": _int("Maximum results.", 25),
            },
            ["query"],
        ),
        _t_list_algorithms,
    )
)


def _is_optional(definition):
    """Whether a Processing parameter is optional.

    QGIS 4 moved ``QgsProcessingParameterDefinition.Flag`` to
    ``Qgis.ProcessingParameterFlag``, so try the modern spelling first and fall
    back to the 3.x one.  Returns None if neither is available rather than
    guessing -- the model can still read the description.
    """
    try:
        flags = definition.flags()
    except Exception:
        return None

    from qgis.core import Qgis

    holder = getattr(Qgis, "ProcessingParameterFlag", None)
    optional = getattr(holder, "Optional", None) if holder is not None else None
    if optional is None:
        optional = getattr(definition, "FlagOptional", None)
    if optional is None:
        return None
    try:
        return bool(flags & optional)
    except TypeError:
        return None


def _t_algorithm_help(args, ctx, payload=None):
    algorithm = _algorithm(args["algorithm_id"])
    parameters = []
    for definition in algorithm.parameterDefinitions():
        parameters.append(
            {
                "name": definition.name(),
                "type": definition.type(),
                "description": definition.description(),
                "optional": _is_optional(definition),
                "default": _jsonable(definition.defaultValue()),
            }
        )
    return {
        "id": algorithm.id(),
        "name": algorithm.displayName(),
        "group": algorithm.group(),
        "parameters": parameters,
        "outputs": [o.name() for o in algorithm.outputDefinitions()],
    }


register(
    Tool(
        "algorithm_help",
        "Show the exact parameter names, types and defaults for a Processing "
        "algorithm. Always call this before run_processing on an algorithm you have "
        "not used in this session -- parameter names are validated strictly.",
        _obj({"algorithm_id": _str("e.g. 'native:buffer'.")}, ["algorithm_id"]),
        _t_algorithm_help,
    )
)


def _t_run_processing(args, ctx, payload=None):
    from qgis import processing

    algorithm_id = args["algorithm_id"]
    algorithm = _algorithm(algorithm_id)
    parameters = args.get("parameters") or {}
    if isinstance(parameters, str):
        try:
            parameters = json.loads(parameters)
        except ValueError:
            raise ToolError("'parameters' was a string that is not valid JSON.")

    declared = {d.name() for d in algorithm.parameterDefinitions()}
    unknown = sorted(set(parameters) - declared)
    if unknown:
        raise ToolError(
            "Algorithm {0} has no parameter(s) {1}. Its parameters are: {2}. "
            "Call algorithm_help first.".format(
                algorithm_id, ", ".join(unknown), ", ".join(sorted(declared))
            )
        )

    resolved = {}
    for key, value in parameters.items():
        resolved[key] = _resolve_parameter(ctx, key, value)

    if "OUTPUT" in declared and "OUTPUT" not in resolved:
        resolved["OUTPUT"] = "TEMPORARY_OUTPUT"

    try:
        result = processing.run(algorithm_id, resolved)
    except Exception as exc:
        raise ToolError(
            "Processing algorithm {0} failed: {1}\nParameters used: {2}".format(
                algorithm_id, exc, json.dumps(_jsonable(resolved))[:800]
            )
        )

    loaded = []
    if args.get("load_output", True):
        for key, value in result.items():
            layer = _layer_from_output(value, "{0} ({1})".format(algorithm.displayName(), key))
            if layer is not None:
                ctx.add_layer(layer)
                record = provenance.describe(
                    layer,
                    "derived",
                    abstract="Produced in QGIS by {0} ({1}).".format(
                        algorithm.displayName(), algorithm_id
                    ),
                )
                loaded.append(
                    {"name": layer.name(), "id": layer.id(), "key": key, "record": record}
                )

    lines = ["result = processing.run({0!r}, {1})".format(algorithm_id, _repr_params(ctx, resolved))]
    for key, value in result.items():
        for entry in loaded:
            if entry.get("key") != key:
                continue
            variable = ctx.journal.alias(entry["id"], entry["name"])
            lines.append("{0} = result[{1!r}]".format(variable, key))
            lines.append("project.addMapLayer({0})".format(variable))
            record = entry["record"]
            lines.append(
                "_describe({var}, {title!r}, {org!r}, {licence!r}, '',\n"
                "          '', {retrieved!r})".format(
                    var=variable,
                    title=record["source"],
                    org=record["organisation"],
                    licence=record["licence"],
                    retrieved=record["retrieved"][:10],
                )
            )
    ctx.journal.add_step(
        "run_processing",
        "\n".join(lines),
        "{0} -> {1}".format(algorithm.displayName(), ", ".join(entry["name"] for entry in loaded) or "no layer"),
    )
    return {
        "algorithm": algorithm_id,
        "result": _jsonable(result),
        "layers_added": [
            {k: v for k, v in entry.items() if k != "record"} for entry in loaded
        ],
    }


def _resolve_parameter(ctx, key, value):
    """Turn layer names in parameters into real layer objects."""
    if isinstance(value, str) and value and os.path.sep not in value:
        if value in ("TEMPORARY_OUTPUT", "memory:"):
            return value
        try:
            return ctx.find_layer(value)
        except ToolError:
            return value
    if isinstance(value, list):
        return [_resolve_parameter(ctx, key, item) for item in value]
    return value


def _layer_from_output(value, fallback_name):
    from qgis.core import QgsMapLayer, QgsRasterLayer

    if isinstance(value, QgsMapLayer):
        return value if value.isValid() else None
    if not isinstance(value, str) or not value:
        return None
    layer = QgsVectorLayer(value, fallback_name, "ogr")
    if layer.isValid():
        return layer
    raster = QgsRasterLayer(value, fallback_name)
    return raster if raster.isValid() else None


def _repr_params(ctx, parameters):
    from qgis.core import QgsMapLayer

    parts = []
    for key, value in parameters.items():
        if isinstance(value, QgsMapLayer):
            parts.append("{0!r}: {1}".format(key, ctx.journal.reference(value)))
        elif isinstance(value, list) and any(isinstance(v, QgsMapLayer) for v in value):
            inner = ", ".join(
                ctx.journal.reference(v) if isinstance(v, QgsMapLayer) else repr(v)
                for v in value
            )
            parts.append("{0!r}: [{1}]".format(key, inner))
        else:
            parts.append("{0!r}: {1!r}".format(key, value))
    return "{" + ", ".join(parts) + "}"


def _jsonable(value):
    from qgis.core import QgsMapLayer

    if isinstance(value, QgsMapLayer):
        return value.name()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


register(
    Tool(
        "run_processing",
        "Run a QGIS Processing algorithm. The algorithm id and every parameter name "
        "are validated against the live registry before anything executes. Layer "
        "names in parameters are resolved to the loaded layers automatically. "
        "Outputs default to temporary layers.",
        _obj(
            {
                "algorithm_id": _str("e.g. 'native:buffer'."),
                "parameters": {
                    "type": "object",
                    "description": "Parameter names exactly as algorithm_help reports them.",
                },
                "load_output": {
                    "type": "boolean",
                    "description": "Add the result to the project.",
                    "default": True,
                },
            },
            ["algorithm_id", "parameters"],
        ),
        _t_run_processing,
        tier=SAFE,
    )
)


# ===========================================================================
# Styling and cartography
# ===========================================================================


def _t_style_layer(args, ctx, payload=None):
    from qgis.core import (
        QgsCategorizedSymbolRenderer,
        QgsGraduatedSymbolRenderer,
        QgsSingleSymbolRenderer,
        QgsSymbol,
    )
    from qgis.PyQt.QtGui import QColor

    layer = ctx.find_layer(args["layer"])
    if not isinstance(layer, QgsVectorLayer):
        raise ToolError("style_layer only works on vector layers.")

    mode = (args.get("mode") or "single").lower()
    field = args.get("field")

    if mode == "single":
        # defaultSymbol returns None for a geometryless layer, and this plugin
        # creates those itself for data.gov.in tables that carry no coordinates.
        symbol = QgsSymbol.defaultSymbol(layer.geometryType())
        if symbol is None:
            raise ToolError(
                "{0!r} has no geometry, so it cannot be styled. Join it to a "
                "boundary layer first.".format(layer.name())
            )
        colour = QColor(args.get("color") or "#1f77b4")
        if not colour.isValid():
            raise ToolError("{0!r} is not a colour QGIS understands.".format(args.get("color")))
        symbol.setColor(colour)
        if args.get("opacity") is not None:
            layer.setOpacity(max(0.0, min(1.0, float(args["opacity"]))))
        # Replace the renderer rather than calling setSymbol on the existing
        # one: setSymbol only exists on QgsSingleSymbolRenderer, so calling it
        # on a layer this tool previously made categorized would raise.
        layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        summary = "single symbol {0}".format(colour.name())
        reference = ctx.journal.reference(layer)
        code = (
            "sym = QgsSymbol.defaultSymbol({0}.geometryType())\n"
            "sym.setColor(QColor({1!r}))\n"
            "{0}.setRenderer(QgsSingleSymbolRenderer(sym))".format(reference, colour.name())
        )
    else:
        if not field:
            raise ToolError("'field' is required for categorized and graduated styling.")
        if layer.fields().indexOf(field) < 0:
            raise ToolError(
                "Field {0!r} not found. Fields: {1}".format(
                    field, ", ".join(f.name() for f in layer.fields())
                )
            )
        if mode == "categorized":
            renderer = QgsCategorizedSymbolRenderer(field, [])
            layer.setRenderer(renderer)
            renderer = layer.renderer()
            from qgis.core import QgsRendererCategory

            index = layer.fields().indexOf(field)
            for value in sorted(layer.uniqueValues(index, 30), key=lambda v: str(v)):
                symbol = QgsSymbol.defaultSymbol(layer.geometryType())
                renderer.addCategory(QgsRendererCategory(value, symbol, str(value)))
            summary = "categorized on {0}".format(field)
        elif mode == "graduated":
            classes = int(args.get("classes", 5) or 5)
            symbol = QgsSymbol.defaultSymbol(layer.geometryType())
            if symbol is None:
                raise ToolError(
                    "{0!r} has no geometry, so it cannot be styled.".format(layer.name())
                )
            # createRenderer's colour ramp argument has no default: omitting it
            # is a TypeError, not a styled layer.
            renderer = QgsGraduatedSymbolRenderer.createRenderer(
                layer,
                field,
                classes,
                GRADUATED_QUANTILE,
                symbol,
                _colour_ramp(args.get("ramp")),
            )
            layer.setRenderer(renderer)
            summary = "graduated on {0} into {1} classes".format(field, classes)
        else:
            raise ToolError("mode must be one of: single, categorized, graduated.")
        code = "# renderer set on {0} ({1})".format(ctx.journal.reference(layer), summary)

    layer.triggerRepaint()
    if ctx.iface:
        ctx.iface.layerTreeView().refreshLayerSymbology(layer.id())
    ctx.journal.add_step("style_layer", code, "Style " + layer.name())
    return {"layer": layer.name(), "style": summary}


def _colour_ramp(name=None):
    """A colour ramp for graduated styling.

    ``QgsStyle.defaultStyle().colorRamp()`` returns None when the user's style
    database does not have the named ramp, so fall back to a gradient we build
    ourselves rather than handing None to a renderer that requires one.
    """
    from qgis.core import QgsGradientColorRamp, QgsStyle
    from qgis.PyQt.QtGui import QColor

    for candidate in (name, "Spectral", "Viridis", "Blues"):
        if not candidate:
            continue
        try:
            ramp = QgsStyle.defaultStyle().colorRamp(candidate)
        except Exception:
            ramp = None
        if ramp is not None:
            return ramp
    return QgsGradientColorRamp(QColor(255, 245, 235), QColor(140, 30, 10))


register(
    Tool(
        "style_layer",
        "Style a vector layer: a single colour, categorized by a field, or graduated "
        "into quantile classes.",
        _obj(
            {
                "layer": _str("Layer name or id."),
                "mode": _str("Styling mode.", ["single", "categorized", "graduated"]),
                "field": _str("Field to style by, for categorized and graduated."),
                "color": _str("Colour for single mode, e.g. '#d62728' or 'darkgreen'."),
                "classes": _int("Number of classes for graduated mode.", 5),
                "ramp": _str("Colour ramp name for graduated mode, e.g. 'Spectral'."),
                "opacity": {"type": "number", "description": "Layer opacity, 0 to 1."},
            },
            ["layer"],
        ),
        _t_style_layer,
    )
)


def _t_create_layout(args, ctx, payload=None):
    title = args.get("title") or "Map"
    project = ctx.project
    manager = project.layoutManager()

    name = title
    counter = 1
    while manager.layoutByName(name) is not None:
        counter += 1
        name = "{0} ({1})".format(title, counter)

    layout = QgsPrintLayout(project)
    layout.initializeDefaults()
    layout.setName(name)

    page = layout.pageCollection().page(0)
    size = (args.get("page_size") or "A4").upper()
    dimensions = {"A4": (297, 210), "A3": (420, 297), "A5": (210, 148)}.get(size, (297, 210))
    orientation = (args.get("orientation") or "landscape").lower()
    width, height = dimensions if orientation == "landscape" else dimensions[::-1]
    page.setPageSize(QgsLayoutSize(width, height, LAYOUT_MM))

    map_item = QgsLayoutItemMap(layout)
    map_item.setRect(0, 0, width - 20, height - 40)
    if ctx.iface:
        map_item.setExtent(ctx.iface.mapCanvas().extent())
    map_item.attemptMove(QgsLayoutPoint(10, 25, LAYOUT_MM))
    map_item.attemptResize(
        QgsLayoutSize(width - 20, height - 45, LAYOUT_MM)
    )
    map_item.setFrameEnabled(True)
    layout.addLayoutItem(map_item)

    label = QgsLayoutItemLabel(layout)
    label.setText(title)
    label.setFontColor(_black())
    _set_label_font(label, int(args.get("title_size", 18) or 18))
    label.adjustSizeToText()
    label.attemptMove(QgsLayoutPoint(10, 8, LAYOUT_MM))
    layout.addLayoutItem(label)

    if args.get("legend", True):
        legend = QgsLayoutItemLegend(layout)
        legend.setTitle(args.get("legend_title") or "Legend")
        legend.setLinkedMap(map_item)
        legend.attemptMove(
            QgsLayoutPoint(width - 60, 30, LAYOUT_MM)
        )
        layout.addLayoutItem(legend)

    if args.get("scalebar", True):
        scalebar = QgsLayoutItemScaleBar(layout)
        scalebar.setStyle("Single Box")
        scalebar.setLinkedMap(map_item)
        scalebar.applyDefaultSize()
        scalebar.attemptMove(
            QgsLayoutPoint(12, height - 18, LAYOUT_MM)
        )
        layout.addLayoutItem(scalebar)

    credit = QgsLayoutItemLabel(layout)
    credit.setText(args.get("credit") or "Made with Srot in QGIS")
    _set_label_font(credit, 7)
    credit.adjustSizeToText()
    credit.attemptMove(
        QgsLayoutPoint(width - 90, height - 12, LAYOUT_MM)
    )
    layout.addLayoutItem(credit)

    manager.addLayout(layout)
    ctx.journal.add_step(
        "create_print_layout",
        "# print layout {0!r} created ({1} {2})".format(name, size, orientation),
        "Print layout: " + name,
    )
    return {
        "layout": name,
        "page": "{0} {1}".format(size, orientation),
        "items": ["map", "title"]
        + (["legend"] if args.get("legend", True) else [])
        + (["scalebar"] if args.get("scalebar", True) else []),
        "hint": "Open it from Project > Layouts, or call export_layout to write a PDF or PNG.",
    }


def _black():
    from qgis.PyQt.QtGui import QColor

    return QColor(0, 0, 0)


def _set_label_font(label, point_size):
    from qgis.PyQt.QtGui import QFont

    font = QFont()
    font.setPointSize(point_size)
    setter = getattr(label, "setTextFormat", None)
    if setter is not None:
        from qgis.core import QgsTextFormat

        text_format = QgsTextFormat()
        text_format.setFont(font)
        text_format.setSize(point_size)
        setter(text_format)
    else:  # pragma: no cover - QGIS < 3.32
        label.setFont(font)


register(
    Tool(
        "create_print_layout",
        "Create a print layout with a map frame, title, legend and scale bar, sized "
        "A4/A3/A5. This is the map you would hand to someone, not the canvas.",
        _obj(
            {
                "title": _str("Map title."),
                "page_size": _str("Page size.", ["A4", "A3", "A5"]),
                "orientation": _str("Page orientation.", ["landscape", "portrait"]),
                "legend": {"type": "boolean", "description": "Include a legend.", "default": True},
                "scalebar": {"type": "boolean", "description": "Include a scale bar.", "default": True},
                "legend_title": _str("Legend heading."),
                "credit": _str("Small credit line at the bottom right."),
                "title_size": _int("Title font point size.", 18),
            },
            ["title"],
        ),
        _t_create_layout,
    )
)


def _t_export_layout(args, ctx, payload=None):
    layout = ctx.project.layoutManager().layoutByName(args["layout"])
    if layout is None:
        names = [item.name() for item in ctx.project.layoutManager().layouts()]
        raise ToolError(
            "No layout called {0!r}. Layouts in this project: {1}".format(
                args["layout"], ", ".join(names) or "(none)"
            )
        )
    path = os.path.abspath(os.path.expanduser(args["path"]))
    _guard_path(path)

    exporter = QgsLayoutExporter(layout)
    if path.lower().endswith(".pdf"):
        result = exporter.exportToPdf(path, QgsLayoutExporter.PdfExportSettings())
    else:
        settings_obj = QgsLayoutExporter.ImageExportSettings()
        settings_obj.dpi = float(args.get("dpi", 300) or 300)
        result = exporter.exportToImage(path, settings_obj)

    if result != EXPORT_SUCCESS:
        raise ToolError("QGIS could not write the layout to {0}.".format(path))
    ctx.journal.add_step(
        "export_layout",
        "# exported layout {0!r} to {1}".format(args["layout"], path),
        "Export layout",
    )
    return {"written": path}


register(
    Tool(
        "export_layout",
        "Export a print layout to PDF or PNG.",
        _obj(
            {
                "layout": _str("Layout name."),
                "path": _str("Output file path ending in .pdf or .png."),
                "dpi": _int("DPI for image export.", 300),
            },
            ["layout", "path"],
        ),
        _t_export_layout,
        tier=WRITE,
    )
)


def _t_export_layer(args, ctx, payload=None):
    layer = ctx.find_layer(args["layer"])
    if not isinstance(layer, QgsVectorLayer):
        raise ToolError(
            "export_layer writes vector layers. For a raster, use run_processing "
            "with 'gdal:translate'."
        )
    path = os.path.abspath(os.path.expanduser(args["path"]))
    _guard_path(path)

    driver = {
        ".gpkg": "GPKG",
        ".shp": "ESRI Shapefile",
        ".geojson": "GeoJSON",
        ".json": "GeoJSON",
        ".csv": "CSV",
        ".kml": "KML",
    }.get(os.path.splitext(path)[1].lower())
    if driver is None:
        raise ToolError(
            "Choose an output extension the writer supports: .gpkg, .shp, .geojson, "
            ".csv or .kml."
        )

    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = driver
    options.fileEncoding = "UTF-8"
    error = QgsVectorFileWriter.writeAsVectorFormatV3(
        layer, path, ctx.project.transformContext(), options
    )
    if error[0] != WRITER_NO_ERROR:
        raise ToolError("Export failed: {0}".format(error[1]))

    ctx.journal.add_step(
        "export_layer",
        "options = QgsVectorFileWriter.SaveVectorOptions()\n"
        "options.driverName = {driver!r}\n"
        "options.fileEncoding = 'UTF-8'\n"
        "QgsVectorFileWriter.writeAsVectorFormatV3(\n"
        "    {ref}, {path!r}, project.transformContext(), options)".format(
            driver=driver, ref=ctx.journal.reference(layer), path=path
        ),
        "Export {0} to {1}".format(layer.name(), driver),
    )
    return {"written": path, "driver": driver, "features": layer.featureCount()}


register(
    Tool(
        "export_layer",
        "Write a vector layer to disk as GeoPackage, Shapefile, GeoJSON, CSV or KML.",
        _obj(
            {
                "layer": _str("Layer name or id."),
                "path": _str("Output path; the extension picks the format."),
            },
            ["layer", "path"],
        ),
        _t_export_layer,
        tier=WRITE,
    )
)


def _t_export_citations(args, ctx, payload=None):
    records = provenance.collect(ctx.project)
    if not records:
        raise ToolError(
            "None of the loaded layers carry recorded sources yet. Layers added "
            "by this plugin do; add one first, then export."
        )

    style = (args.get("style") or "plain").lower()
    if style not in ("plain", "markdown", "bibtex"):
        raise ToolError("'style' must be plain, markdown or bibtex.")
    text = provenance.as_bibliography(records, style)

    path = os.path.abspath(os.path.expanduser(args["path"]))
    _guard_path(path)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
        if not text.endswith("\n"):
            handle.write("\n")

    ctx.journal.add_step(
        "export_citations",
        "_write_sources({path!r}, {style!r})".format(path=path, style=style),
        "Write a source list for {0} layer(s)".format(len(records)),
    )
    return {
        "written": path,
        "style": style,
        "layers": len(records),
        "sources": sorted({r["organisation"] for r in records if r["organisation"]}),
        "preview": text[:1200],
    }


register(
    Tool(
        "export_citations",
        "Write a source list for every layer in the project that carries recorded "
        "provenance: publisher, licence, citation and the date the data was "
        "retrieved. Style 'plain' gives a readable text block, 'markdown' a "
        "section ready to paste into a report, and 'bibtex' entries for a "
        "reference manager. Offer this whenever the user mentions a paper, a "
        "report, a submission or sharing the project with somebody else.",
        _obj(
            {
                "path": _str("Output file path, e.g. ~/sources.md or ~/sources.bib."),
                "style": _str("Citation style.", ["plain", "markdown", "bibtex"]),
            },
            ["path"],
        ),
        _t_export_citations,
        tier=WRITE,
    )
)


def _t_remove_layer(args, ctx, payload=None):
    layer = ctx.find_layer(args["layer"])
    name = layer.name()
    reference = ctx.journal.reference(layer)
    ctx.project.removeMapLayer(layer.id())
    if ctx.iface:
        ctx.iface.mapCanvas().refresh()
    ctx.journal.add_step(
        "remove_layer",
        "project.removeMapLayer({0}.id())".format(reference),
        "Remove " + name,
    )
    return {"removed": name}


register(
    Tool(
        "remove_layer",
        "Remove a layer from the project. This does not delete any file on disk.",
        _obj({"layer": _str("Layer name or id.")}, ["layer"]),
        _t_remove_layer,
        tier=WRITE,
    )
)


def _guard_path(path):
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        raise ToolError(
            "The folder {0} does not exist. Ask the user for a path that does, or "
            "pick their home folder.".format(directory)
        )
    if os.path.exists(path) and not os.access(path, os.W_OK):
        raise ToolError("{0} exists and is not writable.".format(path))
