# -*- coding: utf-8 -*-
"""Indian place resolution.

Two problems no generic geocoder solves well for India:

1. **Renaming and spelling.**  Bengaluru/Bangalore, Prayagraj/Allahabad,
   Varanasi/Banaras, Puducherry/Pondicherry, Thiruvananthapuram/Trivandrum.
   Both the historical and the current name are in active use in English
   documents, so either spelling must land in the same place -- and a district
   join against Census 2011 data must use the *Census* spelling even when the
   user typed the modern one.
2. **Vintage.**  Indian boundary files do not share one.  The Census 2011
   snapshot predates the 2014 bifurcation and files Telangana's ten districts
   under "Andhra Pradesh"; the current district set carries Telangana with its
   own 34.  A join that assumes either one silently loses districts, so
   :func:`census_state_for` records what the *older* files use and callers must
   check the data before applying it.

Resolution order: built-in gazetteer (offline, instant, no network) -> state
table -> Nominatim (network, 1 req/s policy).
"""

from ..core import net
from . import catalog

#: State and union territory bounding boxes, west, south, east, north.
STATES = {
    "andaman and nicobar islands": (92.20, 6.75, 94.28, 13.68),
    "andhra pradesh": (76.75, 12.62, 84.80, 19.92),
    "arunachal pradesh": (91.56, 26.63, 97.42, 29.45),
    "assam": (89.68, 24.13, 96.02, 28.22),
    "bihar": (83.32, 24.28, 88.30, 27.52),
    "chandigarh": (76.68, 30.67, 76.85, 30.80),
    "chhattisgarh": (80.25, 17.78, 84.40, 24.12),
    "dadra and nagar haveli and daman and diu": (72.65, 20.10, 73.22, 20.80),
    "delhi": (76.84, 28.40, 77.35, 28.89),
    "goa": (73.68, 14.90, 74.34, 15.80),
    "gujarat": (68.16, 20.12, 74.47, 24.71),
    "haryana": (74.46, 27.65, 77.60, 30.93),
    "himachal pradesh": (75.58, 30.38, 79.02, 33.25),
    "jammu and kashmir": (73.75, 32.28, 80.30, 35.70),
    "jharkhand": (83.32, 21.97, 87.95, 25.35),
    "karnataka": (74.05, 11.59, 78.59, 18.45),
    "kerala": (74.85, 8.18, 77.42, 12.79),
    "ladakh": (75.85, 32.30, 80.33, 36.00),
    "lakshadweep": (71.70, 8.20, 74.00, 12.40),
    "madhya pradesh": (74.03, 21.08, 82.81, 26.87),
    "maharashtra": (72.65, 15.60, 80.90, 22.03),
    "manipur": (92.97, 23.83, 94.78, 25.68),
    "meghalaya": (89.82, 25.03, 92.80, 26.12),
    "mizoram": (92.15, 21.95, 93.45, 24.52),
    "nagaland": (93.33, 25.20, 95.25, 27.03),
    "odisha": (81.38, 17.78, 87.53, 22.57),
    "puducherry": (79.75, 11.75, 79.87, 12.05),
    "punjab": (73.87, 29.53, 76.93, 32.52),
    "rajasthan": (69.48, 23.03, 78.27, 30.20),
    "sikkim": (88.02, 27.08, 88.92, 28.13),
    "tamil nadu": (76.23, 8.07, 80.35, 13.50),
    "telangana": (77.27, 15.83, 81.32, 19.92),
    "tripura": (91.10, 22.93, 92.35, 24.53),
    "uttar pradesh": (77.08, 23.87, 84.65, 30.42),
    "uttarakhand": (77.57, 28.72, 81.05, 31.47),
    "west bengal": (85.82, 21.52, 89.90, 27.22),
}

#: Cities and towns with a small bounding box each.
CITIES = {
    "delhi": (76.84, 28.40, 77.35, 28.89),
    "new delhi": (77.10, 28.53, 77.32, 28.68),
    "mumbai": (72.77, 18.89, 72.99, 19.28),
    "navi mumbai": (72.98, 18.98, 73.10, 19.15),
    "pune": (73.72, 18.41, 73.99, 18.64),
    "bengaluru": (77.44, 12.83, 77.78, 13.14),
    "hyderabad": (78.28, 17.28, 78.63, 17.55),
    "chennai": (80.15, 12.90, 80.32, 13.17),
    "kolkata": (88.26, 22.45, 88.45, 22.65),
    "ahmedabad": (72.45, 22.95, 72.72, 23.13),
    "surat": (72.72, 21.10, 72.93, 21.27),
    "jaipur": (75.68, 26.77, 75.90, 26.99),
    "lucknow": (80.83, 26.72, 81.05, 26.94),
    "kanpur": (80.23, 26.38, 80.42, 26.53),
    "nagpur": (78.99, 21.07, 79.15, 21.20),
    "indore": (75.79, 22.65, 75.94, 22.79),
    "bhopal": (77.32, 23.17, 77.52, 23.32),
    "patna": (85.05, 25.55, 85.24, 25.65),
    "varanasi": (82.93, 25.24, 83.07, 25.38),
    "prayagraj": (81.78, 25.37, 81.94, 25.51),
    "kochi": (76.19, 9.87, 76.35, 10.05),
    "thiruvananthapuram": (76.87, 8.42, 77.02, 8.58),
    "coimbatore": (76.90, 10.92, 77.05, 11.08),
    "madurai": (78.05, 9.87, 78.19, 9.99),
    "visakhapatnam": (83.20, 17.65, 83.35, 17.79),
    "vijayawada": (80.57, 16.45, 80.72, 16.58),
    "guwahati": (91.62, 26.09, 91.87, 26.24),
    "bhubaneswar": (85.75, 20.22, 85.90, 20.36),
    "chandigarh": (76.68, 30.67, 76.85, 30.80),
    "ludhiana": (75.78, 30.85, 75.94, 30.96),
    "amritsar": (74.79, 31.58, 74.94, 31.69),
    "dehradun": (77.96, 30.27, 78.10, 30.39),
    "shimla": (77.11, 31.05, 77.22, 31.14),
    "srinagar": (74.72, 34.02, 74.88, 34.15),
    "jodhpur": (72.96, 26.20, 73.10, 26.34),
    "udaipur": (73.63, 24.53, 73.79, 24.66),
    "nashik": (73.70, 19.93, 73.87, 20.06),
    "aurangabad": (75.26, 19.82, 75.40, 19.95),
    "raipur": (81.55, 21.17, 81.72, 21.31),
    "ranchi": (85.24, 23.30, 85.40, 23.44),
    "jamshedpur": (86.13, 22.75, 86.29, 22.87),
    "gwalior": (78.10, 26.15, 78.26, 26.28),
    "jabalpur": (79.87, 23.11, 80.02, 23.23),
    "agra": (77.94, 27.10, 78.10, 27.24),
    "meerut": (77.65, 28.94, 77.79, 29.06),
    "gurugram": (76.95, 28.38, 77.13, 28.53),
    "noida": (77.30, 28.47, 77.45, 28.63),
    "faridabad": (77.25, 28.32, 77.40, 28.47),
    "ghaziabad": (77.38, 28.61, 77.52, 28.73),
    "mysuru": (76.58, 12.24, 76.72, 12.38),
    "mangaluru": (74.79, 12.82, 74.90, 12.95),
    "hubli": (75.08, 15.30, 75.20, 15.42),
    "belagavi": (74.44, 15.79, 74.58, 15.92),
    "kozhikode": (75.73, 11.20, 75.85, 11.33),
    "thrissur": (76.14, 10.46, 76.28, 10.58),
    "tiruchirappalli": (78.63, 10.75, 78.76, 10.86),
    "salem": (78.09, 11.61, 78.22, 11.72),
    "guntur": (80.38, 16.24, 80.52, 16.37),
    "warangal": (79.52, 17.93, 79.66, 18.05),
    "gorakhpur": (83.30, 26.68, 83.44, 26.81),
    "siliguri": (88.36, 26.66, 88.48, 26.78),
    "durgapur": (87.24, 23.48, 87.38, 23.60),
    "cuttack": (85.79, 20.44, 85.93, 20.55),
    "rajkot": (70.72, 22.24, 70.86, 22.35),
    "vadodara": (73.13, 22.24, 73.27, 22.37),
    "jamnagar": (69.99, 22.41, 70.13, 22.53),
    "bhavnagar": (72.09, 21.71, 72.23, 21.83),
    "kota": (75.78, 25.13, 75.92, 25.24),
    "ajmer": (74.57, 26.40, 74.69, 26.52),
    "bikaner": (73.25, 27.98, 73.39, 28.09),
    "aizawl": (92.68, 23.68, 92.78, 23.78),
    "imphal": (93.87, 24.75, 93.99, 24.87),
    "shillong": (91.83, 25.51, 91.95, 25.63),
    "itanagar": (93.55, 27.04, 93.68, 27.15),
    "kohima": (94.05, 25.61, 94.18, 25.73),
    "agartala": (91.23, 23.78, 91.35, 23.90),
    "gangtok": (88.55, 27.28, 88.65, 27.39),
    "panaji": (73.79, 15.44, 73.88, 15.54),
    "puducherry": (79.75, 11.85, 79.87, 11.99),
    "port blair": (92.68, 11.57, 92.78, 11.70),
    "leh": (77.53, 34.10, 77.63, 34.22),
    "jammu": (74.79, 32.66, 74.93, 32.79),
    "haridwar": (78.10, 29.89, 78.22, 30.00),
    "rishikesh": (78.25, 30.06, 78.36, 30.16),
    "ujjain": (75.72, 23.13, 75.85, 23.24),
    "tirupati": (79.35, 13.58, 79.48, 13.70),
    "nellore": (79.92, 14.39, 80.05, 14.51),
    "kurnool": (77.99, 15.76, 78.12, 15.88),
    "solapur": (75.85, 17.61, 75.98, 17.73),
    "kolhapur": (74.17, 16.64, 74.30, 16.77),
    "bareilly": (79.35, 28.30, 79.48, 28.43),
    "aligarh": (78.02, 27.83, 78.14, 27.95),
    "moradabad": (78.71, 28.79, 78.83, 28.91),
    "saharanpur": (77.50, 29.91, 77.62, 30.03),
    "muzaffarpur": (85.32, 26.06, 85.44, 26.18),
    "gaya": (84.94, 24.72, 85.06, 24.84),
    "bhagalpur": (86.94, 25.19, 87.06, 25.31),
    "dhanbad": (86.37, 23.75, 86.50, 23.86),
    "bokaro": (85.99, 23.61, 86.13, 23.73),
    "asansol": (86.90, 23.62, 87.04, 23.74),
    "howrah": (88.25, 22.53, 88.37, 22.64),
}

#: ``alias -> canonical name``.  Both directions of every rename are here so
#: that either spelling resolves, and the Census spelling is recoverable.
ALIASES = {
    "bangalore": "bengaluru",
    "bangaluru": "bengaluru",
    "blr": "bengaluru",
    "bombay": "mumbai",
    "calcutta": "kolkata",
    "madras": "chennai",
    "cochin": "kochi",
    "ernakulam": "kochi",
    "trivandrum": "thiruvananthapuram",
    "calicut": "kozhikode",
    "trichur": "thrissur",
    "trichy": "tiruchirappalli",
    "allahabad": "prayagraj",
    "banaras": "varanasi",
    "benares": "varanasi",
    "kashi": "varanasi",
    "poona": "pune",
    "mysore": "mysuru",
    "mangalore": "mangaluru",
    "belgaum": "belagavi",
    "gurgaon": "gurugram",
    "pondicherry": "puducherry",
    "pondy": "puducherry",
    "baroda": "vadodara",
    "cawnpore": "kanpur",
    "vizag": "visakhapatnam",
    "waltair": "visakhapatnam",
    "bezawada": "vijayawada",
    "gauhati": "guwahati",
    "simla": "shimla",
    "hubballi": "hubli",
    "orissa": "odisha",
    "pondicherry ut": "puducherry",
    "ncr": "delhi",
    "new delhi ncr": "delhi",
    "ncr delhi": "delhi",
    "uttaranchal": "uttarakhand",
    "uttranchal": "uttarakhand",
    "up": "uttar pradesh",
    "mp": "madhya pradesh",
    "ap": "andhra pradesh",
    "tn": "tamil nadu",
    "wb": "west bengal",
    "jk": "jammu and kashmir",
    "j&k": "jammu and kashmir",
    "hp": "himachal pradesh",
    "tg": "telangana",
    "ts": "telangana",
    "maharastra": "maharashtra",
    "chattisgarh": "chhattisgarh",
    "chhatisgarh": "chhattisgarh",
    "pondichery": "puducherry",
    "bharat": "india",
    "hindustan": "india",
    "hindusthan": "india",
}

INDIA_BBOX = (68.0, 6.0, 97.5, 37.6)

#: Telangana districts that the Census 2011 files still label "Andhra Pradesh".
#: Any state-based filter on those files has to account for this.
TELANGANA_IN_CENSUS_AP = {
    "adilabad",
    "hyderabad",
    "karimnagar",
    "khammam",
    "mahbubnagar",
    "medak",
    "nalgonda",
    "nizamabad",
    "rangareddy",
    "warangal",
}


class Place:
    """A resolved place."""

    __slots__ = ("name", "canonical", "bbox", "kind", "state", "source")

    def __init__(self, name, canonical, bbox, kind, state=None, source="gazetteer"):
        self.name = name
        self.canonical = canonical
        self.bbox = bbox  # (west, south, east, north) in EPSG:4326
        self.kind = kind  # country | state | city | geocoded
        self.state = state
        self.source = source

    def as_dict(self):
        return {
            "name": self.name,
            "canonical": self.canonical,
            "bbox": list(self.bbox),
            "kind": self.kind,
            "state": self.state,
            "source": self.source,
        }

    def overpass_bbox(self):
        """Overpass wants ``south,west,north,east``."""
        west, south, east, north = self.bbox
        return "{0},{1},{2},{3}".format(south, west, north, east)

    def __repr__(self):  # pragma: no cover - debugging aid
        return "<Place {0} ({1}) {2}>".format(self.canonical, self.kind, self.bbox)


def normalise(name):
    """Lowercase, strip noise words, and apply the alias table."""
    text = str(name or "").strip().lower()
    for char in ".,;:!?()[]'\"":
        text = text.replace(char, " ")
    text = " ".join(text.split())
    for suffix in (
        " district",
        " city",
        " state",
        " region",
        " area",
        " metro",
        " municipal corporation",
        " urban agglomeration",
    ):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    return ALIASES.get(text, text)


def census_state_for(district_name, modern_state=None):
    """Return the state label a **pre-2014** boundary file uses.

    Telangana does not exist in those files, so the right filter value there is
    "Andhra Pradesh".

    Do not apply this blindly. Not every Indian boundary file is pre-2014 --
    the district set this plugin ships by default carries Telangana with its
    own 34 districts, and rewriting the query for that file returns Andhra
    Pradesh's own districts to someone who asked for Telangana, which is worse
    than an error. ``loaders.build_boundary_layer`` probes the loaded data and
    only falls back when the file genuinely has no Telangana.
    """
    if normalise(modern_state or "") == "telangana":
        return "Andhra Pradesh"
    if normalise(district_name or "") in TELANGANA_IN_CENSUS_AP:
        return "Andhra Pradesh"
    return modern_state


def lookup(name):
    """Resolve offline.  Returns a :class:`Place` or ``None``."""
    key = normalise(name)
    if not key:
        return None
    if key in ("india", "bharat", "whole india", "all india", "national", "desh"):
        return Place(name, "India", INDIA_BBOX, "country")
    if key in STATES:
        return Place(name, _titlecase(key), STATES[key], "state", state=_titlecase(key))
    if key in CITIES:
        return Place(name, _titlecase(key), CITIES[key], "city")
    # partial match, longest first so "andhra" does not beat "andhra pradesh"
    for table, kind in ((STATES, "state"), (CITIES, "city")):
        candidates = [k for k in table if key in k or k in key]
        if candidates:
            best = max(candidates, key=len)
            return Place(name, _titlecase(best), table[best], kind)
    return None


def geocode(name, feedback=None):
    """Resolve via Nominatim, restricted to India.  Network call."""
    from urllib.parse import urlencode

    query = urlencode(
        {
            "q": str(name),
            "format": "json",
            "limit": "1",
            "countrycodes": "in",
            "polygon_geojson": "0",
        }
    )
    url = "{0}?{1}".format(catalog.NOMINATIM, query)
    data = net.get_json(url, feedback=feedback)
    if not data:
        return None
    hit = data[0]
    # Nominatim boundingbox is [south, north, west, east] as strings.
    south, north, west, east = (float(v) for v in hit["boundingbox"])
    return Place(
        name,
        hit.get("display_name", str(name)).split(",")[0].strip(),
        (west, south, east, north),
        "geocoded",
        source="nominatim",
    )


def resolve(name, feedback=None, allow_network=True):
    """Offline gazetteer first, Nominatim only if that misses."""
    place = lookup(name)
    if place is not None:
        return place
    if not allow_network:
        return None
    try:
        return geocode(name, feedback=feedback)
    except Exception:
        return None


def _titlecase(text):
    small = {"and", "of", "the"}
    parts = []
    for word in text.split():
        parts.append(word if word in small else word.capitalize())
    return " ".join(parts)
