# -*- coding: utf-8 -*-
"""Session journal -> a re-runnable PyQGIS script.

Every competing AI plugin is a chat box: you get an answer, and no record of
how it was produced.  That makes them unusable for anything an institution has
to review or repeat.

Each tool records the PyQGIS it is equivalent to, and the journal assembles
those fragments into a script the user can save, read, diff and re-run without
the plugin or an LLM.
"""

import datetime
import re


HEADER = '''"""Recorded by Srot on {timestamp}.

This script reproduces the session below without the plugin or an LLM.
Run it from the QGIS Python console, or with PyQGIS standalone.

Layers the agent created are assigned to variables here, so later steps refer
to those variables rather than to session-specific layer ids. Layers that were
already open when the session started are looked up by name, so open the same
project first.

Session prompt(s):
{prompts}
"""

from qgis.core import (
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer,
    QgsCoordinateReferenceSystem,
    QgsRectangle,
    QgsSymbol,
    QgsSingleSymbolRenderer,
    QgsVectorFileWriter,
)
from qgis.PyQt.QtGui import QColor
from qgis import processing

project = QgsProject.instance()


def _existing(name):
    """Look up a layer that was already in the project when this was recorded."""
    matches = QgsProject.instance().mapLayersByName(name)
    if not matches:
        raise RuntimeError(
            "This script expects a layer named {{0!r}} to be open. "
            "Open the original project first.".format(name)
        )
    return matches[0]

'''


#: Emitted only when the session recorded provenance, so a script that never
#: touched it stays short. Written in plain PyQGIS with no import from the
#: plugin, so the script keeps its promise of running without it.
PROVENANCE_HELPERS = '''
from qgis.core import QgsAbstractMetadataBase, QgsLayerMetadata


def _describe(layer, title, organisation, licence, citation, url, retrieved):
    """Record where a layer came from, in the layer's own QGIS metadata."""
    metadata = QgsLayerMetadata()
    metadata.setIdentifier(url or layer.name())
    metadata.setTitle(layer.name())
    metadata.setType("dataset")
    metadata.setLanguage("eng")
    metadata.setAbstract(
        "{0}. Retrieved from {1} on {2}.".format(layer.name(), title, retrieved)
    )
    metadata.setLicenses([licence])
    metadata.setRights([citation] if citation else [])
    metadata.addKeywords("srot:source", [title])
    metadata.addKeywords("srot:retrieved", [retrieved])
    if organisation:
        contact = QgsAbstractMetadataBase.Contact()
        contact.name = organisation
        contact.organization = organisation
        contact.role = "custodian"
        metadata.setContacts([contact])
    if url:
        link = QgsAbstractMetadataBase.Link()
        link.name = title
        link.type = "WWW:LINK"
        link.url = url
        metadata.setLinks([link])
    layer.setMetadata(metadata)
    return layer


def _write_sources(path, style="plain"):
    """Write a source list for every described layer in the project."""
    entries, seen = [], []
    for layer in sorted(project.mapLayers().values(), key=lambda l: l.name().lower()):
        data = layer.metadata()
        if not (data.rights() or data.licenses()):
            continue
        organisation = ""
        for contact in data.contacts() or []:
            organisation = contact.organization or contact.name
            break
        links = [link for link in (data.links() or []) if link.url]
        source = (data.keywords("srot:source") or [layer.name()])[0]
        dates = data.keywords("srot:retrieved") or [""]
        entry = {
            "layer": layer.name(),
            "source": source,
            "organisation": organisation,
            "licence": (data.licenses() or [""])[0],
            "citation": (data.rights() or [""])[0],
            "url": links[0].url if links else "",
            "retrieved": dates[0],
        }
        entries.append(entry)
        if entry["citation"] and entry["citation"] not in [s["citation"] for s in seen]:
            seen.append(entry)

    lines = []
    if style == "bibtex":
        for index, entry in enumerate(seen, 1):
            key = "".join(c for c in entry["organisation"] if c.isalnum())[:20] or "source"
            lines.append(
                "@misc{%s%d,\\n  title        = {{%s}},\\n  author       = {{%s}},\\n"
                "  howpublished = {\\\\url{%s}},\\n  note         = {%s. Accessed %s}\\n}\\n"
                % (key, index, entry["source"], entry["organisation"], entry["url"],
                   entry["licence"], entry["retrieved"])
            )
    elif style == "markdown":
        lines.append("## Data sources\\n")
        for entry in seen:
            lines.append("- **{0}** — {1}. {2}. Accessed {3}. {4}".format(
                entry["source"], entry["organisation"], entry["licence"],
                entry["retrieved"], entry["url"]))
            if entry["citation"]:
                lines.append("  > " + entry["citation"])
        lines.append("\\n### Layers in this project\\n")
        for entry in entries:
            lines.append("- `{0}` — {1}".format(entry["layer"], entry["source"]))
    else:
        lines += ["Data sources", "=" * 12, ""]
        for entry in seen:
            lines.append(entry["citation"] or entry["source"])
            lines.append("    Licence: {0}. Accessed {1}.".format(
                entry["licence"], entry["retrieved"]))
            lines.append("")
        lines += ["Layers in this project", "-" * 22, ""]
        for entry in entries:
            lines.append("  {0}  ({1})".format(entry["layer"], entry["source"]))

    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\\n".join(lines) + "\\n")
    return path

'''


class Journal:
    """Collects prompts, narrative steps and PyQGIS fragments.

    It also assigns a stable Python variable name to every layer the agent
    creates.  Without that, an exported script would refer to layers by their
    ``QgsProject`` id -- which is generated per session and means nothing when
    the script is re-run, so the script would not actually reproduce anything.
    """

    def __init__(self):
        self._entries = []
        self._prompts = []
        self._aliases = {}
        self._alias_names = set()

    def clear(self):
        self._entries = []
        self._prompts = []
        self._aliases = {}
        self._alias_names = set()

    def alias(self, layer_id, hint="layer"):
        """Return (and remember) the variable name standing for this layer."""
        if layer_id in self._aliases:
            return self._aliases[layer_id]
        base = re.sub(r"\W+", "_", str(hint)).strip("_").lower()[:28] or "layer"
        if base[0].isdigit():
            base = "layer_" + base
        name, counter = base, 1
        while name in self._alias_names:
            counter += 1
            name = "{0}_{1}".format(base, counter)
        self._aliases[layer_id] = name
        self._alias_names.add(name)
        return name

    def known(self, layer_id):
        return layer_id in self._aliases

    def reference(self, layer):
        """A runnable expression for a layer: a variable if we made it, else a lookup."""
        if self.known(layer.id()):
            return self._aliases[layer.id()]
        return "_existing({0!r})".format(layer.name())

    def add_prompt(self, text):
        self._prompts.append(text)
        self._entries.append(("prompt", text))

    def add_step(self, tool_name, code, comment=None):
        """Record one executed tool.

        :param tool_name: the agent tool that ran.
        :param code: PyQGIS source that reproduces it (may be empty for
            read-only tools).
        :param comment: a human-readable one-liner.
        """
        self._entries.append(("step", (tool_name, code or "", comment or "")))

    def add_note(self, text):
        self._entries.append(("note", text))

    def is_empty(self):
        return not any(kind == "step" for kind, _ in self._entries)

    def step_count(self):
        return sum(1 for kind, _ in self._entries if kind == "step")

    def _uses_provenance(self):
        """Whether any recorded step calls a provenance helper."""
        return any(
            kind == "step" and ("_describe(" in payload[1] or "_write_sources(" in payload[1])
            for kind, payload in self._entries
        )

    def to_script(self):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        prompts = "\n".join("  - " + p.replace('"""', "'''") for p in self._prompts) or "  (none)"
        lines = [HEADER.format(timestamp=timestamp, prompts=prompts)]
        if self._uses_provenance():
            lines.append(PROVENANCE_HELPERS)

        step_no = 0
        for kind, payload in self._entries:
            if kind == "prompt":
                lines.append("# ==> user: {0}\n".format(_one_line(payload)))
            elif kind == "note":
                lines.append("# {0}\n".format(_one_line(payload)))
            elif kind == "step":
                tool_name, code, comment = payload
                step_no += 1
                lines.append("# --- step {0}: {1}".format(step_no, tool_name))
                if comment:
                    lines.append("# {0}".format(_one_line(comment)))
                if code.strip():
                    lines.append(code.strip())
                else:
                    lines.append("# (read-only tool, nothing to reproduce)")
                lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def to_markdown(self):
        out = ["# Srot session", ""]
        step_no = 0
        for kind, payload in self._entries:
            if kind == "prompt":
                out.append("**You:** {0}".format(payload))
                out.append("")
            elif kind == "note":
                out.append("> {0}".format(payload))
                out.append("")
            elif kind == "step":
                tool_name, code, comment = payload
                step_no += 1
                out.append("{0}. `{1}` - {2}".format(step_no, tool_name, comment))
        out.append("")
        return "\n".join(out)


def _one_line(text):
    return " ".join(str(text).split())[:400]
