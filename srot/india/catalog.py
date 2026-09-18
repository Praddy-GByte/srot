# -*- coding: utf-8 -*-
"""The India data catalogue.

Every endpoint below was probed before it was written down.  Entries carry a
``verified`` flag so the agent can tell the user the difference between "this
was tested and works" and "this is documented but we could not reach it from
the build machine".

Sources and their status, as of 2026-09:

* Bhuvan WMS (bhuvan-vec1 / bhuvan-vec3) - VERIFIED. GeoServer, no auth,
  WMS 1.1.1 and 1.3.0, GetMap and GetFeatureInfo both confirmed working.
  ~7,800 layers on vec1 and ~6,560 on vec3.
* Bhuvan tilecache (bhuvan-ras2) - VERIFIED. WMS-C satellite imagery, no auth.
  GetMap 302-redirects to a JPEG, so redirect following must stay enabled.
* Bhuvan WFS - DISABLED server-side. It answers HTTP 200 with an OWS
  ServiceUnavailable exception, so a status-code check is not enough. We do
  not offer it.
* data.gov.in - VERIFIED. Tyk gateway, api-key query parameter.
* Datameet / udit-001 / geohacker boundary files on GitHub - VERIFIED by byte
  count.
* Overpass - the query syntax is verified; India coverage was not reachable
  from the build machine but the endpoint is the standard public one.
* Open-Meteo - VERIFIED, no key.
* India-WRIS and GSI Bhukosh - documented but UNVERIFIED (unreachable from the
  build machine, most likely a geo-block). Marked as such.
"""

from . import bhuvan_layers

# ---------------------------------------------------------------------------
# Bhuvan WMS
# ---------------------------------------------------------------------------

BHUVAN_WMS_HOSTS = [
    {
        "id": "vec1",
        "url": "https://bhuvan-vec1.nrsc.gov.in/bhuvan/wms",
        "label": "Bhuvan vec1 (primary, ~7800 layers)",
        "verified": True,
    },
    {
        "id": "vec3",
        "url": "https://bhuvan-vec3.nrsc.gov.in/bhuvan/wms",
        "label": "Bhuvan vec3 (AMRUT, NREGA, NHAI, urban)",
        "verified": True,
    },
    {
        "id": "vec2",
        "url": "https://bhuvan-vec2.nrsc.gov.in/bhuvan/wms",
        "label": "Bhuvan vec2 (documented by NRSC, unverified here)",
        "verified": False,
    },
]

BHUVAN_TILECACHE = "https://bhuvan-ras2.nrsc.gov.in/tilecache/tilecache.py"

#: Curated shortlist.  Bhuvan's GetCapabilities is 7-10 MB and can take 45
#: seconds, which feels broken inside a dialog, so the agent works from this
#: list first and only fetches capabilities when the user explicitly searches
#: for something not here.
BHUVAN_LAYERS = [
    # --- imagery (tilecache, not GeoServer) --------------------------------
    {
        "name": "bhuvan_imagery",
        "title": "Bhuvan satellite imagery (national mosaic)",
        "host": "tilecache",
        "theme": "imagery",
        "keywords": ["satellite", "imagery", "basemap", "image", "satellite image"],
    },
    {
        "name": "bhuvan_imagery_2018to20",
        "title": "Bhuvan satellite imagery 2018-2020",
        "host": "tilecache",
        "theme": "imagery",
        "keywords": ["satellite", "imagery", "2018", "2020", "historic"],
    },
    # --- administrative ----------------------------------------------------
    {
        "name": "basemap:admin_group_ntl",
        "title": "India administrative boundaries (national)",
        "host": "vec1",
        "theme": "admin",
        "keywords": ["admin", "boundary", "administrative"],
    },
    {
        "name": "basemap:inida_state_ql_new",
        "title": "India state boundaries (note: layer name is misspelt upstream)",
        "host": "vec1",
        "theme": "admin",
        "keywords": ["state", "boundary", "states"],
    },
    {
        "name": "basemap:village",
        "title": "Village boundaries",
        "host": "vec1",
        "theme": "admin",
        "keywords": ["village", "revenue village"],
    },
    # --- land use / land cover --------------------------------------------
    {
        "name": "basemap:AP_LULC",
        "title": "Andhra Pradesh land use / land cover",
        "host": "vec1",
        "theme": "lulc",
        "keywords": ["lulc", "land use", "land cover", "andhra"],
    },
    {
        "name": "moef:BR_LULC50K_1112",
        "title": "Bihar LULC 1:50k (2011-12)",
        "host": "vec1",
        "theme": "lulc",
        "keywords": ["lulc", "bihar", "land use"],
    },
    {
        "name": "moef:MP_LULC50K_1112_GB",
        "title": "Madhya Pradesh LULC 1:50k (2011-12)",
        "host": "vec1",
        "theme": "lulc",
        "keywords": ["lulc", "madhya pradesh", "mp", "land use"],
    },
    {
        "name": "moef:UK_LULC50K_1112",
        "title": "Uttarakhand LULC 1:50k (2011-12)",
        "host": "vec1",
        "theme": "lulc",
        "keywords": ["lulc", "uttarakhand", "land use"],
    },
    {
        "name": "timeseries:lulc250k_tif",
        "title": "LULC 1:250k time series",
        "host": "vec3",
        "theme": "lulc",
        "keywords": ["lulc", "time series", "change", "250k"],
    },
    # --- hydrology ---------------------------------------------------------
    {
        "name": "hydrology:BASIN",
        "title": "River basins of India",
        "host": "vec1",
        "theme": "water",
        "keywords": ["basin", "river", "watershed"],
    },
    {
        "name": "hydrology:BDRN_1_Indus",
        "title": "Indus basin drainage network",
        "host": "vec1",
        "theme": "water",
        "keywords": ["indus", "sindhu", "drainage", "river"],
    },
    {
        "name": "hydrology:BDRN_12_Narmada",
        "title": "Narmada basin drainage network",
        "host": "vec1",
        "theme": "water",
        "keywords": ["narmada", "drainage", "river"],
    },
    {
        "name": "hydrology:BDRN_13_Tapi",
        "title": "Tapi basin drainage network",
        "host": "vec1",
        "theme": "water",
        "keywords": ["tapi", "tapti", "drainage", "river"],
    },
    {
        "name": "basemap:waterbody_DEM",
        "title": "Water bodies derived from DEM",
        "host": "vec1",
        "theme": "water",
        "keywords": ["water body", "lake", "reservoir"],
    },
    # --- terrain -----------------------------------------------------------
    {
        "name": "sdv:ap_slope",
        "title": "Andhra Pradesh slope",
        "host": "vec1",
        "theme": "terrain",
        "keywords": ["slope", "terrain", "andhra"],
    },
    {
        "name": "sdv:ka_slope",
        "title": "Karnataka slope",
        "host": "vec1",
        "theme": "terrain",
        "keywords": ["slope", "terrain", "karnataka"],
    },
    # --- urban / schemes ---------------------------------------------------
    {
        "name": "nuis:AP_DH_admin_boundary",
        "title": "NUIS urban admin boundary (Andhra Pradesh)",
        "host": "vec1",
        "theme": "urban",
        "keywords": ["urban", "nuis", "city", "municipal"],
    },
    {
        "name": "sisdpv2:AP_Guntur_lulc_v2",
        "title": "SISDP-II Guntur LULC",
        "host": "vec1",
        "theme": "lulc",
        "keywords": ["guntur", "sisdp", "lulc", "village level"],
    },
]

BHUVAN_WORKSPACES = {
    "nuis": "National Urban Information System (2988 layers)",
    "sisdpv2": "Space based Information Support for Decentralised Planning, phase II (1274)",
    "sisdp": "SISDP phase I (989)",
    "sdv": "Spatial Data Visualiser - slope, terrain, taluk HQs (900)",
    "mmi": "Multi-hazard / mapping (424)",
    "basemap": "Base maps, admin boundaries, LULC (272)",
    "twris": "Telangana water resources (236)",
    "gw": "Groundwater (179)",
    "cadastral": "Cadastral layers (143)",
    "hydrology": "River basins and drainage networks",
    "moef": "Ministry of Environment, Forest and Climate Change LULC",
    "india_wris": "Water Resources Information System layers",
    "coastal": "Coastal zone layers",
    "asi": "Archaeological Survey of India monuments",
    "postal": "Postal geography",
    "amrut_ph1": "AMRUT phase 1 city layers (3207, on vec3)",
    "cdma": "Commissioner and Director of Municipal Administration (2910, on vec3)",
    "nrega": "MGNREGA assets (on vec3)",
    "nhai_data": "National Highways Authority of India (on vec3)",
}

# ---------------------------------------------------------------------------
# data.gov.in
# ---------------------------------------------------------------------------

DATAGOV_BASE = "https://api.data.gov.in/resource/{resource_id}"
DATAGOV_LIST = "https://api.data.gov.in/lists"

DATAGOV_RESOURCES = [
    {
        "id": "3b01bcb8-0b14-4abf-b6f2-c1bfd384ba69",
        "title": "Live air quality from CPCB / State PCB stations",
        "org": "CPCB",
        "lat_field": "latitude",
        "lon_field": "longitude",
        "label_field": "station",
        "filters": ["state", "city", "station", "pollutant_id"],
        "notes": "Updated hourly. pollutant_id is one of PM2.5, PM10, NO2, SO2, CO, OZONE, NH3.",
        "keywords": ["air quality", "aqi", "pollution", "pm2.5", "pm10", "cpcb"],
        "verified": True,
    },
    {
        "id": "37670b6f-c236-49a7-8cd7-cc2dc610e32d",
        "title": "National hospital directory with geocodes",
        "org": "Ministry of Health and Family Welfare",
        "location_field": "_location_coordinates",
        "label_field": "hospital_name",
        "filters": ["state", "district"],
        "notes": "30,284 records. Coordinates arrive as a single 'lat, lon' string.",
        "keywords": ["hospital", "health", "clinic", "medical"],
        "verified": True,
    },
    {
        "id": "97a27e69-e488-402d-b017-9ed363da7d84",
        "title": "Daily rainfall by district (IMD gridded model)",
        "org": "India Meteorological Department",
        "filters": ["_state_", "district", "date"],
        "notes": "District-level, join to the Census district boundaries by name.",
        "keywords": ["rainfall", "rain", "monsoon", "imd", "precipitation"],
        "verified": True,
    },
    {
        "id": "9ef84268-d588-465a-a308-a864a43d0070",
        "title": "Daily mandi commodity prices",
        "org": "Ministry of Agriculture",
        "filters": ["state", "district", "market", "commodity"],
        "notes": "Market-level daily prices; geocode by market name if needed.",
        "keywords": ["mandi", "price", "crop", "commodity", "agriculture"],
        "verified": True,
    },
    {
        "id": "f20d7d45-e3d8-4603-bc79-15a3d0db1f9a",
        "title": "Production of different crops 2019-20",
        "org": "Ministry of Agriculture",
        "filters": ["state", "district"],
        "notes": "District-level crop tonnage; join to district boundaries.",
        "keywords": ["crop", "production", "agriculture", "yield"],
        "verified": True,
    },
    {
        "id": "a5d860b4-785b-4d09-b642-23c5a96e0daa",
        "title": "GSI district resource maps 1997-2022 (PDF index)",
        "org": "Geological Survey of India",
        "filters": ["district_name", "state_names"],
        "notes": "Metadata plus a URL to each map PDF. 600 records.",
        "keywords": ["geology", "mineral", "gsi", "bhukosh", "resource map"],
        "verified": True,
    },
    {
        "id": "7d208ae4-5d65-47ec-8cb8-2a7a7ac89f8c",
        "title": "Hospital directory with geocodes (Sep 2015)",
        "org": "Ministry of Health and Family Welfare",
        "lat_field": "_googlemapcorridinate_lati",
        "lon_field": "_googlemapcorridinate_longi",
        "label_field": "hospital_name",
        "filters": ["district"],
        "notes": "Smaller, older companion to the national directory.",
        "keywords": ["hospital", "health", "2015"],
        "verified": True,
    },
]

# ---------------------------------------------------------------------------
# Boundaries (vector downloads)
# ---------------------------------------------------------------------------

BOUNDARY_SOURCES = {
    "district": {
        "title": "India districts (760, Census 2011 updated to 2025)",
        "url": "https://raw.githubusercontent.com/udit-001/india-maps-data/main/geojson/india.geojson",
        "format": "geojson",
        "fields": ["district", "dt_code", "st_nm", "st_code", "year"],
        "join_field": "district",
        "state_field": "st_nm",
        "licence": "Open data, derived from Census of India 2011 and later notifications",
        "notes": (
            "4.1 MB, CRS84. 760 districts: the 640 of Census 2011 plus 120 "
            "created or revised between 2012 and 2025, with a 'year' field "
            "recording each one's vintage. This set is post-bifurcation -- it "
            "carries Telangana with its own 34 districts, and Ladakh separately "
            "from Jammu and Kashmir. Use it unless you specifically need the "
            "2011 snapshot. Cleanest schema for joining to data.gov.in district data."
        ),
        "official_boundary": False,
        "verified": True,
    },
    "district_datameet": {
        "title": "India districts (Datameet Census 2011 shapefile)",
        "url": "https://raw.githubusercontent.com/datameet/maps/master/Districts/Census_2011/2011_Dist.shp",
        "sidecars": [".dbf", ".shx", ".prj"],
        "format": "shapefile",
        "fields": ["DISTRICT", "ST_NM", "ST_CEN_CD", "DT_CEN_CD", "censuscode"],
        "join_field": "DISTRICT",
        "state_field": "ST_NM",
        "licence": "CC-BY-SA",
        "notes": (
            "10.2 MB, 641 features. The Census 2011 snapshot, and genuinely "
            "pre-bifurcation: it has no Telangana at all, and files those 10 "
            "districts under ST_NM='Andhra Pradesh'. Ask for Telangana and the "
            "plugin selects them by district name and tells you why. Use this "
            "only when you need the 2011 snapshot; otherwise use level='district'. "
            "No .cpg is published, so the encoding is set explicitly."
        ),
        "official_boundary": False,
        "verified": True,
    },
    "state": {
        "title": "India states and union territories",
        "url": "https://raw.githubusercontent.com/geohacker/india/master/state/india_state.geojson",
        "format": "geojson",
        "fields": ["NAME_1", "ID_1"],
        "join_field": "NAME_1",
        "state_field": "NAME_1",
        "licence": "GADM-derived",
        "notes": "23 MB - large. Prefer the district file and dissolve if you can.",
        "official_boundary": False,
        "verified": True,
    },
    "parliamentary": {
        "title": "Parliamentary constituencies 2019 (simplified)",
        "url": (
            "https://raw.githubusercontent.com/datameet/maps/master/"
            "parliamentary-constituencies/india_pc_2019_simplified.geojson"
        ),
        "format": "geojson",
        "fields": ["pc_id", "st_code", "st_name", "pc_no", "pc_name", "pc_name_hi", "pc_category"],
        "join_field": "pc_name",
        "state_field": "st_name",
        "licence": "CC-BY-SA",
        "notes": "1.9 MB. pc_name_hi carries the Devanagari constituency name.",
        "official_boundary": False,
        "verified": True,
    },
    "country": {
        "title": "India national outline (Survey of India derived)",
        "url": "https://raw.githubusercontent.com/datameet/maps/master/Country/india-soi.geojson",
        "format": "geojson",
        "fields": [],
        "join_field": None,
        "state_field": None,
        "licence": "CC-BY-SA",
        "official_boundary": True,
        "notes": (
            "12.3 MB, derived from Survey of India. This is the default national "
            "outline because the Geospatial Data Guidelines make SoI maps and SoI "
            "digital boundary data the standard for political maps of India."
        ),
        "verified": True,
    },
    "country_osm": {
        "title": "India national outline (OpenStreetMap derived)",
        "url": "https://raw.githubusercontent.com/datameet/maps/master/Country/india-osm.geojson",
        "format": "geojson",
        "fields": [],
        "join_field": None,
        "state_field": None,
        "licence": "CC-BY-SA / ODbL",
        "official_boundary": False,
        "notes": (
            "6.7 MB. Community-mapped outline. Its depiction of disputed "
            "boundaries differs from Survey of India. Analytical use only."
        ),
        "verified": True,
    },
}

# ---------------------------------------------------------------------------
# OpenStreetMap via Overpass
# ---------------------------------------------------------------------------

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

#: Admin levels as tagged in India.
OSM_ADMIN_LEVELS = {"country": 2, "state": 4, "district": 5, "subdistrict": 6}

OSM_PRESETS = {
    "hospital": ('["amenity"="hospital"]', "node,way,relation"),
    "school": ('["amenity"="school"]', "node,way"),
    "college": ('["amenity"="college"]', "node,way"),
    "university": ('["amenity"="university"]', "node,way"),
    "police": ('["amenity"="police"]', "node,way"),
    "fire_station": ('["amenity"="fire_station"]', "node,way"),
    "bank": ('["amenity"="bank"]', "node,way"),
    "atm": ('["amenity"="atm"]', "node"),
    "pharmacy": ('["amenity"="pharmacy"]', "node,way"),
    "market": ('["amenity"="marketplace"]', "node,way"),
    "place_of_worship": ('["amenity"="place_of_worship"]', "node,way"),
    "railway_station": ('["railway"="station"]', "node,way"),
    "railway": ('["railway"~"rail|light_rail|subway|narrow_gauge"]', "way"),
    "village": ('["place"~"village|hamlet"]', "node"),
    "town": ('["place"~"town|city"]', "node"),
    "bus_station": ('["amenity"="bus_station"]', "node,way"),
    "airport": ('["aeroway"="aerodrome"]', "node,way,relation"),
    "road": ('["highway"~"motorway|trunk|primary|secondary"]', "way"),
    "river": ('["waterway"="river"]', "way"),
    "waterbody": ('["natural"="water"]', "way,relation"),
    "building": ('["building"]', "way,relation"),
    "landuse_residential": ('["landuse"="residential"]', "way,relation"),
    "park": ('["leisure"="park"]', "way,relation"),
    "toilet": ('["amenity"="toilets"]', "node,way"),
    "power_line": ('["power"="line"]', "way"),
    "solar_farm": ('["plant:source"="solar"]', "way,relation"),
}

# ---------------------------------------------------------------------------
# Weather / climate (no key required)
# ---------------------------------------------------------------------------

OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_AIR = "https://air-quality-api.open-meteo.com/v1/air-quality"
NOMINATIM = "https://nominatim.openstreetmap.org/search"

# ---------------------------------------------------------------------------
# Documented but unverified from the build machine
# ---------------------------------------------------------------------------

UNVERIFIED_SOURCES = {
    "india_wris": {
        "title": "India-WRIS (rainfall, groundwater, reservoirs, river basins)",
        "base": "https://indiawris.gov.in",
        "notes": (
            "POST APIs that require Origin and Referer headers set to "
            "indiawris.gov.in. Metadata endpoints take JSON; data endpoints take "
            "form-encoded bodies with parameters split across the query string. "
            "Unreachable from the build machine, so treat as best-effort."
        ),
    },
    "bhukosh": {
        "title": "GSI Bhukosh geology and minerals",
        "base": "https://bhukosh.gsi.gov.in/arcgis/rest/services",
        "notes": (
            "ArcGIS REST directory. Unreachable from the build machine. Use the "
            "GSI district resource map index on data.gov.in as a fallback."
        ),
    },
    "bhuvan_api": {
        "title": "Bhuvan REST APIs (village geocoding, LULC statistics, routing)",
        "base": "https://bhuvan-app1.nrsc.gov.in/api/",
        "notes": (
            "Require a token from a free Bhuvan account, and the token expires "
            "daily, which makes them a poor fit for unattended use. The WMS "
            "needs no token at all."
        ),
    },
    "imd_api": {
        "title": "IMD station weather and warnings",
        "base": "https://mausam.imd.gov.in/api/",
        "notes": (
            "Real endpoints, but access is IP-allowlisted by IMD rather than "
            "key-based. rainfallapi.php returns HTTP 200 even when it rejects "
            "you, so the body must be checked. Use the IMD gridded rainfall on "
            "data.gov.in instead."
        ),
    },
}


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def _score(needle_words, haystack_words):
    hits = 0
    for word in needle_words:
        for candidate in haystack_words:
            if word == candidate:
                hits += 3
            elif len(word) > 3 and word in candidate:
                hits += 1
    return hits


def search(query, limit=8):
    """Search the catalogue.  Returns a list of dicts the agent can act on."""
    words = [w for w in _normalise(query).split() if w]
    if not words:
        return []

    results = []

    # The curated shortlist and the state-wise families, scored together. The
    # families are what stop the catalogue from only serving whichever states
    # happened to be tested.
    for entry in BHUVAN_LAYERS + bhuvan_layers.all_layers():
        hay = _normalise(
            " ".join(
                [entry["title"], entry["name"], entry["theme"], entry.get("state") or ""]
                + entry["keywords"]
            )
        ).split()
        score = _score(words, hay)
        if score:
            results.append(
                (
                    score,
                    {
                        "source": "bhuvan",
                        "kind": "wms",
                        "id": entry["name"],
                        "title": entry["title"],
                        "host": entry["host"],
                        "state": entry.get("state"),
                        "how": "add_bhuvan_layer(layer='{0}')".format(entry["name"]),
                    },
                )
            )

    for entry in DATAGOV_RESOURCES:
        hay = _normalise(
            " ".join([entry["title"], entry["org"]] + entry["keywords"])
        ).split()
        score = _score(words, hay)
        if score:
            results.append(
                (
                    score,
                    {
                        "source": "data.gov.in",
                        "kind": "table",
                        "id": entry["id"],
                        "title": entry["title"],
                        "filters": entry.get("filters", []),
                        "mappable": bool(
                            entry.get("lat_field") or entry.get("location_field")
                        ),
                        "how": "add_datagov_layer(resource_id='{0}')".format(entry["id"]),
                    },
                )
            )

    for key, entry in BOUNDARY_SOURCES.items():
        hay = _normalise(entry["title"] + " " + key + " boundary india").split()
        score = _score(words, hay)
        if score:
            results.append(
                (
                    score,
                    {
                        "source": "boundaries",
                        "kind": "vector",
                        "id": key,
                        "title": entry["title"],
                        "how": "add_boundary(level='{0}')".format(key),
                    },
                )
            )

    for key, (_tags, _types) in OSM_PRESETS.items():
        hay = _normalise(key.replace("_", " ") + " osm openstreetmap").split()
        score = _score(words, hay)
        if score:
            results.append(
                (
                    score,
                    {
                        "source": "openstreetmap",
                        "kind": "vector",
                        "id": key,
                        "title": "OpenStreetMap {0}".format(key.replace("_", " ")),
                        "how": "add_osm_features(feature='{0}', place=...)".format(key),
                    },
                )
            )

    results.sort(key=lambda item: -item[0])
    return [item[1] for item in results[:limit]]


#: Query normalisation. Plural and near-synonym terms collapse onto the word the
#: catalogue actually indexes, so "districts", "borders" and "boundaries" all
#: reach the boundary datasets.
_SYNONYMS = {
    "aqi": "air quality",
    "pollution": "air quality",
    "boundaries": "boundary",
    "border": "boundary",
    "borders": "boundary",
    "catchment": "basin",
    "watershed": "basin",
    "constituencies": "parliamentary",
    "constituency": "parliamentary",
    "crops": "crop",
    "dem": "terrain",
    "districts": "district",
    "elevation": "terrain",
    "farming": "agriculture",
    "healthcare": "hospital",
    "highways": "road",
    "landcover": "land cover",
    "landuse": "land use",
    "lakes": "lake",
    "minerals": "mineral",
    "monsoon": "rainfall",
    "precipitation": "rainfall",
    "rain": "rainfall",
    "reservoirs": "reservoir",
    "rivers": "river",
    "roads": "road",
    "states": "state",
    "stations": "station",
    "villages": "village",
    "waterbodies": "water body",
}


def _normalise(text):
    text = str(text).lower()
    for char in ",.;:!?()[]{}\"'/\\|":
        text = text.replace(char, " ")
    words = []
    for word in text.split():
        words.append(_SYNONYMS.get(word, word))
    return " ".join(words)


def bhuvan_host_url(host_id):
    for host in BHUVAN_WMS_HOSTS:
        if host["id"] == host_id:
            return host["url"]
    return BHUVAN_WMS_HOSTS[0]["url"]


def find_datagov_resource(resource_id):
    for entry in DATAGOV_RESOURCES:
        if entry["id"] == resource_id:
            return entry
    return None


def find_bhuvan_layer(name):
    for entry in BHUVAN_LAYERS:
        if entry["name"] == name:
            return entry
    for entry in bhuvan_layers.all_layers():
        if entry["name"] == name:
            return entry
    return None


def bhuvan_state_layers(state_name):
    """Every Bhuvan layer the catalogue knows for one state."""
    return bhuvan_layers.for_state(state_name)


def bhuvan_states_covered():
    return bhuvan_layers.states_covered()


def bhuvan_layer_count():
    """Curated entries plus generated state-wise entries."""
    return len(BHUVAN_LAYERS) + bhuvan_layers.count()


def all_bhuvan_layers():
    """Every Bhuvan layer the catalogue can offer, curated and generated.

    The curated entries come first because they carry hand-written titles and
    are the ones a newcomer is most likely to want.
    """
    return list(BHUVAN_LAYERS) + list(bhuvan_layers.all_layers())
