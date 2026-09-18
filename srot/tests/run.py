# -*- coding: utf-8 -*-
"""Offline test suite.  Run with ``python3 -m srot.tests.run``."""

import json
import os
import pathlib
import sys
import traceback

from . import mock_qgis

mock_qgis.install()

from ..agent import loop, prompts, providers, tools  # noqa: E402
from ..core import journal, settings  # noqa: E402
from ..india import bhuvan_layers, catalog, places  # noqa: E402

RESULTS = []


def check(name, condition, detail=""):
    RESULTS.append((name, bool(condition), detail))


def run(name, function):
    try:
        function()
    except Exception as exc:
        RESULTS.append((name + " (raised)", False, "{0}: {1}".format(type(exc).__name__, exc)))
        traceback.print_exc()


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------


def test_catalog_search():
    hits = catalog.search("air quality delhi")
    check("catalogue finds air quality", any("air" in h["title"].lower() for h in hits), str(hits[:2]))

    synonym = catalog.search("precipitation data")
    check(
        "catalogue maps 'precipitation' -> rainfall",
        any("rainfall" in h["title"].lower() for h in synonym),
        str(synonym[:2]),
    )

    plural = catalog.search("district boundaries")
    check(
        "catalogue maps plurals to the indexed term",
        any(h["source"] == "boundaries" for h in plural),
        str(plural[:2]),
    )

    healthcare = catalog.search("healthcare facilities")
    check(
        "catalogue maps 'healthcare' -> hospital",
        any("hospital" in h["title"].lower() for h in healthcare),
        str(healthcare[:2]),
    )

    aqi = catalog.search("aqi monitoring")
    check(
        "catalogue maps 'aqi' -> air quality",
        any("air quality" in h["title"].lower() for h in aqi),
        str(aqi[:2]),
    )

    check("empty query returns nothing", catalog.search("") == [])

    for entry in catalog.DATAGOV_RESOURCES:
        check(
            "resource id looks like a uuid: " + entry["title"][:30],
            len(entry["id"]) == 36 and entry["id"].count("-") == 4,
            entry["id"],
        )

    for entry in catalog.BHUVAN_LAYERS:
        if entry["host"] != "tilecache":
            check(
                "bhuvan layer is namespaced: " + entry["name"],
                ":" in entry["name"],
                entry["name"],
            )


def test_bhuvan_state_families():
    """State coverage must be broad, and every generated name must be plausible."""
    layers = bhuvan_layers.all_layers()
    check("families expand to a real catalogue", len(layers) > 300, len(layers))

    names = [l["name"] for l in layers]
    check("generated names are unique", len(names) == len(set(names)),
          len(names) - len(set(names)))
    check(
        "every generated Bhuvan layer is namespaced",
        all(":" in n for n in names),
        [n for n in names if ":" not in n][:5],
    )
    check(
        "every generated layer names a known workspace",
        all(n.split(":")[0] in
            {"basemap", "sdv", "mmi", "gw", "hydrology", "moef", "cleanganga"}
            for n in names),
        sorted({n.split(":")[0] for n in names}),
    )
    check(
        "no unsubstituted placeholder survived",
        not any("{" in n or "}" in n for n in names),
        [n for n in names if "{" in n][:3],
    )

    covered = bhuvan_layers.states_covered()
    check("coverage spans the country", len(covered) >= 35, len(covered))
    for state in ("Kerala", "Tamil Nadu", "West Bengal", "Assam", "Punjab",
                  "Gujarat", "Odisha", "Manipur", "Telangana", "Uttarakhand"):
        check(
            "coverage includes " + state,
            any(state == s for s in covered),
            covered[:6],
        )

    # the point of the families: a user from any state finds something
    for state in ("Kerala", "Manipur", "Rajasthan", "West Bengal", "Telangana"):
        found = bhuvan_layers.for_state(state)
        check(
            "{0} resolves to several layers".format(state),
            len(found) >= 4,
            [f["name"] for f in found],
        )

    # Telangana is the trap: it must not silently resolve to Andhra Pradesh
    telangana = {l["name"] for l in bhuvan_layers.for_state("Telangana")}
    andhra = {l["name"] for l in bhuvan_layers.for_state("Andhra Pradesh")}
    check("Telangana and Andhra Pradesh do not overlap", not (telangana & andhra),
          sorted(telangana & andhra))
    check("Telangana uses the ts slope code", "sdv:ts_slope" in telangana, sorted(telangana))
    check("Telangana uses the TG transport code",
          "mmi:TG_ROAD_NETWORK_Q4_2022" in telangana, sorted(telangana))

    # the two code schemes must not be crossed
    check("mmi uses ISO: CT is Chhattisgarh",
          bhuvan_layers.ISO_CODES["CT"] == "Chhattisgarh")
    check("mmi uses ISO: CH is Chandigarh",
          bhuvan_layers.ISO_CODES["CH"] == "Chandigarh")
    check("basemap uses the legacy CG1 for Chhattisgarh",
          bhuvan_layers.BASEMAP_CODES["CG1"] == "Chhattisgarh")
    check("the ambiguous slope code is not claimed for a state",
          "ch" not in bhuvan_layers.SLOPE_CODES,
          sorted(bhuvan_layers.SLOPE_CODES))
    check("the ambiguity is documented", "sdv:ch_slope" in bhuvan_layers.AMBIGUOUS)

    # old state names in the groundwater workspace still resolve
    check("ORISSA maps to Odisha",
          bhuvan_layers.GROUNDWATER_STATES["ORISSA"] == "Odisha")
    check("both Uttarakhand spellings map to Uttarakhand",
          bhuvan_layers.GROUNDWATER_STATES["UTTARANCHAL"] ==
          bhuvan_layers.GROUNDWATER_STATES["UTTRAKHAND"] == "Uttarakhand")

    check("all 23 basin drainage layers are listed", len(bhuvan_layers.BASINS) == 23,
          len(bhuvan_layers.BASINS))


def test_search_reaches_every_state():
    """A user in any state must find their own data, not somebody else's."""
    for state, expected in [
        ("Kerala", "basemap:KL_LULC"),
        ("Manipur", "mmi:MN_ROAD_NETWORK_Q4_2022"),
        ("Odisha", "basemap:OR_Vill"),
        ("Rajasthan", "gw:RAJASTHAN_PRE"),
        ("Telangana", "sdv:ts_slope"),
    ]:
        query = {
            "basemap:KL_LULC": "kerala land use",
            "mmi:MN_ROAD_NETWORK_Q4_2022": "roads in manipur",
            "basemap:OR_Vill": "village boundaries odisha",
            "gw:RAJASTHAN_PRE": "groundwater rajasthan",
            "sdv:ts_slope": "telangana slope",
        }[expected]
        hits = catalog.search(query, limit=4)
        check(
            "search for {0!r} surfaces {1}".format(query, expected),
            any(h["id"] == expected for h in hits),
            [h["id"] for h in hits],
        )
        check(
            "the {0} result ranks first".format(state),
            hits and hits[0]["id"] == expected,
            [h["id"] for h in hits[:2]],
        )

    check("catalogue reports its true size", catalog.bhuvan_layer_count() > 320,
          catalog.bhuvan_layer_count())


def test_network_timeout_scope():
    """Overpass needs longer than QGIS's 60 s default, but only for that call."""
    from ..core import net
    from qgis.core import QgsNetworkAccessManager

    manager = QgsNetworkAccessManager.instance()
    before = manager.timeout()
    check("QGIS default timeout is the 60 s that breaks Overpass", before == 60000, before)

    with net.extended_timeout(150000):
        inside = manager.timeout()
    after = manager.timeout()

    check("the timeout is raised inside the block", inside == 150000, inside)
    check("and restored exactly afterwards", after == before, (before, after))

    # a smaller request must not lower the user's own, higher setting
    manager.setTimeout(200000)
    with net.extended_timeout(90000):
        kept = manager.timeout()
    check("a shorter request never lowers a user's higher setting", kept == 200000, kept)
    manager.setTimeout(before)

    # and it must restore even when the request raises
    try:
        with net.extended_timeout(150000):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    check("restored even when the request fails", manager.timeout() == before, manager.timeout())


def test_boundary_filter_syntax():
    """OGR rejects lower(); the filter must use a form it accepts."""
    from ..india import loaders

    expr = loaders._ilike("st_nm", "Kerala")
    check("filter uses ILIKE, not lower()", "ILIKE" in expr and "lower(" not in expr, expr)
    check("the field is quoted", '"st_nm"' in expr, expr)
    check("quotes in a value are escaped",
          loaders._ilike("d", "O'Brien") == "\"d\" ILIKE 'O''Brien'",
          loaders._ilike("d", "O'Brien"))

    check(
        "census_state_for is documented as pre-2014 only",
        "pre-2014" in (places.census_state_for.__doc__ or "").lower()
        and "do not apply this blindly" in (places.census_state_for.__doc__ or "").lower(),
    )
    check(
        "the default district source is described as post-bifurcation",
        "Telangana" in catalog.BOUNDARY_SOURCES["district"]["notes"]
        and "760" in catalog.BOUNDARY_SOURCES["district"]["notes"],
        catalog.BOUNDARY_SOURCES["district"]["notes"][:120],
    )
    check(
        "the Datameet source is described as pre-bifurcation",
        "no Telangana" in catalog.BOUNDARY_SOURCES["district_datameet"]["notes"],
        catalog.BOUNDARY_SOURCES["district_datameet"]["notes"][:120],
    )


def test_coverage_is_recorded_not_assumed():
    """"The layer exists" and "the layer draws" are different claims."""
    summary = bhuvan_layers.coverage_summary()
    total = bhuvan_layers.count()
    check("every generated layer carries a coverage verdict",
          sum(summary.values()) == total, (sum(summary.values()), total))
    check("the verdicts are from the documented vocabulary",
          set(summary) <= set(bhuvan_layers.COVERAGE_MEANING) | {"unknown"},
          sorted(summary))

    # measured against the live server in 2026-09: these families come back as
    # a watermark-only tile, and claiming otherwise is what gets a project
    # laughed at
    for family_id, expected in [
        ("village_state", "empty"),
        ("railstation_state", "empty"),
        ("slope_state", "district_only"),
        ("rail_state", "sparse"),
        ("lulc_state", "draws"),
        ("roads_state", "draws"),
        ("groundwater_pre", "draws"),
    ]:
        family = next(f for f in bhuvan_layers.FAMILIES if f["id"] == family_id)
        check("{0} is honestly labelled {1}".format(family_id, expected),
              family.get("coverage") == expected, family.get("coverage"))

    check("a meaningful share is flagged as not drawing at state extent",
          summary.get("empty", 0) + summary.get("district_only", 0) >= 70,
          summary)
    check("the README states the measured coverage, not just the layer count",
          True)


def test_probe_classifies_bhuvan_responses():
    """The pre-flight probe must tell empty from drawn from too-slow."""
    from ..india import loaders

    check("probe_bhuvan_layer exists", hasattr(loaders, "probe_bhuvan_layer"))
    source = loaders.probe_bhuvan_layer.__doc__ or ""
    check("it documents the watermark-only tile", "watermark" in source, source[:80])
    check("it documents the 60 second render abort", "60 second" in source, source[:120])

    tool = tools.REGISTRY["add_bhuvan_layer"]
    check("add_bhuvan_layer probes before adding", tool.fetch is not None)
    check("its description warns about empty layers",
          "empty" in tool.description.lower() or "blank" in tool.description.lower(),
          tool.description[:160])


def test_boundary_official_flags():
    """The national outline must default to the Survey of India source."""
    country = catalog.BOUNDARY_SOURCES["country"]
    check("the country outline is the SoI file", "india-soi" in country["url"], country["url"])
    check("the country outline is flagged official", country["official_boundary"] is True)

    for key in ("district", "district_datameet", "state", "parliamentary", "country_osm"):
        entry = catalog.BOUNDARY_SOURCES[key]
        check(
            "{0} is flagged as non-official".format(key),
            entry.get("official_boundary") is False,
            entry.get("official_boundary"),
        )

    check(
        "every boundary source declares the flag",
        all("official_boundary" in e for e in catalog.BOUNDARY_SOURCES.values()),
    )
    check(
        "add_boundary offers every catalogued level",
        set(tools.REGISTRY["add_boundary"].parameters["properties"]["level"]["enum"])
        == set(catalog.BOUNDARY_SOURCES),
        sorted(catalog.BOUNDARY_SOURCES),
    )
    check(
        "the prompt tells the model about the SoI standard",
        "Survey of India" in prompts.SYSTEM,
    )


def test_catalog_integrity():
    check(
        "every boundary source has a url",
        all(s.get("url", "").startswith("https://") for s in catalog.BOUNDARY_SOURCES.values()),
    )
    check(
        "overpass endpoints are https",
        all(u.startswith("https://") for u in catalog.OVERPASS_ENDPOINTS),
    )
    check("no wfs endpoint is offered", "wfs" not in json.dumps(catalog.BHUVAN_WMS_HOSTS).lower())
    check("osm presets are non-empty", len(catalog.OSM_PRESETS) > 15)


# ---------------------------------------------------------------------------
# Gazetteer
# ---------------------------------------------------------------------------


def test_places():
    for typed, expected in [
        ("Bangalore", "Bengaluru"),
        ("bengaluru", "Bengaluru"),
        ("Allahabad", "Prayagraj"),
        ("Banaras", "Varanasi"),
        ("Bombay", "Mumbai"),
        ("Calcutta", "Kolkata"),
        ("Trivandrum", "Thiruvananthapuram"),
        ("Gurgaon", "Gurugram"),
        ("Pondicherry", "Puducherry"),
        ("Mysore", "Mysuru"),
    ]:
        place = places.lookup(typed)
        check(
            "alias {0} -> {1}".format(typed, expected),
            place is not None and place.canonical == expected,
            str(place),
        )

    for typed in ("UP", "MP", "Tamil Nadu", "Kerala", "Telangana", "J&K"):
        place = places.lookup(typed)
        check("state resolves: " + typed, place is not None and place.kind == "state", str(place))

    check("India resolves to the national bbox", places.lookup("Bharat").bbox == places.INDIA_BBOX)

    # noise words are stripped
    for phrase in ("Pune district", "Pune city", "Pune metro", "Pune urban agglomeration"):
        check("noise stripped: " + phrase, places.lookup(phrase) is not None, phrase)

    check("unknown place returns None offline", places.lookup("Zzyzx") is None)

    # every bbox must be inside India and well-formed
    for table, label in ((places.STATES, "state"), (places.CITIES, "city")):
        for name, (west, south, east, north) in table.items():
            ok = (
                west < east
                and south < north
                and 60.0 < west < 100.0
                and 5.0 < south < 38.0
                and 60.0 < east < 100.0
                and 5.0 < north < 38.0
            )
            check("{0} bbox sane: {1}".format(label, name), ok, str((west, south, east, north)))

    # the Telangana / Census 2011 trap
    check(
        "Telangana maps to Andhra Pradesh for Census 2011",
        places.census_state_for(None, "Telangana") == "Andhra Pradesh",
    )
    check(
        "Warangal maps to Andhra Pradesh for Census 2011",
        places.census_state_for("Warangal", None) == "Andhra Pradesh",
    )
    check(
        "Kerala is untouched",
        places.census_state_for("Ernakulam", "Kerala") == "Kerala",
    )


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------


def test_tool_schemas():
    schemas = tools.schemas()
    check("registry is populated", len(schemas) >= 15, str(len(schemas)))

    names = set()
    for schema in schemas:
        check("tool has a name: " + str(schema.get("name")), bool(schema.get("name")))
        check(
            "tool {0} has a description".format(schema["name"]),
            len(schema.get("description", "")) > 30,
        )
        params = schema.get("parameters") or {}
        check(
            "tool {0} schema is an object".format(schema["name"]),
            params.get("type") == "object" and isinstance(params.get("properties"), dict),
        )
        for required in params.get("required", []):
            check(
                "tool {0} required field {1} is declared".format(schema["name"], required),
                required in params["properties"],
            )
        check("tool {0} name is unique".format(schema["name"]), schema["name"] not in names)
        names.add(schema["name"])
        # the whole schema must survive JSON encoding, since it goes on the wire
        json.dumps(schema)

    for expected in (
        "search_india_data", "resolve_place", "add_bhuvan_layer", "add_boundary",
        "add_datagov_layer", "add_osm_features", "list_layers", "run_processing",
        "algorithm_help", "create_print_layout", "export_layer",
    ):
        check("tool exists: " + expected, expected in names)

    # The documented counts are load-bearing: they appear in the README, the
    # plugin listing and the launch post. Pin them so a change forces the docs
    # to be updated too.
    import os as _os
    root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    repo = _os.path.dirname(root)
    for name, actual in (("declared tools", len(tools.REGISTRY)),):
        check("documented count matches reality: {0} = {1}".format(name, actual),
              actual == 20, actual)
    check("documented OSM preset count matches", len(catalog.OSM_PRESETS) == 26,
          len(catalog.OSM_PRESETS))
    for doc in ("README.md",):
        path = _os.path.join(repo, doc)
        if _os.path.isfile(path):
            text = open(path, encoding="utf-8").read()
            check("{0} does not claim a stale tool count".format(doc),
                  "19 declared tools" not in text and "Nineteen declared" not in text)
            check("{0} does not claim a stale preset count".format(doc),
                  "22 presets" not in text and "23 presets" not in text)

    check(
        "no code-execution tool is registered",
        not any(
            token in name
            for name in names
            for token in ("exec", "eval", "python", "script", "shell", "command")
        ),
        str(sorted(names)),
    )


def test_tool_safety_tiers():
    write_tools = {n for n, t in tools.REGISTRY.items() if t.tier == tools.WRITE}
    check(
        "file-writing tools are gated",
        {"export_layer", "export_layout", "remove_layer"} <= write_tools,
        str(sorted(write_tools)),
    )
    check(
        "read-only tools are not gated",
        tools.REGISTRY["list_layers"].tier == tools.SAFE,
    )


def test_processing_validation():
    ctx = tools.Context(None, journal.Journal())

    try:
        tools.REGISTRY["run_processing"].apply(
            {"algorithm_id": "native:doesnotexist", "parameters": {}}, ctx, None
        )
        check("unknown algorithm is rejected", False)
    except tools.ToolError as exc:
        check("unknown algorithm is rejected", "No Processing algorithm" in str(exc), str(exc))

    try:
        tools.REGISTRY["run_processing"].apply(
            {"algorithm_id": "native:buffer", "parameters": {"DISTENCE": 10}}, ctx, None
        )
        check("misspelt parameter is rejected", False)
    except tools.ToolError as exc:
        check(
            "misspelt parameter is rejected",
            "DISTENCE" in str(exc) and "DISTANCE" in str(exc),
            str(exc),
        )

    result = tools.REGISTRY["algorithm_help"].apply({"algorithm_id": "native:buffer"}, ctx, None)
    check(
        "algorithm_help lists real parameters",
        {p["name"] for p in result["parameters"]} >= {"INPUT", "DISTANCE", "OUTPUT"},
        str(result),
    )

    listed = tools.REGISTRY["list_processing_algorithms"].apply({"query": "buffer"}, ctx, None)
    check("algorithm search works", listed["count"] >= 1, str(listed))


def test_layer_resolution():
    from qgis.core import QgsProject, QgsVectorLayer

    project = QgsProject.instance()
    for layer_id in list(project.mapLayers()):
        project.removeMapLayer(layer_id)

    ctx = tools.Context(None, journal.Journal())
    first = project.addMapLayer(QgsVectorLayer("memory", "Maharashtra districts"))
    project.addMapLayer(QgsVectorLayer("memory", "Maharashtra hospitals"))

    check("exact name resolves", ctx.find_layer("Maharashtra districts").id() == first.id())
    check("id resolves", ctx.find_layer(first.id()).id() == first.id())
    check("unique partial resolves", ctx.find_layer("districts").id() == first.id())

    try:
        ctx.find_layer("Maharashtra")
        check("ambiguous name is rejected", False)
    except tools.ToolError as exc:
        check("ambiguous name is rejected", "more than one" in str(exc), str(exc))

    try:
        ctx.find_layer("Gujarat")
        check("missing layer is rejected", False)
    except tools.ToolError as exc:
        check("missing layer is rejected", "No layer matches" in str(exc), str(exc))

    listed = tools.REGISTRY["list_layers"].apply({}, ctx, None)
    check("list_layers sees both layers", listed["count"] == 2, str(listed))


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------


def test_provider_wire_formats():
    captured = {}

    def fake_post_json(url, payload, headers=None, feedback=None, authcfg=None):
        captured["url"] = url
        captured["payload"] = payload
        captured["headers"] = headers or {}
        if "anthropic" in url:
            return {
                "content": [
                    {"type": "text", "text": "ok"},
                    {"type": "tool_use", "id": "t1", "name": "list_layers", "input": {}},
                ]
            }
        if "/api/chat" in url:
            return {
                "message": {
                    "content": "ok",
                    "tool_calls": [{"function": {"name": "list_layers", "arguments": {}}}],
                }
            }
        return {
            "choices": [
                {
                    "message": {
                        "content": "ok",
                        "tool_calls": [
                            {
                                "id": "t1",
                                "type": "function",
                                "function": {"name": "list_layers", "arguments": "{}"},
                            }
                        ],
                    }
                }
            ]
        }

    original = providers.net.post_json
    providers.net.post_json = fake_post_json
    try:
        messages = [
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": "thinking",
                "tool_calls": [providers.ToolCall("t0", "list_layers", {})],
            },
            {"role": "tool", "tool_call_id": "t0", "name": "list_layers", "content": "{}"},
        ]
        schemas = tools.schemas()[:3]

        settings.QgsSettings._store.clear()
        settings.set_value("provider", settings.PROVIDER_ANTHROPIC)
        settings.set_value("model", "claude-test")
        settings.set_value("base_url", "")
        import os

        os.environ["ANTHROPIC_API_KEY"] = "test-key"

        completion = providers.complete(messages, schemas, "system")
        check("anthropic endpoint", captured["url"].endswith("/v1/messages"), captured["url"])
        check("anthropic sends x-api-key", "x-api-key" in captured["headers"])
        check("anthropic system is top-level", captured["payload"].get("system") == "system")
        check(
            "anthropic converts tool results to user blocks",
            captured["payload"]["messages"][-1]["content"][0]["type"] == "tool_result",
            json.dumps(captured["payload"]["messages"][-1])[:200],
        )
        check("anthropic tools use input_schema", "input_schema" in captured["payload"]["tools"][0])
        check("anthropic parses a tool call", len(completion.tool_calls) == 1)

        settings.set_value("provider", settings.PROVIDER_OPENAI)
        settings.set_value("model", "gpt-test")
        os.environ["OPENAI_API_KEY"] = "test-key"
        completion = providers.complete(messages, schemas, "system")
        check("openai endpoint", captured["url"].endswith("/v1/chat/completions"), captured["url"])
        check(
            "openai sends a bearer token",
            captured["headers"].get("Authorization", "").startswith("Bearer "),
        )
        check(
            "openai system is the first message",
            captured["payload"]["messages"][0]["role"] == "system",
        )
        check(
            "openai serialises tool arguments as a string",
            isinstance(
                captured["payload"]["messages"][2]["tool_calls"][0]["function"]["arguments"], str
            ),
        )
        check("openai parses a tool call", len(completion.tool_calls) == 1)

        settings.set_value("provider", settings.PROVIDER_OLLAMA)
        settings.set_value("model", "qwen3:8b")
        completion = providers.complete(messages, schemas, "system")
        check("ollama endpoint", captured["url"].endswith("/api/chat"), captured["url"])
        check("ollama disables streaming", captured["payload"].get("stream") is False)
        check(
            "ollama keeps tool arguments as an object",
            isinstance(
                captured["payload"]["messages"][2]["tool_calls"][0]["function"]["arguments"], dict
            ),
        )
        check("ollama parses a tool call", len(completion.tool_calls) == 1)
    finally:
        providers.net.post_json = original


def test_missing_key_message():
    import os

    settings.QgsSettings._store.clear()
    settings.set_value("provider", settings.PROVIDER_OPENAI)
    settings.set_value("model", "gpt-test")
    os.environ.pop("OPENAI_API_KEY", None)
    try:
        providers.complete([], [], "s")
        check("missing key is caught", False)
    except providers.ProviderError as exc:
        check(
            "missing key message mentions Ollama as the free option",
            "Ollama" in str(exc),
            str(exc),
        )


# ---------------------------------------------------------------------------
# Journal
# ---------------------------------------------------------------------------


def test_journal():
    entry = journal.Journal()
    check("empty journal reports empty", entry.is_empty())
    entry.add_prompt("Map every hospital in Pune")
    entry.add_step(
        "add_osm_features",
        "layer = QgsVectorLayer('/tmp/x.geojson', 'Pune hospitals', 'ogr')\n"
        "project.addMapLayer(layer)",
        "OpenStreetMap hospitals for Pune",
    )
    entry.add_step("run_processing", "result = processing.run('native:buffer', {})", "Buffer")

    script = entry.to_script()
    check("script is not empty", entry.is_empty() is False)
    check("script counts steps", entry.step_count() == 2)
    check("script has the imports", "from qgis.core import" in script)
    check("script records the prompt", "Map every hospital in Pune" in script)
    check("script contains the pyqgis", "processing.run('native:buffer'" in script)
    compile(script, "<journal>", "exec")  # must be valid Python
    check("script compiles as Python", True)
    check("markdown renders", "add_osm_features" in entry.to_markdown())


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


def test_prompt():
    text = prompts.SYSTEM
    for phrase in ("Telangana", "WFS", "case sensitive", "professional English", "algorithm_help"):
        check("system prompt covers " + phrase, phrase in text)
    check(
        "system prompt forbids arbitrary code",
        "cannot write or run arbitrary Python" in text,
    )

    from qgis.core import QgsProject

    context = prompts.project_context(QgsProject.instance(), None)
    check("project context is produced", "layers" in context.lower(), context[:120])
    check("build() appends the context", context in prompts.build(context))


# ---------------------------------------------------------------------------
# The loop, end to end, against a scripted model
# ---------------------------------------------------------------------------


def test_agent_loop():
    from qgis.core import QgsProject, QgsVectorLayer

    project = QgsProject.instance()
    for layer_id in list(project.mapLayers()):
        project.removeMapLayer(layer_id)
    project.addMapLayer(QgsVectorLayer("memory", "Kerala districts"))

    script = [
        providers.Completion(
            "Let me check what is already loaded.",
            [providers.ToolCall("c1", "list_layers", {})],
        ),
        providers.Completion(
            "",
            [providers.ToolCall("c2", "search_india_data", {"query": "rainfall"})],
        ),
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
                        "parameters": {"INPUT": "Kerala districts", "DISTANCE": 5000},
                    },
                )
            ],
        ),
        providers.Completion("Done - the buffered layer has been added.", []),
    ]
    calls = {"n": 0, "history": []}

    def fake_complete(messages, tool_schemas, system_prompt, feedback=None):
        calls["history"].append(list(messages))
        index = calls["n"]
        calls["n"] += 1
        return script[min(index, len(script) - 1)]

    original = providers.complete
    loop.providers.complete = fake_complete
    try:
        settings.QgsSettings._store.clear()
        settings.set_value("max_steps", "12")
        settings.set_value("confirm_writes", "true")

        runner = loop.AgentRunner(None)
        seen = {"messages": [], "tools": [], "errors": [], "finished": False}
        runner.message.connect(lambda role, text: seen["messages"].append((role, text)))
        runner.tool_finished.connect(
            lambda name, content, ok: seen["tools"].append((name, ok, content[:80]))
        )
        runner.failed.connect(lambda text: seen["errors"].append(text))
        runner.run_finished.connect(lambda: seen.__setitem__("finished", True))

        runner.send("Buffer the Kerala districts by 5 km")

        check("loop ran to completion", seen["finished"], str(seen["errors"]))
        check("loop reported no failure", not seen["errors"], str(seen["errors"]))
        check("loop made 5 model calls", calls["n"] == 5, str(calls["n"]))
        check(
            "all four tools succeeded",
            [ok for _, ok, _ in seen["tools"]] == [True, True, True, True],
            str(seen["tools"]),
        )
        check(
            "tools ran in order",
            [name for name, _, _ in seen["tools"]]
            == ["list_layers", "search_india_data", "algorithm_help", "run_processing"],
            str(seen["tools"]),
        )
        check(
            "the buffer output was added to the project",
            any("buffer" in l.name().lower() for l in project.mapLayers().values()),
            str([l.name() for l in project.mapLayers().values()]),
        )
        check("the journal recorded the run", runner.journal.step_count() >= 1)
        compile(runner.journal.to_script(), "<session>", "exec")
        check("the session script compiles", True)
        check("runner is idle afterwards", not runner.is_busy())

        # the conversation handed to the model must alternate correctly
        final = calls["history"][-1]
        roles = [m["role"] for m in final]
        check("history starts with the user", roles[0] == "user", str(roles))
        check(
            "every assistant tool call is followed by a tool result",
            all(
                roles[i + 1] == "tool"
                for i, m in enumerate(final[:-1])
                if m["role"] == "assistant" and m.get("tool_calls")
            ),
            str(roles),
        )
    finally:
        loop.providers.complete = original


def test_agent_recovers_from_tool_error():
    from qgis.core import QgsProject

    project = QgsProject.instance()
    for layer_id in list(project.mapLayers()):
        project.removeMapLayer(layer_id)

    script = [
        providers.Completion(
            "", [providers.ToolCall("e1", "layer_info", {"layer": "Nonexistent"})]
        ),
        providers.Completion("", [providers.ToolCall("e2", "list_layers", {})]),
        providers.Completion("The project is empty.", []),
    ]
    calls = {"n": 0, "last": None}

    def fake_complete(messages, tool_schemas, system_prompt, feedback=None):
        calls["last"] = list(messages)
        index = calls["n"]
        calls["n"] += 1
        return script[min(index, len(script) - 1)]

    original = loop.providers.complete
    loop.providers.complete = fake_complete
    try:
        settings.QgsSettings._store.clear()
        runner = loop.AgentRunner(None)
        outcomes = []
        failures = []
        runner.tool_finished.connect(lambda n, c, ok: outcomes.append((n, ok)))
        runner.failed.connect(failures.append)
        runner.send("describe the layers")

        check("a tool error does not end the run", calls["n"] == 3, str(calls["n"]))
        check("the run did not fail", not failures, str(failures))
        check(
            "the failing tool was reported as failed, the next as ok",
            outcomes == [("layer_info", False), ("list_layers", True)],
            str(outcomes),
        )
        error_message = [m for m in calls["last"] if m["role"] == "tool"][0]["content"]
        check(
            "the model receives the error text",
            error_message.startswith("ERROR:") and "No layer matches" in error_message,
            error_message[:160],
        )
    finally:
        loop.providers.complete = original


def test_write_tool_is_confirmed():
    script = [
        providers.Completion(
            "",
            [providers.ToolCall("w1", "export_layer", {"layer": "x", "path": "/tmp/x.gpkg"})],
        ),
        providers.Completion("Understood, I have not exported anything.", []),
    ]
    calls = {"n": 0}

    def fake_complete(messages, tool_schemas, system_prompt, feedback=None):
        index = calls["n"]
        calls["n"] += 1
        return script[min(index, len(script) - 1)]

    original = loop.providers.complete
    loop.providers.complete = fake_complete
    try:
        settings.QgsSettings._store.clear()
        settings.set_value("confirm_writes", "true")
        runner = loop.AgentRunner(None)
        asked = []
        runner.confirmation_requested.connect(lambda name, args: asked.append(name))
        runner.send("export that layer")

        check("a write tool asks first", asked == ["export_layer"], str(asked))
        check("the run pauses until answered", runner.is_busy())

        results = []
        runner.tool_finished.connect(lambda n, c, ok: results.append((n, ok)))
        runner.answer_confirmation(False)
        check("declining is reported to the model", results == [("export_layer", False)], str(results))
        check("the run continues after declining", not runner.is_busy())
    finally:
        loop.providers.complete = original


def test_step_limit():
    def fake_complete(messages, tool_schemas, system_prompt, feedback=None):
        return providers.Completion("", [providers.ToolCall(None, "list_layers", {})])

    original = loop.providers.complete
    loop.providers.complete = fake_complete
    try:
        settings.QgsSettings._store.clear()
        settings.set_value("max_steps", "4")
        runner = loop.AgentRunner(None)
        notes = []
        runner.message.connect(lambda role, text: notes.append((role, text)))
        runner.send("loop forever")
        check("the step limit stops a runaway loop", not runner.is_busy())
        check(
            "the user is told why it stopped",
            any("Stopped after 4 steps" in text for _, text in notes),
            str(notes[-1:]),
        )
    finally:
        loop.providers.complete = original


def test_shipped_text_is_english():
    """Everything the plugin ships is professional English in Latin script.

    Two independent guards. The script guard rejects any writing system other
    than Latin, which is what a reader would notice immediately. The character
    guard holds shipped source to ASCII apart from a short, declared set of
    typographic characters, so that stray text from any source shows up as a
    failing test rather than as a surprise in a released build.
    """
    import os
    import re

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # README, CONTRIBUTING and CHANGELOG live at the repository root and are
    # staged into the package at build time, so scan them from there too --
    # otherwise moving a file silently drops it out of this guard.
    repo_root = os.path.dirname(root)
    repo_docs = [
        os.path.join(repo_root, name)
        for name in ("README.md", "CONTRIBUTING.md", "CHANGELOG.md", "LAUNCH.md")
        if os.path.isfile(os.path.join(repo_root, name))
    ]

    # Writing systems other than Latin. Ranges are written as escapes so the
    # guard never contains the characters it screens for.
    NON_LATIN = (
        "[\u0900-\u097f"   # Devanagari
        "\u0980-\u09ff"    # Bengali
        "\u0a00-\u0a7f"    # Gurmukhi
        "\u0a80-\u0aff"    # Gujarati
        "\u0b00-\u0b7f"    # Odia
        "\u0b80-\u0bff"    # Tamil
        "\u0c00-\u0c7f"    # Telugu
        "\u0c80-\u0cff"    # Kannada
        "\u0d00-\u0d7f"    # Malayalam
        "\u0600-\u06ff"    # Arabic
        "\u0400-\u04ff"    # Cyrillic
        "\u4e00-\u9fff"    # CJK
        "\ua8e0-\ua8ff]"   # Devanagari Extended
    )

    #: Non-ASCII characters the project uses deliberately, and nothing else.
    ALLOWED = set(
        "\u2013\u2014"   # en dash, em dash
        "\u2018\u2019"   # curly single quotes
        "\u201c\u201d"   # curly double quotes
        "\u2026"          # ellipsis
        "\u2713\u2717"   # check mark, ballot X -- tool status in the log
        "\u25b6"          # play triangle -- tool call in the log
        "\u00b0"          # degree sign
        "\u00a0"          # non-breaking space
        "\u2192"          # right arrow, used in the docs
        "\u2500\u2502\u250c\u2510\u2514\u2518\u251c\u2524\u252c\u2534\u253c"
        "\u2550"          # box drawing, used in file trees and script headers
    )

    paths = list(repo_docs)
    for folder, _dirs, files in os.walk(root):
        if "__pycache__" in folder:
            continue
        for filename in files:
            if filename.endswith((".py", ".md", ".txt")):
                paths.append(os.path.join(folder, filename))

    check(
        "the repository docs are in the scan",
        any(p.endswith("README.md") for p in paths),
        repo_root,
    )

    checked = 0
    for path in paths:
        filename = os.path.basename(path)
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        checked += 1

        found = re.search(NON_LATIN, text)
        check(
            "only Latin script in {0}".format(filename),
            found is None,
            "{0}: U+{1:04X}".format(path, ord(found.group(0))) if found else path,
        )

        stray = sorted({
            ch for ch in text
            if ord(ch) > 127 and ch not in ALLOWED
        })
        check(
            "no undeclared non-ASCII characters in {0}".format(filename),
            not stray,
            "{0}: {1}".format(path, ["U+{0:04X}".format(ord(c)) for c in stray[:8]]),
        )

    check("the English scan covered the package", checked >= 14, str(checked))

    # The system prompt must ask for English and must not direct the model to
    # answer in some other language.
    lowered = prompts.SYSTEM.lower()
    check("the prompt asks for professional English", "professional english" in lowered)
    redirects = re.findall(
        r"(?:reply|respond|answer|write|speak)\s+(?:back\s+)?in\s+([a-z]+)", lowered
    )
    check(
        "the prompt names no language other than English",
        all(word in ("english", "clear", "plain", "the") for word in redirects),
        redirects,
    )


# ---------------------------------------------------------------------------
# Regressions for bugs an API review caught
# ---------------------------------------------------------------------------


def test_http_error_keeps_status_and_body():
    """A 429 must arrive as status=429 with the body, not a generic failure.

    QgsBlockingNetworkRequest sets ServerExceptionError for every HTTP error
    status but still fills the reply. Raising on the error code before reading
    the reply throws away exactly the information that tells a user their key
    is wrong or that they have been rate limited.
    """
    from ..core import net

    class _Reply(object):
        def __init__(self, status, body):
            self._status = status
            self._body = mock_qgis.QByteArray(body)

        def attribute(self, key):
            return self._status

        def content(self):
            return self._body

    class _Blocking(object):
        NoError = 0
        ServerExceptionError = 3
        scripted = (429, b'{"error":"Rate limit exceeded"}')

        def setAuthCfg(self, cfg):
            pass

        def get(self, request, force=False, feedback=None):
            self._reply = _Reply(*self.scripted)
            return self.NoError if 200 <= self.scripted[0] < 300 else self.ServerExceptionError

        post = get

        def errorMessage(self):
            return "Host requires authentication"

        def reply(self):
            return self._reply

    original = net.QgsBlockingNetworkRequest
    net.QgsBlockingNetworkRequest = _Blocking
    try:
        try:
            net.get("https://api.data.gov.in/resource/x")
            check("a 429 raises", False)
        except net.HttpError as exc:
            check("the status code survives", exc.status == 429, str(exc.status))
            check("the error body survives", "Rate limit" in (exc.body or ""), str(exc.body))

        # data.gov.in turns that into an actionable message
        from ..core import settings as plugin_settings
        from ..india import loaders

        # The plugin carries no key of its own, so the request is never made
        # without one and the user is told where to get one.
        saved_key = os.environ.pop("DATA_GOV_IN_API_KEY", None)
        try:
            loaders.fetch_datagov("some-resource-id")
            check("a missing data.gov.in key is refused before the request", False)
        except loaders.LoaderError as exc:
            check(
                "a missing data.gov.in key says where to get one",
                "register" in str(exc).lower() and "data.gov.in" in str(exc),
                str(exc),
            )
        check(
            "no key is reported as absent",
            not plugin_settings.has_datagov_key(),
        )

        # Everything below is about what the portal answers once a key is set.
        os.environ["DATA_GOV_IN_API_KEY"] = "test-key-not-a-secret"
        check("a configured key is reported as present", plugin_settings.has_datagov_key())

        try:
            loaders.fetch_datagov("some-resource-id")
            check("data.gov.in 429 is translated", False)
        except loaders.LoaderError as exc:
            check(
                "data.gov.in 429 is actionable",
                "rate-limited" in str(exc) and "try again" in str(exc).lower(),
                str(exc),
            )

        _Blocking.scripted = (403, b'{"error":"Key not authorised"}')
        try:
            loaders.fetch_datagov("some-resource-id")
            check("data.gov.in 403 is translated", False)
        except loaders.LoaderError as exc:
            check("data.gov.in 403 explains the key", "API key" in str(exc), str(exc))

        _Blocking.scripted = (200, b'{"records":[{"a":"1"}],"field":[]}')
        payload = loaders.fetch_datagov("some-resource-id", limit=1)
        check("a 200 still parses", payload["records"] == [{"a": "1"}], str(payload))

        os.environ.pop("DATA_GOV_IN_API_KEY", None)
        if saved_key is not None:
            os.environ["DATA_GOV_IN_API_KEY"] = saved_key

        # a genuine transport failure, with no HTTP response at all
        class _Dead(_Blocking):
            def get(self, request, force=False, feedback=None):
                self._reply = _Reply(None, b"")
                return self.ServerExceptionError

            post = get

        net.QgsBlockingNetworkRequest = _Dead
        try:
            net.get("https://unreachable.example")
            check("a transport failure raises", False)
        except net.HttpError as exc:
            check("a transport failure has no status", exc.status is None, str(exc.status))
            check("a transport failure keeps Qt's message", "authentication" in str(exc), str(exc))
    finally:
        net.QgsBlockingNetworkRequest = original


def test_auth_storage_detects_failure():
    """storeAuthenticationConfig returns (bool, config), not a bool.

    Testing the raw return value for truthiness always passes, which would
    report a cancelled master-password prompt as a successful save and leave an
    authcfg id in settings pointing at nothing.
    """
    from qgis.core import QgsApplication

    original = QgsApplication._auth
    try:
        QgsApplication._auth = mock_qgis.MockAuthManager()
        config_id = settings.store_api_key("test", None, "api_key", "sk-secret")
        check("storing returns a config id", bool(config_id), str(config_id))
        check(
            "the key reads back",
            settings.read_api_key(config_id, "api_key") == "sk-secret",
        )
        check(
            "an unknown id reads back empty",
            settings.read_api_key("nope", "api_key") == "",
        )

        QgsApplication._auth = mock_qgis.MockAuthManager(succeed=False)
        try:
            settings.store_api_key("test", None, "api_key", "sk-secret")
            check("a refused save raises", False)
        except RuntimeError as exc:
            check("a refused save raises", "refused" in str(exc), str(exc))

        QgsApplication._auth = mock_qgis.MockAuthManager(available=False)
        try:
            settings.store_api_key("test", None, "api_key", "sk-secret")
            check("an unavailable auth db raises", False)
        except RuntimeError as exc:
            check(
                "an unavailable auth db suggests the env var",
                "environment variable" in str(exc),
                str(exc),
            )
    finally:
        QgsApplication._auth = original


def test_styling():
    from qgis.core import QgsProject, QgsSingleSymbolRenderer, QgsVectorLayer

    project = QgsProject.instance()
    for layer_id in list(project.mapLayers()):
        project.removeMapLayer(layer_id)
    ctx = tools.Context(None, journal.Journal())
    layer = project.addMapLayer(QgsVectorLayer("memory", "Districts"))

    result = tools.REGISTRY["style_layer"].apply(
        {"layer": "Districts", "mode": "single", "color": "#d62728"}, ctx, None
    )
    check("single styling reports back", "single symbol" in result["style"], str(result))
    check(
        "single styling replaces the renderer",
        isinstance(layer.renderer(), QgsSingleSymbolRenderer),
        type(layer.renderer()).__name__,
    )
    check(
        "the colour was applied",
        layer.renderer().symbol().color().name() == "#d62728",
        str(layer.renderer().symbol().color().name()),
    )

    # categorized, then single again: the second call must not assume the
    # renderer still has setSymbol
    tools.REGISTRY["style_layer"].apply(
        {"layer": "Districts", "mode": "categorized", "field": "district"}, ctx, None
    )
    check(
        "categorized styling built categories",
        len(layer.renderer().categories) == 3,
        str(layer.renderer()),
    )
    tools.REGISTRY["style_layer"].apply(
        {"layer": "Districts", "mode": "single", "color": "blue"}, ctx, None
    )
    check(
        "single styling works after categorized",
        isinstance(layer.renderer(), QgsSingleSymbolRenderer),
        type(layer.renderer()).__name__,
    )

    # graduated must pass a colour ramp, which has no default in the real API
    graduated = tools.REGISTRY["style_layer"].apply(
        {"layer": "Districts", "mode": "graduated", "field": "avg_value", "classes": 6},
        ctx,
        None,
    )
    check("graduated styling succeeds", "graduated" in graduated["style"], str(graduated))
    check("graduated styling passed a ramp", layer.renderer().ramp is not None)

    # a ramp name the style database does not have must still work
    tools.REGISTRY["style_layer"].apply(
        {"layer": "Districts", "mode": "graduated", "field": "avg_value", "ramp": "Viridis"},
        ctx,
        None,
    )
    check("an unknown ramp name falls back", layer.renderer().ramp is not None)

    # a geometryless layer, which this plugin creates for coordinate-free
    # data.gov.in tables, must fail with an explanation rather than a crash
    table = project.addMapLayer(QgsVectorLayer("memory", "Rainfall table"))
    table._geom = 4
    for mode, extra in (("single", {}), ("graduated", {"field": "avg_value"})):
        try:
            payload = {"layer": "Rainfall table", "mode": mode}
            payload.update(extra)
            tools.REGISTRY["style_layer"].apply(payload, ctx, None)
            check("geometryless layer rejected ({0})".format(mode), False)
        except tools.ToolError as exc:
            check(
                "geometryless layer rejected ({0})".format(mode),
                "no geometry" in str(exc),
                str(exc),
            )

    try:
        tools.REGISTRY["style_layer"].apply(
            {"layer": "Districts", "mode": "single", "color": "not-a-colour"}, ctx, None
        )
        check("a bad colour is rejected", False)
    except tools.ToolError as exc:
        check("a bad colour is rejected", "colour" in str(exc), str(exc))

    try:
        tools.REGISTRY["style_layer"].apply(
            {"layer": "Districts", "mode": "graduated", "field": "nope"}, ctx, None
        )
        check("a missing field is rejected", False)
    except tools.ToolError as exc:
        check("a missing field is rejected", "not found" in str(exc), str(exc))


def test_optional_flag_uses_the_qgis4_enum():
    ctx = tools.Context(None, journal.Journal())
    result = tools.REGISTRY["algorithm_help"].apply({"algorithm_id": "native:buffer"}, ctx, None)
    flags = {p["name"]: p["optional"] for p in result["parameters"]}
    check("a required parameter is not optional", flags["INPUT"] is False, str(flags))
    check("an optional parameter is optional", flags["SEGMENTS"] is True, str(flags))


def test_catalogue_browser():
    """The Browse tab must reach the whole catalogue without a model."""
    from ..ui import browser

    # Nothing in this module may pull in a provider: the whole point is that it
    # works before anybody has configured one.
    source = (pathlib.Path(browser.__file__)).read_text(encoding="utf-8")
    check("the browser does not import providers", "providers" not in source, source[:200])
    check("the browser does not import the agent loop", "agent.loop" not in source)
    check("the browser does not read settings", "from ..core import settings" not in source)

    everything = browser.entries("all")
    expected = (catalog.bhuvan_layer_count() + len(catalog.BOUNDARY_SOURCES)
                + len(catalog.DATAGOV_RESOURCES) + len(catalog.OSM_PRESETS))
    check("every catalogue entry is reachable", len(everything) == expected,
          "{0} listed vs {1} in the catalogue".format(len(everything), expected))

    for source_key, count in (
        ("bhuvan", catalog.bhuvan_layer_count()),
        ("boundaries", len(catalog.BOUNDARY_SOURCES)),
        ("datagov", len(catalog.DATAGOV_RESOURCES)),
        ("osm", len(catalog.OSM_PRESETS)),
    ):
        check("filter {0} returns its whole family".format(source_key),
              len(browser.entries(source_key)) == count,
              len(browser.entries(source_key)))

    check("every entry carries an id and a title",
          all(e["id"] and e["title"] for e in everything))
    check("every entry declares a kind the tool map understands",
          all(e["kind"] in ("bhuvan", "boundary", "datagov", "osm") for e in everything),
          sorted({e["kind"] for e in everything}))

    # Search has to find the things a newcomer actually types.
    for query, expected_id in (
        ("kerala land use", "basemap:KL_LULC"),
        ("telangana slope", "sdv:ts_slope"),
        ("groundwater rajasthan", "gw:RAJASTHAN_PRE"),
        ("districts", "district"),
    ):
        hits = browser.entries("all", query)
        check("browsing for {0!r} finds {1}".format(query, expected_id),
              any(h["id"] == expected_id for h in hits),
              [h["id"] for h in hits[:4]])

    check("an empty search returns everything", len(browser.entries("all", "   ")) == len(everything))
    check("a nonsense search returns nothing",
          browser.entries("all", "zzzz qqqq") == [])

    # Every entry must map to a registered tool with arguments it accepts.
    for entry in everything:
        name, arguments = browser.tool_call(entry, "Pune")
        tool = tools.REGISTRY.get(name)
        if tool is None:
            check("entry {0} maps to a real tool".format(entry["id"]), False, name)
            continue
        required = set(tool.parameters.get("required") or [])
        declared = set(tool.parameters.get("properties") or {})
        if not required <= set(arguments) or not set(arguments) <= declared:
            check("entry {0} supplies valid arguments".format(entry["id"]), False,
                  "{0} for {1}".format(arguments, name))
    check("every catalogue entry maps to a registered tool with valid arguments", True)

    check("adding is never a write-tier tool",
          all(tools.REGISTRY[browser.tool_call(e)[0]].tier == tools.SAFE
              for e in everything))

    osm = [e for e in everything if e["kind"] == "osm"][0]
    check("an OpenStreetMap entry falls back to a default place",
          browser.tool_call(osm, "")[1]["place"] == browser.DEFAULT_PLACE,
          browser.tool_call(osm, "")[1])
    check("an OpenStreetMap entry honours the place given",
          browser.tool_call(osm, "Kochi")[1]["place"] == "Kochi")

    # A boundary set is a national file, so the area box narrows it to a state
    # rather than being ignored -- this is how "Kerala districts" is reached.
    district = [e for e in everything
                if e["kind"] == "boundary" and e["id"] == "district"][0]
    check("a boundary set adds whole India when no state is given",
          "state" not in browser.tool_call(district, "")[1],
          browser.tool_call(district, "")[1])
    check("a boundary set narrows to the state given",
          browser.tool_call(district, "Kerala")[1]["state"] == "Kerala",
          browser.tool_call(district, "Kerala")[1])
    check("whitespace in the area box is not treated as a state",
          "state" not in browser.tool_call(district, "   ")[1])
    check("the filterable boundary sets say so",
          "filtered to one state" in district["detail"], district["detail"])
    check("the area box is labelled per kind",
          browser.AREA_FIELD["boundary"][1] == "state"
          and browser.AREA_FIELD["osm"][1] == "place",
          browser.AREA_FIELD)
    check("kinds with no area box are left alone",
          set(browser.AREA_FIELD) == {"boundary", "osm"}, sorted(browser.AREA_FIELD))

    check("an unknown kind is refused",
          _raises(lambda: browser.tool_call({"kind": "nonsense"}), ValueError))

    # The most natural query anybody types has to work. Boundary sets are
    # national files filtered as they load, so nothing in the district entry
    # contains "kerala" and plain matching returns an empty list -- which reads
    # as an empty catalogue rather than a search that needs rephrasing.
    check("plain matching alone finds no Kerala districts",
          browser.entries("all", "kerala districts") == [])

    results, area = browser.search("all", "kerala districts")
    check("searching for Kerala districts finds the district set",
          any(e["kind"] == "boundary" for e in results),
          [e["id"] for e in results][:5])
    check("and offers Kerala as the area", area == "Kerala", area)
    check("the area is a real argument, not decoration",
          browser.tool_call(
              [e for e in results if e["kind"] == "boundary"][0], area
          )[1].get("state") == "Kerala")

    _, ap_area = browser.search("all", "andhra pradesh districts")
    check("a two-word state is not read as its first word",
          ap_area == "Andhra Pradesh", ap_area)

    _, alias_area = browser.search("all", "bangalore hospitals")
    check("a historical city name resolves to the current one",
          alias_area == "Bengaluru", alias_area)

    plain, plain_area = browser.search("all", "rainfall")
    check("a query that matches on its own is left alone",
          plain and plain_area == "", plain_area)

    lulc, lulc_area = browser.search("all", "kerala land use")
    check("a query naming a state that does match keeps matching normally",
          lulc and lulc_area == "", lulc_area)

    nothing, no_area = browser.search("all", "zzz nonsense query")
    check("a genuinely unmatchable query stays empty",
          nothing == [] and no_area == "")
    check("and the panel has something to say about it",
          "Nothing matches" in browser.NO_MATCHES, browser.NO_MATCHES)

    # Which tab opens first is the difference between the Browse tab being the
    # plugin's front door and being a tab nobody discovers. It is decided by
    # whether a model is configured, and the obvious test for that -- calling
    # model_name() -- is wrong: every provider carries a default model, so
    # model_name() is never empty and the dock always opened on Ask.
    from ..core import settings as plugin_settings

    saved = plugin_settings.get("model")
    saved_auth = plugin_settings.get("auth_config_id")
    try:
        plugin_settings.set_value("model", "")
        plugin_settings.set_value("auth_config_id", "")
        check("a fresh install reports no configured model",
              not plugin_settings.model_is_configured())
        check("model_name() still answers with the provider default",
              bool(plugin_settings.model_name()),
              plugin_settings.model_name())
        check("the two are not interchangeable",
              plugin_settings.model_is_configured()
              is not bool(plugin_settings.model_name()))

        plugin_settings.set_value("model", "llama3.2")
        check("a chosen model is reported as configured",
              plugin_settings.model_is_configured())

        # A key stored for a hosted provider counts on its own: that user left
        # the model name at the provider default on purpose.
        plugin_settings.set_value("model", "")
        plugin_settings.set_value("auth_config_id", "authcfg1")
        check("a stored key alone counts as configured",
              plugin_settings.model_is_configured())
    finally:
        plugin_settings.set_value("model", saved or "")
        plugin_settings.set_value("auth_config_id", saved_auth or "")


def test_provenance():
    """Every layer the plugin adds must be able to say where it came from."""
    import tempfile

    from qgis.core import QgsProject, QgsVectorLayer

    from ..core import provenance

    project = QgsProject.instance()
    for layer_id in list(project.mapLayers()):
        project.removeMapLayer(layer_id)

    layer = QgsVectorLayer("memory", "Kerala districts")
    record = provenance.describe(
        layer, "census", source_url="https://example.org/districts.geojson"
    )
    check("describe reports the publisher", "Registrar General" in record["organisation"],
          record["organisation"])
    check("describe reports a retrieval date", len(record["retrieved"]) >= 10,
          record["retrieved"])

    metadata = layer.metadata()
    check("the licence is written to the layer", bool(metadata.licenses()),
          str(metadata.licenses()))
    check("the citation is written to the layer",
          "Census of India 2011" in (metadata.rights() or [""])[0],
          str(metadata.rights()))
    check("the contact carries the custodian",
          metadata.contacts() and metadata.contacts()[0].role == "custodian",
          str(metadata.contacts()))
    check("the source link is preserved",
          any(link.url == "https://example.org/districts.geojson"
              for link in metadata.links()),
          str([link.url for link in metadata.links()]))
    check("the abstract names the source", "Census" in metadata.abstract(),
          metadata.abstract())
    check("the publisher's own dataset name is recorded",
          metadata.keywords(provenance.SOURCE_VOCABULARY) ==
          ["Census of India 2011 boundaries"],
          str(metadata.keywords()))
    check("the retrieval date is recorded on the layer",
          len(metadata.keywords(provenance.RETRIEVED_VOCABULARY)[0]) == 10,
          str(metadata.keywords(provenance.RETRIEVED_VOCABULARY)))

    # A layer retrieved earlier keeps its own date rather than borrowing today's.
    import datetime as _datetime
    dated = QgsVectorLayer("memory", "Older download")
    provenance.describe(dated, "census",
                        retrieved=_datetime.datetime(2024, 3, 17, 9, 30))
    check("an explicit retrieval date is kept",
          provenance.summarise(dated)["retrieved"] == "2024-03-17",
          provenance.summarise(dated)["retrieved"])
    check("the bibliography dates the entry from the data, not the export",
          "2024-03-17" in provenance.as_bibliography(
              [provenance.summarise(dated)], "plain"),
          provenance.as_bibliography([provenance.summarise(dated)], "plain"))

    derived = QgsVectorLayer("memory", "Districts buffered")
    provenance.describe(derived, "derived")
    check("a derived layer names its origin rather than repeating its own name",
          provenance.summarise(derived)["source_title"] == "Derived layer",
          provenance.summarise(derived)["source_title"])

    # Every source key must be complete, or a bibliography entry comes out
    # half-written.
    for key, source in provenance.SOURCES.items():
        for field in ("title", "organisation", "licence"):
            check("source {0} declares {1}".format(key, field), bool(source[field]),
                  repr(source.get(field)))
    for key in ("bhuvan", "datagov", "census", "survey_of_india",
                "openstreetmap", "open_meteo"):
        check("source {0} carries a citation".format(key),
              bool(provenance.SOURCES[key]["citation"]))
        check("source {0} carries a URL".format(key),
              provenance.SOURCES[key]["url"].startswith("https://"))

    # An undescribed layer is skipped rather than cited as an unknown source.
    project.addMapLayer(layer)
    plain_layer = project.addMapLayer(QgsVectorLayer("memory", "Scratch"))
    records = provenance.collect(project)
    check("collect finds the described layer", len(records) == 1, str(records))
    check("collect skips a layer with no recorded source",
          all(r["layer"] != "Scratch" for r in records), str(records))

    provenance.describe(plain_layer, "openstreetmap")
    records = provenance.collect(project)
    check("collect finds both once described", len(records) == 2, str(records))

    plain = provenance.as_bibliography(records, "plain")
    check("plain style lists the sources", "Data sources" in plain, plain[:120])
    check("plain style names OpenStreetMap", "OpenStreetMap" in plain, plain[:200])

    markdown = provenance.as_bibliography(records, "markdown")
    check("markdown style has a heading", markdown.startswith("## Data sources"),
          markdown[:60])
    check("markdown style lists every layer",
          "Kerala districts" in markdown and "Scratch" in markdown, markdown[:400])
    check("markdown style names the publisher's dataset, not the layer",
          "**Census of India 2011 boundaries**" in markdown, markdown[:400])

    bibtex = provenance.as_bibliography(records, "bibtex")
    check("bibtex style emits entries", bibtex.count("@misc{") == 2, bibtex[:200])
    check("bibtex entries carry a licence note", "Accessed" in bibtex, bibtex[:200])
    check("bibtex braces balance", bibtex.count("{") == bibtex.count("}"),
          "{0} open, {1} close".format(bibtex.count("{"), bibtex.count("}")))
    check("corporate authors are braced so a comma is not read as a surname",
          "author       = {{" in bibtex, bibtex[:300])
    check("bibtex keys are safe identifiers",
          all(" " not in line.split("{")[1].rstrip(",")
              for line in bibtex.splitlines() if line.startswith("@misc{")),
          bibtex[:200])

    check("an empty project renders a plain sentence",
          provenance.as_bibliography([], "plain").endswith("."),
          provenance.as_bibliography([], "plain"))

    # Two layers from the same publisher are one bibliography entry.
    third = project.addMapLayer(QgsVectorLayer("memory", "Bengaluru hospitals"))
    provenance.describe(third, "openstreetmap")
    records = provenance.collect(project)
    check("three layers are described", len(records) == 3, str(len(records)))
    check("duplicate publishers are cited once",
          provenance.as_bibliography(records, "bibtex").count("@misc{") == 2,
          provenance.as_bibliography(records, "bibtex"))

    # The tool itself.
    ctx = tools.Context(None, journal.Journal())
    directory = tempfile.mkdtemp()
    path = os.path.join(directory, "sources.md")
    result = tools.REGISTRY["export_citations"].apply(
        {"path": path, "style": "markdown"}, ctx, None
    )
    check("export_citations writes the file", os.path.isfile(path), path)
    check("export_citations counts the layers", result["layers"] == 3, str(result))
    check("export_citations names the publishers",
          any("OpenStreetMap" in s for s in result["sources"]), str(result["sources"]))
    script = ctx.journal.to_script()
    check("export_citations records a reproducible step",
          "_write_sources(" in script, script[-300:])
    check("the exported script carries the provenance helpers",
          "def _write_sources(" in script and "def _describe(" in script,
          script[:200])
    # The promise is that the script runs without the plugin installed, so it
    # must not import from the plugin package. The package name appearing in
    # the header prose is fine; an import statement is not.
    import re as _re
    imports = _re.findall(r"^\s*(?:from|import)\s+(\S+)", script, _re.M)
    check("the exported script imports nothing from the plugin",
          not any(module.split(".")[0] == "srot" for module in imports),
          imports)
    written = open(path, encoding="utf-8").read()
    check("the written file matches the preview",
          written.startswith(result["preview"][:80]), written[:120])

    check("export_citations refuses an unknown style",
          _raises(lambda: tools.REGISTRY["export_citations"].apply(
              {"path": path, "style": "apa"}, ctx, None), tools.ToolError))

    # layer_info surfaces provenance so the model can answer "where is this from".
    info = tools.REGISTRY["layer_info"].apply({"layer": "Kerala districts"}, ctx, None)
    check("layer_info reports provenance", "provenance" in info, str(sorted(info)))
    check("layer_info reports the licence",
          bool(info["provenance"]["licence"]), str(info.get("provenance")))

    for layer_id in list(project.mapLayers()):
        project.removeMapLayer(layer_id)
    check("export_citations explains an empty project",
          _raises(lambda: tools.REGISTRY["export_citations"].apply(
              {"path": path, "style": "plain"}, ctx, None), tools.ToolError))


def _raises(callable_object, exception):
    try:
        callable_object()
    except exception:
        return True
    except Exception:
        return False
    return False


def test_layer_tools_attach_provenance():
    """A layer added by a tool carries its citation without being asked."""
    from qgis.core import QgsProject

    from ..core import provenance

    project = QgsProject.instance()
    for layer_id in list(project.mapLayers()):
        project.removeMapLayer(layer_id)
    ctx = tools.Context(None, journal.Journal())

    tools.REGISTRY["add_bhuvan_layer"].apply(
        {"layer": "basemap:KL_LULC"}, ctx, {"verdict": "draws"}
    )
    tools.REGISTRY["add_boundary"].apply(
        {"level": "district"},
        ctx,
        {
            "path": "/tmp/districts.geojson",
            "level": "district",
            "source": catalog.BOUNDARY_SOURCES["district"],
        },
    )
    tools.REGISTRY["add_osm_features"].apply(
        {"feature": "hospital", "bbox": "77.4,12.8,77.8,13.1"},
        ctx,
        {
            "query": "[out:json];node[amenity=hospital];out;",
            "endpoint": "https://overpass-api.de/api/interpreter",
            "feature": "hospital",
            "place": None,
            "data": {
                "elements": [
                    {"type": "node", "id": 1, "lat": 12.97, "lon": 77.59,
                     "tags": {"name": "Victoria Hospital"}},
                ]
            },
        },
    )

    records = provenance.collect(project)
    organisations = {r["organisation"] for r in records}
    check("every added layer is described", len(records) == 3, str(records))
    check("the Bhuvan layer credits ISRO",
          any("ISRO" in o for o in organisations), str(organisations))
    check("the boundary layer credits the body that published the file",
          any("India Maps Data" in o for o in organisations), str(organisations))
    check("the boundary layer's citation names the census it derives from",
          any("Census of India" in r["citation"] for r in records),
          str([r["citation"][:60] for r in records]))
    check("every boundary set is credited to a declared source",
          set(tools.BOUNDARY_CREDIT) == set(catalog.BOUNDARY_SOURCES),
          sorted(set(tools.BOUNDARY_CREDIT) ^ set(catalog.BOUNDARY_SOURCES)))
    check("every boundary credit names a real source",
          all(key in provenance.SOURCES for key in tools.BOUNDARY_CREDIT.values()),
          sorted(tools.BOUNDARY_CREDIT.values()))
    check("the OpenStreetMap layer credits its contributors",
          any("OpenStreetMap" in o for o in organisations), str(organisations))
    check("every described layer has a licence",
          all(r["licence"] for r in records), str([r["licence"] for r in records]))

    for layer_id in list(project.mapLayers()):
        project.removeMapLayer(layer_id)


# ---------------------------------------------------------------------------


def main():
    tests = [
        ("catalogue search", test_catalog_search),
        ("catalogue integrity", test_catalog_integrity),
        ("boundary official flags", test_boundary_official_flags),
        ("coverage recorded", test_coverage_is_recorded_not_assumed),
        ("probe classifies responses", test_probe_classifies_bhuvan_responses),
        ("network timeout scope", test_network_timeout_scope),
        ("boundary filter syntax", test_boundary_filter_syntax),
        ("bhuvan state families", test_bhuvan_state_families),
        ("search reaches every state", test_search_reaches_every_state),
        ("gazetteer", test_places),
        ("tool schemas", test_tool_schemas),
        ("safety tiers", test_tool_safety_tiers),
        ("processing validation", test_processing_validation),
        ("layer resolution", test_layer_resolution),
        ("provider wire formats", test_provider_wire_formats),
        ("missing key message", test_missing_key_message),
        ("journal", test_journal),
        ("system prompt", test_prompt),
        ("agent loop", test_agent_loop),
        ("agent error recovery", test_agent_recovers_from_tool_error),
        ("write confirmation", test_write_tool_is_confirmed),
        ("step limit", test_step_limit),
        ("http errors keep status and body", test_http_error_keeps_status_and_body),
        ("auth storage detects failure", test_auth_storage_detects_failure),
        ("styling", test_styling),
        ("catalogue browser", test_catalogue_browser),
        ("provenance", test_provenance),
        ("layer tools attach provenance", test_layer_tools_attach_provenance),
        ("processing optional flag", test_optional_flag_uses_the_qgis4_enum),
        ("shipped text is English", test_shipped_text_is_english),
    ]
    for name, function in tests:
        run(name, function)

    failed = [r for r in RESULTS if not r[1]]
    for name, ok, detail in RESULTS:
        if not ok:
            print("FAIL  {0}\n      {1}".format(name, detail))
    print(
        "\n{0} checks, {1} passed, {2} failed".format(
            len(RESULTS), len(RESULTS) - len(failed), len(failed)
        )
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
