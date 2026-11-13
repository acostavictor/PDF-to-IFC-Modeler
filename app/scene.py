"""The structure description ("scene") that every model is stored and exchanged as.

A scene is a list of components drawn from a small vocabulary of marine building blocks. Components can
repeat on a grid or at listed positions, and can be grouped into assemblies. Coordinates are x along the
structure, y across it, z elevation; all lengths are in the scene's unit.
"""
import re

SCHEMA = "p2i-scene/1"
UNITS = {"ft": ("FOOT", 1.0), "m": ("METRE", 0.3048), "mm": ("MILLIMETRE", 304.8)}
SOURCES = ("dimensioned", "derived", "scaled", "assumed", "library")
MAX_PARTS = 20000
MAX_DEPTH = 6

STRUCTURE_TYPES = ["Pier or jetty", "Wharf or quay", "Mooring or breasting dolphin", "Marina or floating dock",
                   "Breakwater", "Revetment or seawall", "Bulkhead", "Dry dock", "Boat ramp", "Other"]
LIBRARY_CATEGORIES = ["Piles", "Pile caps and beams", "Decks", "Walls and bulkheads", "Breakwaters and revetments",
                      "Fenders", "Mooring hardware", "Floating docks", "Assemblies", "Other"]


class SceneError(ValueError):
    pass


def N(key, label, default, hint="", length=True):
    return {"key": key, "label": label, "type": "number", "default": default, "hint": hint, "length": length}


def C(key, label, options, default, hint=""):
    return {"key": key, "label": label, "type": "choice", "options": options, "default": default, "hint": hint}


def T(key, label, columns, default, hint=""):
    return {"key": key, "label": label, "type": "table", "columns": columns, "default": default, "hint": hint}


def X(key, label, default="", hint=""):
    return {"key": key, "label": label, "type": "text", "default": default, "hint": hint}


# Defaults are in feet; they are converted when a component is created in another unit.
TYPES = {
    "pile": {
        "title": "Pile", "summary": "A single pile, plumb or battered. Placed at the pile head.",
        "kinds": ["bearing pile", "batter pile", "fender pile", "guide pile", "mooring pile", "king pile", "anchor pile"],
        "params": [
            C("shape", "Cross-section", ["round", "pipe", "square", "octagonal", "h"], "octagonal",
              "pipe is a hollow round section; h is an H-pile shown as an approximate outline."),
            N("size", "Diameter or width", 2.0, "Diameter for round and pipe; width across flats otherwise."),
            N("wall", "Wall thickness (pipe only)", 0.042),
            N("top_el", "Top elevation", 8.0, "Cut-off or head elevation."),
            N("tip_el", "Tip elevation", -60.0),
            N("batter", "Batter, horizontal per 1 vertical", 0.0, "0 for a plumb pile. 1H:6V is 0.1667; '2 on 12' is 0.1667.", False),
            N("batter_dir", "Batter direction (degrees)", 0.0,
              "Direction the toe moves, counter-clockwise from +x. 90 leans the toe toward +y.", False),
        ],
    },
    "block": {
        "title": "Block", "summary": "A rectangular or circular prism between two elevations. Placed at the centre of its plan.",
        "kinds": ["pile cap", "dolphin cap", "pontoon", "mooring block", "footing", "deadman", "caisson", "fill", "other"],
        "params": [
            C("plan", "Plan shape", ["rectangle", "circle"], "rectangle"),
            N("length", "Length along x, or diameter", 10.0),
            N("width", "Width along y", 10.0, "Ignored for a circle."),
            N("top_el", "Top elevation", 10.0),
            N("bottom_el", "Bottom elevation", 6.0),
        ],
    },
    "slab": {
        "title": "Slab", "summary": "A flat slab of any plan outline. A plain rectangle runs from the placement point toward +x and +y.",
        "kinds": ["deck", "apron", "relieving platform", "floor", "mat", "ramp slab", "topping"],
        "params": [
            N("length", "Length along x", 100.0, "Used when no outline is given."),
            N("width", "Width along y", 30.0, "Used when no outline is given."),
            T("outline", "Plan outline (optional)", [{"name": "x", "type": "number"}, {"name": "y", "type": "number"}], [],
              "Corner points in order. Leave empty for a plain rectangle."),
            N("top_el", "Top elevation", 12.0),
            N("thickness", "Thickness", 1.5),
        ],
    },
    "beam": {
        "title": "Beam or linear member", "summary": "A member of constant section along a line through 3D points.",
        "kinds": ["pile cap beam", "deck beam", "stringer", "waler", "curb", "bullrail", "tie rod", "brace", "gangway",
                  "handrail", "pipe"],
        "params": [
            T("path", "Path points", [{"name": "x", "type": "number"}, {"name": "y", "type": "number"}, {"name": "z", "type": "number"}],
              [[0, 0, 10], [40, 0, 10]], "Two or more points. z is the elevation of the reference line."),
            C("section", "Section", ["rectangle", "round", "pipe"], "rectangle"),
            N("width", "Width, or diameter", 3.0),
            N("depth", "Depth", 3.0, "Ignored for round and pipe."),
            N("wall", "Wall thickness (pipe only)", 0.03),
            C("reference", "Path runs along the", ["top", "centre"], "top", "top: the section hangs below the path."),
        ],
    },
    "wall": {
        "title": "Wall", "summary": "A wall of constant thickness along a line in plan, between two elevations.",
        "kinds": ["sheet pile wall", "bulkhead", "seawall", "quay wall", "wave wall", "cutoff wall", "retaining wall", "deadman wall"],
        "params": [
            T("path", "Path points in plan", [{"name": "x", "type": "number"}, {"name": "y", "type": "number"}], [[0, 0], [100, 0]]),
            N("top_el", "Top elevation", 10.0),
            N("bottom_el", "Bottom or tip elevation", -30.0),
            N("thickness", "Thickness", 1.5, "For sheet piling, the overall depth of the sheet pile system."),
            C("align", "Path runs along the", ["centre", "left face", "right face"], "centre", "Left and right are seen looking along the path."),
            C("closed", "Closed loop", ["no", "yes"], "no", "yes joins the last point back to the first, for example a circular cell."),
        ],
    },
    "section_sweep": {
        "title": "Swept cross-section", "summary": "Any cross-section pushed along a line in plan: breakwaters, revetments, gravity walls, dredge cuts.",
        "kinds": ["armour layer", "underlayer", "core", "filter layer", "revetment", "rubble mound", "gravity wall", "quay wall",
                  "dock wall", "floor", "fill", "dredge cut", "scour protection", "bedding", "toe berm", "crown wall"],
        "params": [
            T("section", "Cross-section points", [{"name": "offset", "type": "number"}, {"name": "elevation", "type": "number"}],
              [[-20, -10], [20, -10], [5, 5], [-5, 5]],
              "Outline of the section in order. Offset is measured across the path, positive to the right when looking along it."),
            T("path", "Path points in plan", [{"name": "x", "type": "number"}, {"name": "y", "type": "number"}], [[0, 0], [100, 0]]),
            C("closed", "Closed loop", ["no", "yes"], "no"),
        ],
    },
    "fender": {
        "title": "Fender", "summary": "A fender unit. Placed at the centre of its mounting face; it projects toward +x, so rotate it to face the berth.",
        "kinds": ["cylindrical fender", "arch fender", "cone fender", "cell fender", "D fender", "foam fender", "timber rubbing strip"],
        "params": [
            N("length", "Length along the face", 6.0),
            N("height", "Height", 3.0),
            N("projection", "Projection from the face", 3.0),
        ],
    },
    "mooring": {
        "title": "Mooring fitting", "summary": "A bollard, cleat, bitt or hook. Placed at the centre of its base, on the deck.",
        "kinds": ["bollard", "cleat", "bitt", "quick release hook", "mooring ring"],
        "params": [
            N("height", "Height", 1.5),
            N("diameter", "Base diameter or length", 1.5),
            X("capacity", "Rated capacity", "", "For example 100 t. Recorded on the element, not drawn."),
        ],
    },
    "assembly": {
        "title": "Assembly", "summary": "A group of components that is placed and repeated as one unit, for example a pile bent.",
        "kinds": ["pile bent", "dolphin", "finger pier", "breakwater section", "fender system", "tie-back system", "other"],
        "params": [],
    },
}

_DEC = {"ft": 3, "m": 3, "mm": 0}


def _to_unit(value, units):
    """Convert a default given in feet to the scene unit, rounded to a tidy value."""
    f = UNITS[units][1]
    if isinstance(value, (int, float)):
        return round(value * f, _DEC[units]) if f != 1.0 else value
    return value


def default_params(type_id, units="ft"):
    out = {}
    for spec in TYPES[type_id]["params"]:
        d = spec["default"]
        if spec["type"] == "number" and spec.get("length"):
            d = _to_unit(d, units)
        elif spec["type"] == "table":
            d = [[_to_unit(c, units) for c in row] for row in d]
        out[spec["key"]] = d
    return out


def catalogue():
    types = []
    for tid, t in TYPES.items():
        types.append({"id": tid, "title": t["title"], "summary": t["summary"], "kinds": t["kinds"], "params": t["params"]})
    return {"schema": SCHEMA, "types": types, "units": sorted(UNITS), "sources": list(SOURCES),
            "structure_types": STRUCTURE_TYPES, "library_categories": LIBRARY_CATEGORIES}


# ------------------------------------------------------------------------------------------ validation
def _num(x, where):
    if isinstance(x, bool) or x is None:
        raise SceneError("%s: a number is needed" % where)
    if isinstance(x, (int, float)):
        v = float(x)
    else:
        try:
            v = float(str(x).strip().replace(",", ""))
        except ValueError:
            raise SceneError("%s: '%s' is not a number" % (where, x))
    if v != v or abs(v) > 1e12:
        raise SceneError("%s: the number is out of range" % where)
    return v


def _table(value, spec, where):
    cols = spec["columns"]
    if isinstance(value, str):
        value = [[c for c in re.split(r"[,\s;]+", line.strip()) if c] for line in value.splitlines() if line.strip()]
    if value in (None, ""):
        value = []
    if not isinstance(value, (list, tuple)):
        raise SceneError("%s: a list of rows is needed" % where)
    rows = []
    for i, row in enumerate(value):
        if isinstance(row, dict):
            row = [row.get(c["name"]) for c in cols]
        if not isinstance(row, (list, tuple)) or len(row) != len(cols):
            raise SceneError("%s, row %d: %d values are needed (%s)" % (where, i + 1, len(cols), ", ".join(c["name"] for c in cols)))
        rows.append([_num(c, "%s, row %d" % (where, i + 1)) for c in row])
    return rows


def _params(type_id, raw, units, where):
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    defaults = default_params(type_id, units)
    for spec in TYPES[type_id]["params"]:
        key = spec["key"]
        val = raw.get(key)
        here = "%s, %s" % (where, spec["label"].lower())
        if val is None or val == "":
            out[key] = defaults[key]
        elif spec["type"] == "number":
            out[key] = _num(val, here)
        elif spec["type"] == "choice":
            v = str(val).strip().lower()
            match = [o for o in spec["options"] if o == v or o.split()[0] == v]
            if not match:
                raise SceneError("%s: '%s' is not one of %s" % (here, val, ", ".join(spec["options"])))
            out[key] = match[0]
        elif spec["type"] == "table":
            out[key] = _table(val, spec, here)
        else:
            out[key] = str(val)[:200]
    return out


def _check(type_id, p, where):
    def need(cond, msg):
        if not cond:
            raise SceneError("%s: %s" % (where, msg))
    if type_id == "pile":
        need(p["size"] > 0, "the size must be greater than zero")
        need(p["top_el"] > p["tip_el"], "the top elevation must be above the tip elevation")
        need(0 <= p["batter"] <= 2, "the batter must be between 0 and 2 horizontal per vertical")
        if p["shape"] == "pipe":
            need(0 < p["wall"] < p["size"] / 2, "the wall thickness must be less than half the diameter")
    elif type_id == "block":
        need(p["length"] > 0 and (p["plan"] == "circle" or p["width"] > 0), "length and width must be greater than zero")
        need(p["top_el"] > p["bottom_el"], "the top elevation must be above the bottom elevation")
    elif type_id == "slab":
        need(p["thickness"] > 0, "the thickness must be greater than zero")
        if p["outline"]:
            need(len(p["outline"]) >= 3, "an outline needs at least three points")
        else:
            need(p["length"] > 0 and p["width"] > 0, "length and width must be greater than zero")
    elif type_id == "beam":
        need(len(p["path"]) >= 2, "the path needs at least two points")
        need(p["width"] > 0 and (p["section"] != "rectangle" or p["depth"] > 0), "the section size must be greater than zero")
        if p["section"] == "pipe":
            need(0 < p["wall"] < p["width"] / 2, "the wall thickness must be less than half the diameter")
        need(all(a != b for a, b in zip(p["path"][:-1], p["path"][1:])), "two path points in a row are the same")
    elif type_id == "wall":
        need(len(p["path"]) >= 2, "the path needs at least two points")
        need(p["top_el"] > p["bottom_el"], "the top elevation must be above the bottom elevation")
        need(p["thickness"] > 0, "the thickness must be greater than zero")
        need(all(a != b for a, b in zip(p["path"][:-1], p["path"][1:])), "two path points in a row are the same")
        need(p["closed"] == "no" or len(p["path"]) >= 3, "a closed wall needs at least three points")
    elif type_id == "section_sweep":
        need(len(p["section"]) >= 3, "the cross-section needs at least three points")
        need(len(p["path"]) >= 2, "the path needs at least two points")
        need(all(a != b for a, b in zip(p["path"][:-1], p["path"][1:])), "two path points in a row are the same")
        need(p["closed"] == "no" or len(p["path"]) >= 3, "a closed path needs at least three points")
        area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(p["section"], p["section"][1:] + p["section"][:1])) / 2.0
        need(abs(area) > 1e-9, "the cross-section has no area")
    elif type_id == "fender":
        need(p["length"] > 0 and p["height"] > 0 and p["projection"] > 0, "every size must be greater than zero")
    elif type_id == "mooring":
        need(p["height"] > 0 and p["diameter"] > 0, "height and diameter must be greater than zero")


def _component(raw, units, used, depth, path):
    if not isinstance(raw, dict):
        raise SceneError("%s: each component must be an object" % path)
    type_id = str(raw.get("type") or "").strip().lower().replace(" ", "_").replace("-", "_")
    if type_id not in TYPES:
        raise SceneError("%s: '%s' is not a component type. Use one of: %s" % (path, raw.get("type"), ", ".join(TYPES)))
    name = str(raw.get("name") or TYPES[type_id]["title"]).strip()[:120]
    where = "'%s' (%s)" % (name, TYPES[type_id]["title"].lower())
    cid = re.sub(r"[^A-Za-z0-9_-]", "", str(raw.get("id") or ""))[:40]
    n = len(used)
    while not cid or cid in used:
        n += 1
        cid = "c%d" % n
    used.add(cid)
    at = raw.get("at") if raw.get("at") not in (None, "") else [0, 0, 0]
    if not isinstance(at, (list, tuple)) or len(at) not in (2, 3):
        raise SceneError("%s: the placement needs x, y and z" % where)
    at = [_num(c, where + ", placement") for c in at] + ([0.0] if len(at) == 2 else [])
    out = {"id": cid, "type": type_id, "name": name, "kind": str(raw.get("kind") or "").strip().lower()[:60],
           "material": str(raw.get("material") or "").strip()[:60], "at": at,
           "rotate": _num(raw.get("rotate") or 0, where + ", rotation"),
           "source": raw.get("source") if raw.get("source") in SOURCES else "assumed",
           "note": str(raw.get("note") or "")[:400]}
    if raw.get("library_item"):
        out["library_item"] = str(raw["library_item"])[:120]
    arr = raw.get("array")
    if isinstance(arr, dict) and (arr.get("nx") or arr.get("ny")):
        nx, ny = int(_num(arr.get("nx") or 1, where + ", repeat count")), int(_num(arr.get("ny") or 1, where + ", repeat count"))
        if nx < 1 or ny < 1 or nx * ny > MAX_PARTS:
            raise SceneError("%s: repeat counts must be at least 1 and no more than %d in total" % (where, MAX_PARTS))
        if nx * ny > 1:
            out["array"] = {"nx": nx, "dx": _num(arr.get("dx") or 0, where + ", spacing"), "ny": ny,
                            "dy": _num(arr.get("dy") or 0, where + ", spacing")}
    pos = raw.get("positions")
    if isinstance(pos, str):
        pos = [[c for c in re.split(r"[,\s;]+", line.strip()) if c] for line in pos.splitlines() if line.strip()]
    if pos:
        if not isinstance(pos, (list, tuple)) or len(pos) > MAX_PARTS:
            raise SceneError("%s: positions must be a list of x, y points" % where)
        rows = []
        for i, row in enumerate(pos):
            if not isinstance(row, (list, tuple)) or len(row) not in (2, 3):
                raise SceneError("%s, position %d: x and y are needed" % (where, i + 1))
            rows.append([_num(c, "%s, position %d" % (where, i + 1)) for c in row] + ([0.0] if len(row) == 2 else []))
        out["positions"] = rows
        out.pop("array", None)
    if type_id == "assembly":
        if depth >= MAX_DEPTH:
            raise SceneError("%s: assemblies are nested too deeply" % where)
        kids = raw.get("children")
        if not isinstance(kids, (list, tuple)) or not kids:
            raise SceneError("%s: an assembly needs at least one component inside it" % where)
        out["children"] = [_component(k, units, used, depth + 1, where) for k in kids]
        out["params"] = {}
    else:
        out["params"] = _params(type_id, raw.get("params"), units, where)
        _check(type_id, out["params"], where)
    return out


def normalise(raw):
    """Validate a scene and fill in defaults. Raises SceneError naming the component at fault."""
    if not isinstance(raw, dict):
        raise SceneError("The model must be a JSON object.")
    units = str(raw.get("units") or "ft").strip().lower()
    units = {"feet": "ft", "foot": "ft", "metre": "m", "meter": "m", "metres": "m", "meters": "m", "millimetre": "mm",
             "millimeter": "mm", "millimetres": "mm", "millimeters": "mm"}.get(units, units)
    if units not in UNITS:
        raise SceneError("Units must be ft, m or mm.")
    comps = raw.get("components")
    if comps is None:
        comps = []
    if not isinstance(comps, (list, tuple)):
        raise SceneError("The components must be a list.")
    used = set()
    out = {"schema": SCHEMA, "units": units}
    for key, limit in (("name", 160), ("project", 160), ("structure_type", 60), ("datum", 80), ("description", 2000),
                       ("source_drawings", 300), ("author", 120)):
        out[key] = str(raw.get(key) or "").strip()[:limit]
    out["components"] = [_component(c, units, used, 0, "Component %d" % (i + 1)) for i, c in enumerate(comps)]
    return out


def instance_count(comp):
    n = len(comp["positions"]) if comp.get("positions") else (comp["array"]["nx"] * comp["array"]["ny"] if comp.get("array") else 1)
    if comp["type"] == "assembly":
        return n * sum(instance_count(k) for k in comp["children"])
    return n


def count_parts(scene):
    return sum(instance_count(c) for c in scene["components"])


# ------------------------------------------------------------------------------------------ unit conversion
def convert_component(comp, src, dst):
    """Return a copy of a normalised component with every length converted between units."""
    if src == dst:
        return comp
    k = UNITS[dst][1] / UNITS[src][1]
    nd = 4 if dst != "mm" else 1
    c = lambda v: round(v * k, nd)
    out = dict(comp)
    out["at"] = [c(v) for v in comp["at"]]
    if comp.get("array"):
        a = comp["array"]
        out["array"] = {"nx": a["nx"], "dx": c(a["dx"]), "ny": a["ny"], "dy": c(a["dy"])}
    if comp.get("positions"):
        out["positions"] = [[c(v) for v in row] for row in comp["positions"]]
    if comp["type"] == "assembly":
        out["children"] = [convert_component(k_, src, dst) for k_ in comp["children"]]
        return out
    params = {}
    for spec in TYPES[comp["type"]]["params"]:
        v = comp["params"][spec["key"]]
        if spec["type"] == "number" and spec.get("length"):
            v = c(v)
        elif spec["type"] == "table":
            v = [[c(x) for x in row] for row in v]
        params[spec["key"]] = v
    out["params"] = params
    return out


def convert_scene(raw, dst):
    scene = normalise(raw)
    if dst not in UNITS:
        raise SceneError("Units must be ft, m or mm.")
    src = scene["units"]
    scene["components"] = [convert_component(c, src, dst) for c in scene["components"]]
    scene["units"] = dst
    return scene


def normalise_component(raw, units):
    """Validate one component on its own, as stored in the library."""
    return normalise({"units": units, "components": [raw]})["components"][0]
