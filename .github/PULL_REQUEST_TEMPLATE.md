## What this changes

<!-- One or two sentences. -->

## How it was verified

- [ ] `python3 -m srot.tests.run`
- [ ] `QT_QPA_PLATFORM=offscreen python3 -m srot.tests.smoke_qgis`
- [ ] Loaded in a real QGIS window and clicked through it

<!-- If you touched anything QGIS-facing, the smoke test result is the one that counts. -->

## If this adds a data source

- [ ] The endpoint or layer name came from a real server response, not from memory
- [ ] How I verified it: <!-- e.g. GetCapabilities on 2026-09-09, HTTP 200 with N layers -->
- [ ] Anything unreachable is in `UNVERIFIED_SOURCES` and labelled, not presented as working

## Checks

- [ ] No new third-party Python dependencies
- [ ] No code execution added — new capability is a declared tool with a schema
- [ ] Network work stays in `fetch_*`; layer and widget work stays on the GUI thread
- [ ] Shipped text is English
