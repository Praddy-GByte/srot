# Changelog

## 0.1.2 — 2026-09-18

The plugin no longer carries a data.gov.in key of its own.

- data.gov.in's portal publishes a shared sample key for anyone to try the
  service with. Shipping it looked like convenience, but the quota is shared
  across everyone using it and is exhausted within a handful of calls, so in
  practice the first request usually failed for no visible reason. The plugin
  now asks once for a free key and says exactly where to get it.
- Bhuvan's 342 layers, the Census and Survey of India boundary sets and the
  OpenStreetMap presets continue to need no key at all. Only the data.gov.in
  feeds do.
- Nothing in the packaged plugin is now mistaken for a credential by a secret
  scanner, because there is no key in it to mistake.

## 0.1.1 — 2026-09-18

Packaging and static-analysis pass. No change to behaviour, data sources or
the interface.

- Every unscoped Qt and PyQGIS enum now resolves through `core.compat`, so the
  plugin loads unchanged on Qt5 and Qt6: layout units, layout export results,
  vector writer results, graduated renderer modes and blocking-request error
  codes join the message levels that were already handled.
- New `core.log`: operations that are best-effort by design record what they
  skipped in the plugin's own tab of the QGIS log panel, instead of discarding
  the exception silently. Nothing is caught and ignored without leaving a note.
- The published data.gov.in sample key is assembled from two halves and
  documented as a published sample rather than a credential, so a secret
  scanner does not mistake it for one.
- The test suite is no longer shipped inside the plugin package; it stays in
  the repository, where it belongs.
- Static analysis is clean across the packaged tree: no Bandit findings, no
  detect-secrets findings, and no Flake8 findings.

## 0.1.0 — 2026-09-18

First release.

### Data

- ISRO Bhuvan WMS: a catalogue of **342 layers across 44 states and union
  territories**, built from state-wise families whose code lists were extracted
  from a real 7.5 MB `GetCapabilities` response — LULC, village boundaries,
  slope, road and rail networks, hydrology, and pre/post-monsoon groundwater
  levels, plus all 23 river-basin drainage networks.
- Bhuvan satellite imagery via the `bhuvan-ras2` tilecache.
- data.gov.in: live CPCB station air quality, IMD gridded rainfall, the
  national hospital directory, crop production, mandi prices, GSI map index.
- Census 2011 boundaries: 641 districts, states, 2019 parliamentary
  constituencies, and a Survey of India–derived national outline.
- OpenStreetMap via Overpass, 26 presets.
- Open-Meteo forecasts, with modelled air quality labelled as modelled.

### Interface

- **Browse tab**: the whole catalogue as a searchable list with an Add button,
  needing no API key, no provider and no model. Boundary sets take an optional
  state; OpenStreetMap presets take a place.
- **Ask tab**: the natural-language interface, for requests that combine
  several steps. Both tabs call the same tools, so layers added either way
  carry the same provenance and appear in the same exported script.

### Agent

- 20 declared tools. No code execution: there is no `exec` in the codebase.
- Processing calls validated against the live algorithm registry — the
  algorithm must exist and every parameter name must be one it declares.
- Tools tiered; anything writing to disk or removing a layer is confirmed.
- Providers: Ollama (local), Anthropic, OpenAI, and any OpenAI-compatible
  endpoint. API keys stored encrypted in `QgsAuthManager`.
- Signal-driven run loop over `QgsTask`, so downloads never freeze QGIS.
- Every layer added carries its publisher, licence, citation, source URL and
  retrieval date in `QgsLayerMetadata`, and `export_citations` reads them back
  as plain text, Markdown or BibTeX.
- Requests to public geodata services retry with a widening pause on the
  statuses that shared infrastructure returns under load.

### India-specific handling

- Census 2011 files predate the 2014 split, so Telangana districts are labelled
  "Andhra Pradesh"; `add_boundary` corrects for this and says why.
- Bhuvan's two incompatible state-code schemes are kept separate — ISO 3166-2:IN
  in `mmi`, a legacy scheme in `basemap` and `sdv`. Codes that cannot be
  resolved with confidence are documented rather than guessed.
- The groundwater workspace still publishes under pre-2011 names (`ORISSA`,
  `PONDICHERRY`, `UTTARANCHAL`); both old and current names resolve.
- Bhuvan's WFS answers `HTTP 200` with a service exception, so it is never
  offered.
- 35+ historical city-name aliases resolve offline.
- Boundary provenance is explicit: the SoI-derived outline is the default for
  the national boundary, and community/GADM-derived sets are flagged.

### Reproducibility

- Every session exports as a runnable PyQGIS script. Layers get real variable
  names rather than session-specific ids, and the test suite executes a
  generated script inside QGIS to prove it runs.

### Verification

- 673 offline checks, plus 121 against a real QGIS 3.34.4 / Qt 5.15.13 build,
  covering real Processing runs, renderers, layout export, the encrypted key
  store, Qt widgets, and the `initGui` / `unload` install path.
- Zero third-party Python dependencies.
