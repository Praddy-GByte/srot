# Contributing

Thanks for looking. The most useful contributions to this project are probably
not code.

## The single most valuable thing you can do

**Tell us a layer or dataset that should be in the catalogue, and isn't.**

The catalogue is the product. If you work with Indian geodata and reach for
something the plugin cannot find, that is a bug in the catalogue, and it is the
kind of bug only someone doing the work can report. Open a
[data source issue](../../issues/new?template=data_source.md) with the source
and, if you have it, the endpoint.

## Two test suites, and what each is for

```bash
python3 -m srot.tests.run
```

Runs anywhere, needs no QGIS. A stub of the PyQGIS API is installed into
`sys.modules` first. Use it while working on the catalogue, the gazetteer, the
agent loop or the provider wire formats. It is fast, so run it constantly.

```bash
QT_QPA_PLATFORM=offscreen python3 -m srot.tests.smoke_qgis
```

Runs against a **real QGIS install**, and it is the one that decides whether a
change is safe to ship. It exercises real Processing algorithms, real
renderers, real layout export, the real authentication manager, real Qt
widgets, and `initGui` / `unload`.

On Ubuntu 24.04:

```bash
sudo apt-get install python3-qgis python3-pyqt5.sip
```

Both suites run in CI on every push. A change that only passes the offline
suite is not verified.

## Rules that are not negotiable

**No third-party Python dependencies.** Not one. Dependency installation is the
main reason QGIS plugins fail for users, and staying at zero is a feature.
HTTP goes through `QgsBlockingNetworkRequest` so the user's proxy settings
apply; `requests` and `urllib` are not options.

**The agent never executes generated code.** There is no `exec` in this
codebase and there will not be one. New capability is added as a declared tool
in `agent/tools.py` with a JSON schema, and anything touching Processing
validates against the live algorithm registry first.

**Nothing slow on the GUI thread.** Loaders split into `fetch_*` (network,
safe inside a `QgsTask`) and `build_*` (layers, GUI thread only). If you add a
loader, keep that split.

**Do not invent an endpoint or a layer name.** Every entry in
`india/catalog.py` and `india/bhuvan_layers.py` was extracted from a real
server response. If you add one, say in the pull request how you verified it.
Sources that are documented but unreachable belong in `UNVERIFIED_SOURCES`,
labelled as such, not presented as working.

**Shipped text is English.** The offline suite enforces this.

## Adding a Bhuvan layer family

Most Bhuvan datasets are one layer repeated per state. Rather than listing them
by hand, add a family to `india/bhuvan_layers.py`: a name pattern plus the
exact set of state codes that exist on the server. Get the codes from a real
capabilities response:

```bash
curl -s --compressed \
  "https://bhuvan-vec1.nrsc.gov.in/bhuvan/wms?service=WMS&version=1.1.1&request=GetCapabilities" \
  -o caps.xml
```

Note that Bhuvan uses two different state-code schemes: `mmi` uses ISO
3166-2:IN (`CT` Chhattisgarh, `CH` Chandigarh, `UT` Uttarakhand, `TG`
Telangana), while `basemap` and `sdv` use an older in-house scheme (`CG1`,
`UK`, `ts`). Crossing them silently serves the wrong state. If a code cannot be
resolved with confidence, put it in `AMBIGUOUS` rather than guessing.

## Style

PEP 8, comments and identifiers in English, and comments that explain *why*
rather than restate the code. Match the surrounding file.

## Pull requests

Say what you changed, how you verified it, and which suites you ran. If you
touched anything QGIS-facing, the smoke test result matters more than the
offline one.
