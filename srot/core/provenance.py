# -*- coding: utf-8 -*-
"""Provenance for every layer the plugin adds.

A layer in a research project has to answer three questions later, often months
later and often to somebody else: where did this come from, when was it
retrieved, and under what licence may it be published.

QGIS has a place for exactly that. ``QgsLayerMetadata`` travels with the layer
inside the project file, shows up in the layer properties dialog, and exports
to ISO 19115 and Dublin Core. Filling it in at load time means the answers are
already there when the question is asked, and a citation list for a paper is a
matter of reading them back rather than reconstructing them from memory.
"""

import datetime

from qgis.core import (
    QgsAbstractMetadataBase,
    QgsBox3D,
    QgsDateTimeRange,
    QgsLayerMetadata,
)
from qgis.PyQt.QtCore import QDateTime

from . import log

#: Keyword vocabularies used to keep the publisher's own dataset name and the
#: retrieval date on the layer itself.
SOURCE_VOCABULARY = "srot:source"
RETRIEVED_VOCABULARY = "srot:retrieved"

#: Attribution required or requested by each publisher, and the terms the data
#: is offered under. Sources are cited the way the publisher asks to be cited.
SOURCES = {
    "bhuvan": {
        "title": "Bhuvan",
        "organisation": "National Remote Sensing Centre, ISRO",
        "licence": "Bhuvan terms of use",
        "url": "https://bhuvan.nrsc.gov.in",
        "citation": (
            "National Remote Sensing Centre, Indian Space Research Organisation. "
            "Bhuvan Indian Geo-Platform. https://bhuvan.nrsc.gov.in"
        ),
    },
    "datagov": {
        "title": "data.gov.in",
        "organisation": "Open Government Data Platform India",
        "licence": "Government Open Data Licence - India",
        "url": "https://data.gov.in",
        "citation": (
            "Open Government Data Platform India. https://data.gov.in "
            "Government Open Data Licence - India."
        ),
    },
    "census": {
        "title": "Census of India 2011 boundaries",
        "organisation": "Office of the Registrar General and Census Commissioner, India",
        "licence": "CC BY-SA 4.0 (community redistribution)",
        "url": "https://censusindia.gov.in",
        "citation": (
            "Office of the Registrar General and Census Commissioner, India. "
            "Census of India 2011 administrative boundaries, redistributed by "
            "the Datameet community. https://github.com/datameet/maps"
        ),
    },
    "district_current": {
        "title": "India district boundaries, Census 2011 updated through 2025",
        "organisation": "India Maps Data project",
        "licence": "Open data, derived from Census of India 2011 and later notifications",
        "url": "https://github.com/udit-001/india-maps-data",
        "citation": (
            "India Maps Data. District boundaries derived from Census of India "
            "2011 and subsequent district notifications through 2025. "
            "https://github.com/udit-001/india-maps-data"
        ),
    },
    "state_boundaries": {
        "title": "India state and union territory boundaries",
        "organisation": "geohacker/india project",
        "licence": "GADM-derived",
        "url": "https://github.com/geohacker/india",
        "citation": (
            "India state and union territory boundaries, GADM-derived, "
            "redistributed at https://github.com/geohacker/india"
        ),
    },
    "parliamentary_boundaries": {
        "title": "Parliamentary constituencies 2019",
        "organisation": "Datameet community",
        "licence": "CC BY-SA 4.0 (community redistribution)",
        "url": "https://github.com/datameet/maps",
        "citation": (
            "Parliamentary constituency boundaries 2019, compiled and "
            "redistributed by the Datameet community. "
            "https://github.com/datameet/maps"
        ),
    },
    "survey_of_india": {
        "title": "Survey of India national outline",
        "organisation": "Survey of India",
        "licence": "CC BY-SA 4.0 (community redistribution)",
        "url": "https://surveyofindia.gov.in",
        "citation": (
            "Survey of India national boundary, redistributed by the Datameet "
            "community. https://github.com/datameet/maps"
        ),
    },
    "openstreetmap": {
        "title": "OpenStreetMap",
        "organisation": "OpenStreetMap contributors",
        "licence": "Open Database License (ODbL) 1.0",
        "url": "https://www.openstreetmap.org/copyright",
        "citation": (
            "OpenStreetMap contributors. Data retrieved through the Overpass "
            "API. Available under the Open Database License. "
            "https://www.openstreetmap.org/copyright"
        ),
    },
    "open_meteo": {
        "title": "Open-Meteo",
        "organisation": "Open-Meteo",
        "licence": "CC BY 4.0",
        "url": "https://open-meteo.com",
        "citation": "Open-Meteo weather and air quality API. https://open-meteo.com",
    },
    "derived": {
        "title": "Derived layer",
        "organisation": "Produced in QGIS",
        "licence": "Follows the licence of its inputs",
        "url": "",
        "citation": "",
    },
}


def _now():
    return datetime.datetime.now()


def describe(
    layer,
    source_key,
    title=None,
    abstract=None,
    source_url=None,
    extra_links=None,
    retrieved=None,
):
    """Attach full metadata to a layer. GUI thread, alongside layer creation.

    Returns the record that was written, so a caller can report it without
    reading the metadata back.
    """
    source = SOURCES.get(source_key, SOURCES["derived"])
    stamp = retrieved or _now()

    metadata = QgsLayerMetadata()
    metadata.setIdentifier(source_url or layer.name())
    metadata.setTitle(title or layer.name())
    metadata.setType("dataset")
    metadata.setLanguage("eng")
    metadata.setAbstract(
        abstract
        or "{0}. Retrieved from {1} on {2} using Srot.".format(
            title or layer.name(), source["title"], stamp.strftime("%Y-%m-%d")
        )
    )
    metadata.setLicenses([source["licence"]])
    metadata.setRights([source["citation"]] if source["citation"] else [])

    # Keywords under a private vocabulary are the standards-conformant place to
    # keep the two facts a bibliography needs verbatim: the publisher's own name
    # for the dataset, and the day it was retrieved. Both survive a project
    # save, an ISO 19115 export and a hand edit of the layer's title.
    metadata.addKeywords(SOURCE_VOCABULARY, [source["title"]])
    metadata.addKeywords(RETRIEVED_VOCABULARY, [stamp.strftime("%Y-%m-%d")])

    if source["organisation"]:
        contact = QgsAbstractMetadataBase.Contact()
        contact.name = source["organisation"]
        contact.organization = source["organisation"]
        contact.role = "custodian"
        metadata.setContacts([contact])

    links = []
    for name, url in [(source["title"], source_url or source["url"])] + list(
        extra_links or []
    ):
        if not url:
            continue
        link = QgsAbstractMetadataBase.Link()
        link.name = name
        link.type = "WWW:LINK"
        link.url = url
        links.append(link)
    if links:
        metadata.setLinks(links)

    try:
        crs = layer.crs()
        if crs is not None and crs.isValid():
            metadata.setCrs(crs)
            extent = layer.extent()
            spatial = QgsLayerMetadata.SpatialExtent()
            spatial.extentCrs = crs
            spatial.bounds = QgsBox3D(
                extent.xMinimum(), extent.yMinimum(), 0,
                extent.xMaximum(), extent.yMaximum(), 0,
            )
            extent_object = QgsLayerMetadata.Extent()
            extent_object.setSpatialExtents([spatial])
            moment = QDateTime(stamp.year, stamp.month, stamp.day,
                               stamp.hour, stamp.minute, stamp.second)
            extent_object.setTemporalExtents([QgsDateTimeRange(moment, moment)])
            metadata.setExtent(extent_object)
    except Exception as exc:
        # The spatial extent is a nice-to-have; the citation is the point, so
        # a layer with an odd CRS still gets described.
        log.ignored("Recording the spatial extent of {0}".format(layer.name()), exc)

    try:
        layer.setMetadata(metadata)
    except Exception as exc:
        log.ignored("Attaching metadata to {0}".format(layer.name()), exc)

    return {
        "layer": layer.name(),
        "source": source["title"],
        "organisation": source["organisation"],
        "licence": source["licence"],
        "url": source_url or source["url"],
        "retrieved": stamp.strftime("%Y-%m-%d %H:%M"),
        "citation": source["citation"],
    }


def summarise(layer):
    """Read one layer's recorded provenance back, or ``None`` if it has none."""
    try:
        metadata = layer.metadata()
    except Exception:
        return None
    if metadata is None:
        return None
    rights = list(metadata.rights() or [])
    licences = list(metadata.licenses() or [])
    if not rights and not licences:
        return None
    contacts = [c.organization or c.name for c in (metadata.contacts() or [])]
    links = [link for link in (metadata.links() or []) if link.url]
    return {
        "layer": layer.name(),
        "title": metadata.title() or layer.name(),
        # A bibliography entry needs the publisher's own name for the dataset.
        # The layer's title is whatever the user called it in this project, so
        # the recorded keyword comes first.
        "source_title": (
            _keyword(metadata, SOURCE_VOCABULARY)
            or (links[0].name if links else "")
            or metadata.title()
            or layer.name()
        ),
        "organisation": contacts[0] if contacts else "",
        "licence": licences[0] if licences else "",
        "citation": rights[0] if rights else "",
        "url": links[0].url if links else "",
        "retrieved": _keyword(metadata, RETRIEVED_VOCABULARY),
        "abstract": metadata.abstract() or "",
    }


def _keyword(metadata, vocabulary):
    try:
        terms = metadata.keywords(vocabulary)
    except Exception:
        return ""
    return terms[0] if terms else ""


def collect(project):
    """Every described layer in the project, in a form fit for a bibliography."""
    records = []
    for layer in project.mapLayers().values():
        record = summarise(layer)
        if record is not None:
            records.append(record)
    records.sort(key=lambda record: record["layer"].lower())
    return records


def as_bibliography(records, style="plain"):
    """Render collected records as a citation list.

    ``style`` is ``plain``, ``markdown`` or ``bibtex``.
    """
    if not records:
        return "No described layers are loaded yet."

    # One entry per publisher, dated by the earliest layer taken from it, so a
    # reader can tell exactly which day's data the results rest on.
    seen = []
    for record in records:
        key = (record["citation"], record["organisation"])
        if not record["citation"]:
            continue
        existing = [s for s in seen if (s["citation"], s["organisation"]) == key]
        if existing:
            if record["retrieved"] and record["retrieved"] < existing[0]["retrieved"]:
                existing[0]["retrieved"] = record["retrieved"]
            continue
        seen.append(dict(record))

    today = _now().strftime("%Y-%m-%d")
    for record in seen:
        record.setdefault("retrieved", "")
        if not record["retrieved"]:
            record["retrieved"] = today

    if style == "bibtex":
        lines = []
        for index, record in enumerate(seen, 1):
            key = "".join(ch for ch in record["organisation"] if ch.isalnum())[:20] or "source"
            lines.append(
                "@misc{{{key}{n},\n"
                "  title        = {{{{{title}}}}},\n"
                "  author       = {{{{{org}}}}},\n"
                "  howpublished = {{\\url{{{url}}}}},\n"
                "  note         = {{{licence}. Accessed {date}}}\n"
                "}}".format(
                    key=key, n=index, title=record["source_title"],
                    org=record["organisation"], url=record["url"],
                    licence=record["licence"], date=record["retrieved"],
                )
            )
        return "\n\n".join(lines)

    if style == "markdown":
        lines = ["## Data sources", ""]
        for record in seen:
            lines.append(
                "- **{0}** — {1}. {2}. Accessed {3}. {4}".format(
                    record["source_title"], record["organisation"], record["licence"],
                    record["retrieved"], record["url"],
                )
            )
            if record["citation"]:
                lines.append("  > {0}".format(record["citation"]))
        lines += ["", "### Layers in this project", ""]
        for record in records:
            lines.append(
                "- `{0}` — {1}".format(record["layer"], record["source_title"])
            )
        return "\n".join(lines)

    lines = ["Data sources", "=" * 12, ""]
    for record in seen:
        lines.append(record["citation"] or record["source_title"])
        lines.append(
            "    Licence: {0}. Accessed {1}.".format(
                record["licence"], record["retrieved"]
            )
        )
        lines.append("")
    lines += ["Layers in this project", "-" * 22, ""]
    for record in records:
        lines.append("  {0}  ({1})".format(record["layer"], record["source_title"]))
    return "\n".join(lines)
