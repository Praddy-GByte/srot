# -*- coding: utf-8 -*-
"""State-wise Bhuvan layer families.

Bhuvan publishes ~8,350 namespaced layers on ``bhuvan-vec1``. Most of them are
one dataset repeated per state, with the state encoded in the layer name. A
hand-written shortlist can only ever cover a few states, which is how a
catalogue ends up looking like it was built for whoever the author happened to
test with.

So these are recorded as *families*: a name pattern plus the exact set of state
codes that actually exist on the server. Every code list here was extracted
from a real ``GetCapabilities`` response (7.5 MB, 13,342 named layers, fetched
2026-09), not written from memory.

Two different code schemes are in use, which matters:

* The ``mmi`` workspace uses **ISO 3166-2:IN** codes, so ``CT`` is Chhattisgarh
  and ``CH`` is Chandigarh, ``UT`` is Uttarakhand, ``TG`` is Telangana and
  ``LA`` is Ladakh.
* The ``basemap`` and ``sdv`` workspaces use an **older in-house scheme** where
  Chhattisgarh is ``CG1``, Uttarakhand is ``UK`` and Telangana is ``ts``.

Where a code cannot be resolved with confidence it is listed in
:data:`AMBIGUOUS` and deliberately left out of the name lookup, rather than
guessed. A layer served under the wrong state name is worse than one the search
does not reach.
"""

# ---------------------------------------------------------------------------
# Code tables
# ---------------------------------------------------------------------------

#: ISO 3166-2:IN, as used by the ``mmi`` (transport and hazard) workspace.
ISO_CODES = {
    "AN": "Andaman and Nicobar Islands",
    "AP": "Andhra Pradesh",
    "AR": "Arunachal Pradesh",
    "AS": "Assam",
    "BR": "Bihar",
    "CH": "Chandigarh",
    "CT": "Chhattisgarh",
    "DH": "Dadra and Nagar Haveli and Daman and Diu",
    "DL": "Delhi",
    "GA": "Goa",
    "GJ": "Gujarat",
    "HP": "Himachal Pradesh",
    "HR": "Haryana",
    "JH": "Jharkhand",
    "JK": "Jammu and Kashmir",
    "KA": "Karnataka",
    "KL": "Kerala",
    "LA": "Ladakh",
    "LD": "Lakshadweep",
    "MH": "Maharashtra",
    "ML": "Meghalaya",
    "MN": "Manipur",
    "MP": "Madhya Pradesh",
    "MZ": "Mizoram",
    "NL": "Nagaland",
    "OR": "Odisha",
    "PB": "Punjab",
    "PY": "Puducherry",
    "RJ": "Rajasthan",
    "SK": "Sikkim",
    "TG": "Telangana",
    "TN": "Tamil Nadu",
    "TR": "Tripura",
    "UP": "Uttar Pradesh",
    "UT": "Uttarakhand",
    "WB": "West Bengal",
}

#: The older scheme used by ``basemap``. ``CG1`` and ``CH`` both appear, which
#: is what settles ``CH`` as Chandigarh here.
BASEMAP_CODES = {
    "AN": "Andaman and Nicobar Islands",
    "AP": "Andhra Pradesh",
    "AR": "Arunachal Pradesh",
    "AS": "Assam",
    "BR": "Bihar",
    "CG1": "Chhattisgarh",
    "CH": "Chandigarh",
    "DIU": "Daman and Diu",
    "DL": "Delhi",
    "DN": "Dadra and Nagar Haveli",
    "GA": "Goa",
    "GJ": "Gujarat",
    "HP": "Himachal Pradesh",
    "HR": "Haryana",
    "JH": "Jharkhand",
    "JK": "Jammu and Kashmir",
    "KA": "Karnataka",
    "KL": "Kerala",
    "LD": "Lakshadweep",
    "MH": "Maharashtra",
    "ML": "Meghalaya",
    "MN": "Manipur",
    "MP": "Madhya Pradesh",
    "MZ": "Mizoram",
    "NL": "Nagaland",
    "OR": "Odisha",
    "PB": "Punjab",
    "PY1": "Puducherry (Puducherry district)",
    "PY2": "Puducherry (Karaikal)",
    "PY3": "Puducherry (Mahe)",
    "PY4": "Puducherry (Yanam)",
    "RJ1": "Rajasthan (west sheet)",
    "RJ2": "Rajasthan (east sheet)",
    "SK": "Sikkim",
    "TN": "Tamil Nadu",
    "TR": "Tripura",
    "UK": "Uttarakhand",
    "UP": "Uttar Pradesh",
    "WB": "West Bengal",
}

#: Lowercase codes used by ``sdv`` for terrain rasters.
SLOPE_CODES = {
    "ap": "Andhra Pradesh",
    "ar": "Arunachal Pradesh",
    "as": "Assam",
    "br": "Bihar",
    "gj": "Gujarat",
    "hp": "Himachal Pradesh",
    "hr": "Haryana",
    "jh": "Jharkhand",
    "ka": "Karnataka",
    "kl": "Kerala",
    "mh": "Maharashtra",
    "ml": "Meghalaya",
    "mn": "Manipur",
    "mp": "Madhya Pradesh",
    "mz": "Mizoram",
    "nl": "Nagaland",
    "or": "Odisha",
    "pb": "Punjab",
    "rj": "Rajasthan",
    "sk": "Sikkim",
    "tn": "Tamil Nadu",
    "tr": "Tripura",
    "ts": "Telangana",
    "uk": "Uttarakhand",
    "up": "Uttar Pradesh",
    "wb": "West Bengal",
}

#: What a family actually renders, measured by sampling GetMap against the live
#: server (2026-09). Bhuvan happily serves a valid layer that has nothing on it,
#: so "the layer exists" and "the layer draws" are different questions.
#:
#:   draws          -- renders at state extent
#:   sparse         -- renders, but thinly; correct for states with little of it
#:   empty          -- the server returns a watermark-only tile at any extent
#:   district_only  -- a group of per-district layers; Bhuvan's renderer aborts
#:                     at 60 s over a whole state, but it draws when zoomed in
COVERAGE_MEANING = {
    "draws": "renders at state extent",
    "sparse": "renders thinly; may be correct where the feature is genuinely rare",
    "empty": "the server returns a watermark-only tile -- nothing to see",
    "district_only": "only renders over a district-sized extent, not a whole state",
}


#: Codes that exist on the server but cannot be resolved to one state with
#: confidence. They are reachable through search_bhuvan_layers; they are just
#: not claimed to belong to a particular state here.
AMBIGUOUS = {
    "sdv:ch_slope": (
        "Bhuvan's sdv workspace has no separate Chhattisgarh code, so 'ch' here "
        "could be Chandigarh or Chhattisgarh. Load it and check the extent."
    ),
}

#: The ``gw`` workspace spells states out in full, and uses several pre-2011
#: names. Both the old and current names are listed so either resolves.
GROUNDWATER_STATES = {
    "ANDAMAN_NICOBAR": "Andaman and Nicobar Islands",
    "ANDHRA_PRADESH": "Andhra Pradesh",
    "ARUNACHAL_PRADESH": "Arunachal Pradesh",
    "ASSAM": "Assam",
    "BIHAR": "Bihar",
    "CHHATTISGARH": "Chhattisgarh",
    "DADRA_NAGAR_HAVELI": "Dadra and Nagar Haveli",
    "GOA": "Goa",
    "GUJARAT": "Gujarat",
    "HARYANA": "Haryana",
    "HIMACHAL_PRADESH": "Himachal Pradesh",
    "JAMMU_KASHMIR": "Jammu and Kashmir",
    "JHARKHAND": "Jharkhand",
    "KARNATAKA": "Karnataka",
    "KERALA": "Kerala",
    "MADHYA_PRADESH": "Madhya Pradesh",
    "MAHARASHTRA": "Maharashtra",
    "MANIPUR": "Manipur",
    "MEGHALAYA": "Meghalaya",
    "MIZORAM": "Mizoram",
    "NAGALAND": "Nagaland",
    "ORISSA": "Odisha",            # published under the pre-2011 name
    "PONDICHERRY": "Puducherry",   # published under the pre-2006 name
    "PUNJAB": "Punjab",
    "RAJASTHAN": "Rajasthan",
    "TAMIL_NADU": "Tamil Nadu",
    "TELANGANA": "Telangana",
    "TRIPURA": "Tripura",
    "UTTARANCHAL": "Uttarakhand",  # pre-2007 name, still on the server
    "UTTRAKHAND": "Uttarakhand",   # and a second, misspelt copy
    "UTTAR_PRADESH": "Uttar Pradesh",
    "WEST_BENGAL": "West Bengal",
}

# ---------------------------------------------------------------------------
# Families
# ---------------------------------------------------------------------------

FAMILIES = [
    {
        "id": "lulc_state",
        "coverage": "draws",
        "label": "Land use / land cover",
        "pattern": "basemap:{code}_LULC",
        "host": "vec1",
        "theme": "lulc",
        "codes": BASEMAP_CODES,
        "keywords": ["lulc", "land use", "land cover", "landuse", "landcover"],
    },
    {
        "id": "village_state",
        "coverage": "empty",
        "label": "Village boundaries",
        "pattern": "basemap:{code}_Vill",
        "host": "vec1",
        "theme": "admin",
        # The village layers use plain "CG" for Chhattisgarh, not the "CG1" the
        # LULC layers use in the same workspace. Verified against the server.
        "codes": dict(
            {k: v for k, v in BASEMAP_CODES.items()
             if k in {"AP", "AS", "GJ", "HR", "JH", "JK", "KA", "KL", "MH",
                      "MP", "OR", "RJ", "SK", "TN", "TR", "UK", "UP", "WB"}},
            CG="Chhattisgarh",
        ),
        "keywords": ["village", "revenue village", "gram panchayat"],
    },
    {
        "id": "slope_state",
        "coverage": "district_only",
        "label": "Slope",
        "pattern": "sdv:{code}_slope",
        "host": "vec1",
        "theme": "terrain",
        "codes": SLOPE_CODES,
        "keywords": ["slope", "terrain", "gradient", "relief"],
    },
    {
        "id": "roads_state",
        "coverage": "draws",
        "label": "Road network",
        "pattern": "mmi:{code}_ROAD_NETWORK_Q4_2022",
        "host": "vec1",
        "theme": "transport",
        # Chhattisgarh has no road layer in this release of the mmi set.
        "codes": {k: v for k, v in ISO_CODES.items() if k != "CT"},
        "keywords": ["road", "highway", "street", "transport", "network"],
    },
    {
        "id": "rail_state",
        "coverage": "sparse",
        "label": "Railway network",
        "pattern": "mmi:{code}_RAIL_NETWORK_Q4_2022",
        "host": "vec1",
        "theme": "transport",
        # Island and small-UT territories with no railway have no layer.
        "codes": {
            k: v for k, v in ISO_CODES.items()
            if k not in {"AN", "DH", "LA", "LD", "SK"}
        },
        "keywords": ["rail", "railway", "train", "transport", "network"],
    },
    {
        "id": "railstation_state",
        "coverage": "empty",
        "label": "Railway stations",
        "pattern": "mmi:{code}_RAIL_STATION_Q4_2022",
        "host": "vec1",
        "theme": "transport",
        "codes": {
            k: v for k, v in ISO_CODES.items()
            if k not in {"AN", "CH", "DH", "LA", "LD", "SK"}
        },
        "keywords": ["railway station", "train station", "rail", "station"],
    },
    {
        "id": "hydrology_state",
        "coverage": "draws",
        "label": "Hydrology network",
        "pattern": "mmi:{code}_HYDROLOGY_R_Q4_2022",
        "host": "vec1",
        "theme": "water",
        "codes": ISO_CODES,
        "keywords": ["hydrology", "river", "stream", "drainage", "water"],
    },
    {
        "id": "groundwater_pre",
        "coverage": "draws",
        "label": "Groundwater level, pre-monsoon",
        "pattern": "gw:{code}_PRE",
        "host": "vec1",
        "theme": "water",
        "codes": GROUNDWATER_STATES,
        "keywords": ["groundwater", "water table", "aquifer", "pre monsoon", "well"],
    },
    {
        "id": "groundwater_post",
        "coverage": "draws",
        "label": "Groundwater level, post-monsoon",
        "pattern": "gw:{code}_POST",
        "host": "vec1",
        "theme": "water",
        "codes": {
            k: v for k, v in GROUNDWATER_STATES.items()
            if k != "DADRA_NAGAR_HAVELI"
        },
        "keywords": ["groundwater", "water table", "aquifer", "post monsoon", "recharge"],
    },
]

# ---------------------------------------------------------------------------
# Standalone layers verified present, beyond the state families
# ---------------------------------------------------------------------------

#: All 23 river-basin drainage networks, exactly as named on the server.
BASINS = [
    ("hydrology:BDRN_1_Indus", "Indus"),
    ("hydrology:BDRN_2A_Ganga", "Ganga"),
    ("hydrology:BDRN_2B_Brahmaputra", "Brahmaputra"),
    ("hydrology:BDRN_2C_BarakOth", "Barak and others"),
    ("hydrology:BDRN_3_Godavari", "Godavari"),
    ("hydrology:BDRN_4_Krishna", "Krishna"),
    ("hydrology:BDRN_5_Cauvery", "Cauvery"),
    ("hydrology:BDRN_6_Subernarekha", "Subarnarekha"),
    ("hydrology:BDRN_7_BrahmaniBaitarni", "Brahmani and Baitarani"),
    ("hydrology:BDRN_8_Mahanadi", "Mahanadi"),
    ("hydrology:BDRN_9_Pennar", "Pennar"),
    ("hydrology:BDRN_10_Mahi", "Mahi"),
    ("hydrology:BDRN_11_Sabarmati", "Sabarmati"),
    ("hydrology:BDRN_12_Narmada", "Narmada"),
    ("hydrology:BDRN_13_Tapi", "Tapi"),
    ("hydrology:BDRN_14_WFRSouthTapi", "West-flowing rivers south of Tapi"),
    ("hydrology:BDRN_15_EFRMahanadiGodavari", "East-flowing rivers, Mahanadi to Godavari"),
    ("hydrology:BDRN_16_EFRGodavariKrishna", "East-flowing rivers, Godavari to Krishna"),
    ("hydrology:BDRN_17_EFRKrishnaPennar", "East-flowing rivers, Krishna to Pennar"),
    ("hydrology:BDRN_18_EFRPennarCauvery", "East-flowing rivers, Pennar to Cauvery"),
    ("hydrology:BDRN_19_EFRSouthCauvery", "East-flowing rivers south of Cauvery"),
    ("hydrology:BDRN_20_WFRKutchSaurashtra", "West-flowing rivers, Kutch and Saurashtra"),
    ("hydrology:BDRN_22_MinorRiversMyanmar", "Minor rivers draining to Myanmar"),
]

EXTRA_LAYERS = [
    {
        "name": "hydrology:BASIN",
        "title": "River basins of India",
        "host": "vec1", "theme": "water",
        "keywords": ["basin", "river basin", "catchment", "watershed"],
    },
    {
        "name": "hydrology:SUBBASIN",
        "title": "River sub-basins of India",
        "host": "vec1", "theme": "water",
        "keywords": ["sub basin", "subbasin", "catchment"],
    },
    {
        "name": "hydrology:WSHED",
        "title": "Watersheds of India",
        "host": "vec1", "theme": "water",
        "keywords": ["watershed", "catchment", "drainage"],
    },
    {
        "name": "hydrology:dam",
        "title": "Dams of India",
        "host": "vec1", "theme": "water",
        "keywords": ["dam", "reservoir", "storage"],
    },
    {
        "name": "hydrology:barrage_weir_anicut",
        "title": "Barrages, weirs and anicuts",
        "host": "vec1", "theme": "water",
        "keywords": ["barrage", "weir", "anicut", "irrigation"],
    },
    {
        "name": "mmi:india_roads",
        "title": "Road network, all India",
        "host": "vec1", "theme": "transport",
        "keywords": ["road", "highway", "national", "all india"],
    },
    {
        "name": "mmi:india_rail",
        "title": "Railway network, all India",
        "host": "vec1", "theme": "transport",
        "keywords": ["rail", "railway", "national", "all india"],
    },
    {
        "name": "cleanganga:GangaRiver",
        "title": "Ganga river course (Namami Gange)",
        "host": "vec1", "theme": "water",
        "keywords": ["ganga", "ganges", "river", "namami gange"],
    },
    {
        "name": "cleanganga:Ganga_CWC_Water_Quality_Stations",
        "title": "CWC water quality stations on the Ganga",
        "host": "vec1", "theme": "water",
        "keywords": ["water quality", "ganga", "cwc", "monitoring", "pollution"],
    },
    {
        "name": "cleanganga:Ganga_118Towns_STP_Status",
        "title": "Sewage treatment plant status, 118 Ganga towns",
        "host": "vec1", "theme": "water",
        "keywords": ["stp", "sewage", "treatment", "ganga", "sanitation"],
    },
    {
        "name": "basemap:AP_Telengana_bnd_line",
        "title": "Andhra Pradesh / Telangana bifurcation boundary (2014)",
        "host": "vec1", "theme": "admin",
        "keywords": ["telangana", "andhra", "bifurcation", "boundary", "2014"],
    },
]

#: LULC at 1:50,000, which exists for a subset of states only.
LULC_50K = [
    ("sdv:AP_LULC50K_1112N", "Andhra Pradesh"),
    ("moef:BR_LULC50K_1112", "Bihar"),
    ("moef:CH_LULC50K_1112_GB", "Chandigarh"),
    ("moef:DL_LULC50K_1112", "Delhi"),
    ("moef:HP_LULC50K_1112_GB", "Himachal Pradesh"),
    ("moef:HR_LULC50K_1112_GB", "Haryana"),
    ("moef:JH_LULC50K_1112_GB", "Jharkhand"),
    ("moef:MP_LULC50K_1112_GB", "Madhya Pradesh"),
    ("moef:UK_LULC50K_1112", "Uttarakhand"),
    ("moef:UP_LULC50K_1112", "Uttar Pradesh"),
    ("moef:WB_LULC50K_1112", "West Bengal"),
]


# ---------------------------------------------------------------------------
# Expansion
# ---------------------------------------------------------------------------


#: Where a Bhuvan family is served empty, an equivalent that does have data.
#: The point is that a request for village boundaries returns village data --
#: not a report about a server. Each entry names an OpenStreetMap preset and
#: the wording used to tell the user where the result came from.
ALTERNATIVES = {
    "village_state": {
        "osm_preset": "village",
        "label": "villages and hamlets from OpenStreetMap",
    },
    "railstation_state": {
        "osm_preset": "railway_station",
        "label": "railway stations from OpenStreetMap",
    },
    "rail_state": {
        "osm_preset": "railway",
        "label": "railway lines from OpenStreetMap",
    },
}


def alternative_for(family_id):
    """The substitute source for a family Bhuvan serves empty."""
    return ALTERNATIVES.get(family_id)


def _norm(text):
    return " ".join(str(text or "").lower().replace("&", "and").split())


def expand(family):
    """Every concrete layer a family stands for."""
    out = []
    for code, state in sorted(family["codes"].items(), key=lambda kv: kv[1]):
        out.append(
            {
                "name": family["pattern"].format(code=code),
                "title": "{0}, {1}".format(family["label"], state),
                "host": family["host"],
                "theme": family["theme"],
                "state": state,
                "family": family["id"],
                "coverage": family.get("coverage", "unknown"),
                "keywords": family["keywords"],
            }
        )
    return out


def all_layers():
    """The full generated shortlist: families expanded, plus the standalones."""
    layers = []
    for family in FAMILIES:
        layers.extend(expand(family))
    for name, basin in BASINS:
        layers.append(
            {
                "name": name,
                "title": "{0} basin drainage network".format(basin),
                "host": "vec1",
                "theme": "water",
                "state": None,
                "family": "basin",
                "keywords": ["basin", "drainage", "river", basin.lower()],
            }
        )
    for name, state in LULC_50K:
        layers.append(
            {
                "name": name,
                "title": "Land use / land cover 1:50k (2011-12), {0}".format(state),
                "host": "vec1",
                "theme": "lulc",
                "state": state,
                "family": "lulc50k",
                "keywords": ["lulc", "land use", "land cover", "50k", "50000"],
            }
        )
    for entry in EXTRA_LAYERS:
        item = dict(entry)
        item.setdefault("state", None)
        item.setdefault("family", "standalone")
        layers.append(item)
    return layers


def for_state(state_name):
    """Every generated layer belonging to one state."""
    wanted = _norm(state_name)
    if not wanted:
        return []
    hits = []
    for layer in all_layers():
        if not layer.get("state"):
            continue
        state = _norm(layer["state"])
        if wanted == state or wanted in state or state.startswith(wanted):
            hits.append(layer)
    return hits


def states_covered():
    """Sorted list of every state the generated shortlist can serve."""
    return sorted({l["state"] for l in all_layers() if l.get("state")})


def count():
    return len(all_layers())


def coverage_summary():
    """How many catalogued layers actually draw, by measured verdict."""
    counts = {}
    for layer in all_layers():
        verdict = layer.get("coverage", "unknown")
        counts[verdict] = counts.get(verdict, 0) + 1
    return counts
