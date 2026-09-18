---
name: Something went wrong
about: The plugin failed, crashed, or did the wrong thing
labels: bug
---

## What happened

<!-- What you asked for, and what the plugin did instead. -->

## The error

<!--
Two places worth checking, and the second is usually the useful one:

  * View > Panels > Log Messages, tab "Srot"
  * Plugins > Python Console, for a traceback

Paste it here. Full traceback beats a screenshot.
-->

```
paste here
```

## Setup

- QGIS version:
- Operating system:
- Model provider: <!-- Ollama / Anthropic / OpenAI / other -->
- Model:
- Plugin version:

## Things worth ruling out first

- [ ] The first Bhuvan layer of a session can take up to a minute — their
      capabilities document is 7–10 MB. Was it slow, or actually stuck?
- [ ] If a data.gov.in request failed, is your own API key set in the plugin
      settings? The plugin ships with no key; data.gov.in needs one.
- [ ] If the model called a tool with the wrong parameters and recovered on the
      next step, that is expected on small local models — worth mentioning
      which model, but it may not be a bug.
