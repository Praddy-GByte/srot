# Srot

**It brings verified Indian government geodata into QGIS, each layer carrying
its own citation.** Browse the catalogue and add a layer with one click, or
describe what you want in a sentence.

```
You:   Map the live air quality monitoring stations in Delhi
Agent: ▶ search_india_data(query=air quality delhi)
       ✓ 3 catalogue matches
       ▶ add_datagov_layer(resource_id=3b01bcb8-..., filters={"city":"Delhi"})
       ✓ added 'Live air quality from CPCB / State PCB stations', 44 features
       ▶ style_layer(layer=..., mode=graduated, field=avg_value)
       ✓ graduated on avg_value into 5 classes
       Loaded 44 CPCB monitoring stations for Delhi and graduated them by
       PM2.5. The feed updates hourly.
```

---

## Why this exists

There are already eight or so AI agent plugins for QGIS, and none of them
carries an India-specific data source. Meanwhile the most-downloaded plugin in
this corner of the ecosystem is not an agent at all: one that did nothing but
load ISRO Bhuvan layers, downloaded over 4,600 times, last updated in 2020 and
capped at `qgisMaximumVersion=3.99` so it no longer installs on QGIS 4.

The demand is for Indian data in a sensible place. That is what this is for.

## What is different here

This is not trying to be a better general-purpose agent. It is trying to be the
one that knows India.

- **Indian data is built in.** 342 ISRO Bhuvan layers across 44 states and
  union territories, data.gov.in, Census 2011 boundaries, OpenStreetMap. Every
  endpoint was probed against a live server before it was written down.
- **It handles Indian naming.** An offline gazetteer with historical aliases,
  two incompatible Bhuvan state-code schemes kept straight, and Census-year
  corrections applied where the data needs them.
- **It does not run generated code.** Twenty declared tools, and Processing
  calls validated against the live algorithm registry before they execute.
- **Zero third-party Python dependencies.** Nothing to `pip install`.
- **Every session exports as a runnable PyQGIS script.**
- **API keys are encrypted** in the QGIS Authentication Manager, not written to
  a plaintext settings file.
- **QGIS 3.28 through 4.99**, verified on a real 3.34.4 build in CI.
- **No model required** to browse and add anything in the catalogue.

### 0. It works without a model

The **Browse** tab lists the whole catalogue -- every Bhuvan layer, every
boundary set, every data.gov.in resource, every OpenStreetMap preset -- as a
searchable list with an Add button. No provider, no model. Type
`kerala land use`, press Add, and the layer is on your map. Only the
data.gov.in feeds ask for a key, which the portal gives out free.

Boundary sets take an optional state, so `districts` plus `Kerala` gives you
Kerala's fifteen. OpenStreetMap presets take a place.

The **Ask** tab is the layer on top, for when one sentence is quicker than four
clicks: *"Load Kerala districts, every hospital in Kochi, and buffer the
districts by 5 km."* That one needs a model. The catalogue does not.

Both tabs call the same tools, so a layer added either way carries the same
provenance and appears in the same exported script.

### 1. India-first data catalogue

Every endpoint in the catalogue was probed before it was written down, and each
one is flagged as verified or documented-but-unverified.

- **ISRO Bhuvan WMS** — `bhuvan-vec1` (~7,800 layers) and `bhuvan-vec3`
  (~6,560). No token needed. The catalogue carries **342 layers across 44
  states and union territories**, recorded as state-wise *families* whose code
  lists were extracted from a real 7.5 MB `GetCapabilities` response, so it
  serves every state rather than only the ones that got tested.

  **How much of that actually draws, measured rather than assumed.** Bhuvan
  will serve a layer that is valid and completely empty, and it aborts any
  render its server takes over 60 seconds on. Sampling GetMap against the live
  service in September 2026, of 36 layers across 12 families: **23 drew, 10
  came back as a watermark-only tile, 3 timed out at state extent.** So each
  family carries a measured verdict:

  | Family | Verdict |
  |---|---|
  | LULC, roads, hydrology, groundwater (pre/post), river basins, LULC 1:50k | draws at state extent |
  | Railway networks | sparse — thin, and correctly so in states with little rail |
  | Village boundaries, railway stations | **empty** — the server returns a watermark-only tile |
  | Slope | **district only** — a group of per-district layers; Bhuvan aborts over a whole state, but it draws beautifully zoomed in (70% ink over a city-sized extent) |

  That works out to roughly **249 of 323 generated layers drawing at state
  extent**, and 74 that need a smaller extent or have nothing to show. The
  plugin does not paper over this: `add_bhuvan_layer` sends a small GetMap
  probe before it adds anything, and tells you which case you are in instead of
  leaving you staring at a blank canvas. `search_bhuvan_layers` reaches the
  remaining ~8,000, unprobed.
- **Bhuvan satellite imagery** via the `bhuvan-ras2` tilecache.
- **data.gov.in** — live CPCB station air quality (hourly), IMD gridded daily
  rainfall by district, the 30,284-record national hospital directory, crop
  production, mandi prices, and the GSI district resource map index.
- **District boundaries** — 760 districts by default (the 640 of Census 2011
  plus 120 created or revised through 2025, each carrying its vintage in a
  `year` field), the 641-district Census 2011 snapshot as a separate source,
  states, 2019 parliamentary constituencies, and a Survey of India–derived
  national outline.
- **OpenStreetMap** via Overpass — 26 presets, from hospitals to solar farms,
  for everything no government feed publishes cleanly.
- **Open-Meteo** for forecasts, with the modelled-vs-measured distinction made
  explicit rather than blurred.

Documented but unreachable from the build machine — India-WRIS, GSI Bhukosh,
the token-gated Bhuvan REST APIs, the IP-allowlisted IMD endpoints — are listed
as unverified rather than quietly presented as working.

### 2. It knows the traps

- **Bhuvan's WFS is switched off** and answers `HTTP 200` with an OWS exception
  body. A status-code check would call that success. The plugin never offers
  WFS.
- **Indian boundary files do not share a vintage, and guessing is worse than
  asking.** The Census 2011 snapshot genuinely predates the 2014 bifurcation:
  no Telangana, its 10 districts filed under "Andhra Pradesh". The current
  district set does have Telangana, with 34 districts. So the plugin does not
  assume — it runs the filter, and only falls back to selecting by district
  name if the file turns out to have no Telangana, then tells you it did.
  Rewriting the state name up front, which is the obvious implementation,
  silently hands you Andhra Pradesh's own districts.
- **OGR rejects `lower("field") = 'x'` on GeoJSON** and leaves the layer
  unfiltered; `ILIKE` is what actually works.
- **QGIS cuts network connections at 60 seconds by default.** Bhuvan's
  capabilities document and any city-sized Overpass query both run past that,
  so the plugin raises the ceiling for those calls and puts your setting back.
- **data.gov.in requires a key of its own**, free but separate. The plugin
  carries none: the portal's shared sample key is exhausted within a handful of
  calls across everyone using it, so shipping it would mean the first request
  usually fails for no visible reason. The plugin asks once and says where to
  get one. Bhuvan, the boundary sets and OpenStreetMap need no key at all.
- **Renamed cities** — Bangalore/Bengaluru, Allahabad/Prayagraj,
  Banaras/Varanasi, Gurgaon/Gurugram and 30 more resolve either way, offline,
  with no geocoding round-trip.
- **Bhuvan uses two incompatible state-code schemes.** The `mmi` workspace uses
  ISO 3166-2:IN, where `CT` is Chhattisgarh and `CH` is Chandigarh; `basemap`
  and `sdv` use an older scheme where Chhattisgarh is `CG1` and Telangana is
  `ts`. Crossing them silently serves the wrong state, so they are kept
  separate — and where a code genuinely cannot be resolved, it is documented as
  ambiguous rather than guessed.
- **The groundwater layers still use pre-2011 state names** — `ORISSA`,
  `PONDICHERRY`, `UTTARANCHAL`. Both the old and current names resolve.

### 3. Safety by construction

The agent **cannot write or run Python.** There is no `exec` in this codebase
and no code-execution tool. Everything it can do is one of 20 declared tools
with a JSON schema. Processing calls are validated against the live algorithm
registry — the algorithm must exist and every parameter name must be one it
actually declares — before anything executes. Tools that write to disk or
remove layers ask first.

This is a deliberate trade: a fixed set of capabilities, in exchange for the
guarantee that nothing runs on your machine except what those tools do.

### 4. Zero dependencies

Nothing to `pip install`. HTTP goes through `QgsBlockingNetworkRequest`, so
your QGIS proxy settings apply, your institution's proxy and certificate
configuration is honoured, and installation is a single unzip. On a locked-down
machine that is often the difference between using a plugin and filing a ticket.

### 5. Reproducible

Press **Save script** and the session becomes a standalone PyQGIS file that
re-runs the whole analysis without the plugin and without an LLM. Layers the
agent created are assigned real variable names, so the script actually runs —
it does not refer to session-specific layer ids that mean nothing on a re-run.
The test suite executes a generated script inside QGIS to prove it. That is
what turns a chat toy into something an institution can review, version and
repeat.

### 5a. Boundary provenance is explicit

India's [Geospatial Data Guidelines](https://onlinemaps.surveyofindia.gov.in/GeospatialGuidelines.aspx)
make Survey of India maps and SoI digital boundary data the standard for
political maps of India. So `add_boundary level='country'` uses an SoI-derived
outline by default, and the district, state and constituency sets — which are
community and GADM-derived — are flagged as analytical layers. When one of
those loads, the agent is told to pass that on to you rather than let it read
as authoritative.

### 5b. Every layer carries its citation

The moment a layer is added, the plugin writes the publisher, the licence, the
citation the publisher asks for, the source URL and the retrieval date into the
layer's own `QgsLayerMetadata`. That travels inside the `.qgz`, shows up under
**Layer Properties → Metadata**, and exports to ISO 19115 and Dublin Core like
any other QGIS metadata.

Ask for the sources at the end of a session and `export_citations` reads them
back as a text block, a Markdown section for a report, or BibTeX entries for a
reference manager — dated by the day each dataset was actually retrieved, not
by the day you exported the list:

```
@misc{NationalRemoteSensin1,
  title        = {Bhuvan},
  author       = {National Remote Sensing Centre, ISRO},
  howpublished = {\url{https://bhuvan-vec1.nrsc.gov.in/bhuvan/wms}},
  note         = {Bhuvan terms of use. Accessed 2026-09-09}
}
```

Six months later, when a reviewer asks which vintage of the district file a
figure was built on, the project answers for itself.

### 6. Works fully offline

Point it at a local Ollama model and no data leaves your machine — which
matters for government, PSU and defence users in India who cannot send data to
a US API. Anthropic, OpenAI and any OpenAI-compatible endpoint are also
supported.

---

## Install

**From a zip:** Plugins → Manage and Install Plugins → Install from ZIP.

**Manually:** unzip `srot/` into your QGIS profile's plugin folder.

| OS | Path |
|---|---|
| Windows | `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\` |
| macOS | `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/` |
| Linux | `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/` |

Then enable **Srot** in the plugin manager.

### Pick a model

Open **Web → Srot → Settings**.

- **Free and private:** install [Ollama](https://ollama.com), run
  `ollama pull qwen3:8b`, and leave the provider as Ollama. No key, no
  internet, nothing leaves your machine.
- **Best results:** choose Anthropic or OpenAI and paste a key. It is stored
  encrypted in the QGIS Authentication Manager, not in plaintext settings. You
  can use the `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` environment variable
  instead if you would rather skip the master-password prompt.

For the data.gov.in feeds you also need a free
[data.gov.in](https://data.gov.in) key: register, then My Account → APIs, and
paste it into the plugin settings. Bhuvan, the boundary sets and OpenStreetMap
work without one.

---

## Try it

```
Map the live air quality monitoring stations in Delhi
Load Maharashtra district boundaries and shade them by name
Get every hospital in Pune from OpenStreetMap
Show Bhuvan satellite imagery over Bengaluru
Show the districts of Telangana using Census 2011 boundaries
Add the river basins of India and style them by basin
Load Kerala district boundaries, then buffer them by 5 km
Make an A3 landscape print layout titled 'Rajasthan Districts'
```

---

## The tools

| Tool | What it does |
|---|---|
| `search_india_data` | Search the India catalogue by topic |
| `resolve_place` | Indian place name → bounding box, offline |
| `search_bhuvan_layers` | Search all ~7,800 Bhuvan layers |
| `add_bhuvan_layer` | Add a Bhuvan WMS layer or satellite imagery |
| `add_boundary` | Census districts, states, PCs, national outline |
| `add_datagov_layer` | Any data.gov.in resource, as points or a table |
| `add_osm_features` | OpenStreetMap features for a place |
| `get_weather` | Forecast and modelled air quality |
| `list_layers`, `layer_info` | Inspect the project |
| `zoom_to` | Zoom to a place, bbox or layer |
| `list_processing_algorithms`, `algorithm_help` | Discover Processing algorithms |
| `run_processing` | Run one, validated against the registry |
| `style_layer` | Single, categorized or graduated symbology |
| `create_print_layout`, `export_layout` | Cartography: A4/A3/A5 with legend and scale bar |
| `export_layer` | GPKG, SHP, GeoJSON, CSV, KML |
| `export_citations` | Source list for the project: plain text, Markdown or BibTeX |

Every one of these is reachable from the **Ask** tab. The add tools are also
reachable from the **Browse** tab, with no model configured.
| `remove_layer` | Remove a layer from the project |

---

## Architecture

```
srot/
├── core/       compat (Qt5/Qt6), net (QgsBlockingNetworkRequest),
│               settings (QgsAuthManager), journal (session → script)
├── india/      catalog (verified endpoints), places (gazetteer + aliases),
│               loaders (fetch/build split)
├── agent/      providers (3 wire formats), tools (registry + tiers),
│               prompts, loop (QgsTask state machine)
├── ui/         dock, settings dialog
└── tests/      673 offline checks, no QGIS needed
```

Two rules run through the whole codebase:

1. **Nothing slow on the GUI thread.** Every loader splits into `fetch_*`
   (network, safe inside a `QgsTask`) and `build_*` (layers, GUI thread only).
   The agent loop is a signal-driven state machine, not a `while` loop, for
   exactly this reason.
2. **A tool error is not a failure.** The error text goes back to the model as
   the tool result, so a wrong field name gets corrected on the next step
   instead of ending the run.

## Tests

Two suites, and they test different things.

```bash
python3 -m srot.tests.run          # 673 checks, no QGIS needed
```

Runs anywhere: a stub of the PyQGIS API is installed into `sys.modules` first.
Covers the catalogue and gazetteer, every tool schema, Processing parameter
validation, all three provider wire formats, boundary provenance, state coverage, the journal,
and end-to-end runs of the agent loop against a scripted model — error
recovery, write confirmation and the step limit included. It also enforces that
every shipped string is English.

```bash
QT_QPA_PLATFORM=offscreen python3 -m srot.tests.smoke_qgis   # 121 checks
```

Runs against a **real QGIS install**, and this is the one that matters before
you ship. It loads every module under real PyQGIS, runs real Processing
algorithms, applies real single/categorized/graduated renderers, builds and
exports a real A3 layout to PDF and PNG, writes and re-opens GeoPackage and
GeoJSON, round-trips an API key through the real encrypted `QgsAuthManager`,
builds the dock and settings dialog under real Qt, drives the whole agent loop
over the real `QgsTaskManager`, **executes a generated session script inside
QGIS**, and runs `initGui` / `unload` twice against a stand-in `iface` — the
call that decides whether the plugin survives being installed.

Verified green on QGIS 3.34.4 / Qt 5.15.13.

## How the sources behave

Worth knowing before you plan a session around one of them.

- **The first Bhuvan layer in a session takes longer.** Their GetCapabilities
  document is 7–10 MB, so allow up to a minute; every layer after it is served
  from cache.
- **Overpass geometry is built from nodes and ways.** Multipolygon relations
  are reported separately, and the layer states how many it set aside, so a
  count is never quietly short.
- **The catalogue lists what has been reached and verified.** India-WRIS and GSI
  Bhukosh are documented as sources with their endpoints recorded, and they are
  wired in once a live response confirms the schema.
- **OSM density follows population.** Coverage is dense in cities and lighter in
  rural districts, so a rural query is best paired with a government layer.
- **Model size shows up in first-try accuracy.** Parameter validation catches a
  wrong name before anything runs and hands the model the correct list, so small
  local models arrive at the same result in an extra step; larger models get
  there first time.

## Boundaries

Boundary data here comes from Census 2011, OpenStreetMap and GADM-derived
community files. It is for analysis. It is not an authoritative statement about
international borders.

## Licence

GPL-3.0-or-later. See `LICENSE`.

Data sources carry their own terms: Bhuvan (NRSC/ISRO), data.gov.in
(Government Open Data Licence – India), Datameet maps (CC-BY-SA),
OpenStreetMap (ODbL), Open-Meteo (CC-BY).
