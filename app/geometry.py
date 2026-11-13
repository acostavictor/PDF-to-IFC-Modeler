"""Turn a validated scene into solids in world coordinates.

Every solid is either an extrusion (a 2D profile pushed along a direction) or a faceted solid. The same
solids feed the IFC writer and the preview mesh, so the file and the picture cannot disagree.
"""
import math

from .scene import MAX_PARTS, SceneError


def _unit(v):
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


class Xf(object):
    """Rotation about the vertical axis followed by a translation."""
    __slots__ = ("c", "s", "t")

    def __init__(self, c=1.0, s=0.0, t=(0.0, 0.0, 0.0)):
        self.c, self.s, self.t = c, s, t

    def pt(self, p):
        return (self.c * p[0] - self.s * p[1] + self.t[0], self.s * p[0] + self.c * p[1] + self.t[1], p[2] + self.t[2])

    def vec(self, v):
        return (self.c * v[0] - self.s * v[1], self.s * v[0] + self.c * v[1], v[2])

    def mul(self, other):
        """The transform that applies `other` first, then this one."""
        return Xf(self.c * other.c - self.s * other.s, self.s * other.c + self.c * other.s, self.pt(other.t))


def place(at, deg):
    a = math.radians(deg)
    return Xf(math.cos(a), math.sin(a), (at[0], at[1], at[2]))


def _apply(xf, solid):
    if solid[0] == "extrude":
        _, profile, o, w, u, depth = solid
        return ("extrude", profile, xf.pt(o), xf.vec(w), xf.vec(u), depth)
    return ("brep", [[xf.pt(p) for p in loop] for loop in solid[1]])


def _rect(x0, x1, y0, y1):
    return ("poly", [(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def _up(profile, z0, z1, origin=(0.0, 0.0)):
    return ("extrude", profile, (origin[0], origin[1], z0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0), z1 - z0)


# ------------------------------------------------------------------------------------------ builders
def _pile(p):
    size, shape = p["size"], p["shape"]
    lv = p["top_el"] - p["tip_el"]
    a = math.radians(p["batter_dir"])
    run = p["batter"] * lv
    toe = (run * math.cos(a), run * math.sin(a), -lv)
    length = math.sqrt(sum(c * c for c in toe))
    w = _unit(toe)
    u = (-math.sin(a), math.cos(a), 0.0) if run > 1e-9 else (1.0, 0.0, 0.0)
    if shape == "round":
        prof = ("circle", size / 2)
    elif shape == "pipe":
        prof = ("ring", size / 2, p["wall"])
    elif shape == "square":
        prof = _rect(-size / 2, size / 2, -size / 2, size / 2)
    elif shape == "octagonal":
        r = (size / 2) / math.cos(math.pi / 8)
        prof = ("poly", [(r * math.cos(math.pi / 8 + k * math.pi / 4), r * math.sin(math.pi / 8 + k * math.pi / 4)) for k in range(8)])
    else:                                   # H-pile, approximate outline
        h, tf, tw = size / 2, 0.06 * size, 0.04 * size
        prof = ("poly", [(-h, -h), (h, -h), (h, -h + tf), (tw, -h + tf), (tw, h - tf), (h, h - tf), (h, h), (-h, h),
                         (-h, h - tf), (-tw, h - tf), (-tw, -h + tf), (-h, -h + tf)])
    return [("extrude", prof, (0.0, 0.0, p["top_el"]), w, u, length)]


def _block(p):
    if p["plan"] == "circle":
        prof = ("circle", p["length"] / 2)
    else:
        prof = _rect(-p["length"] / 2, p["length"] / 2, -p["width"] / 2, p["width"] / 2)
    return [_up(prof, p["bottom_el"], p["top_el"])]


def _slab(p):
    prof = ("poly", [tuple(r) for r in p["outline"]]) if p["outline"] else _rect(0.0, p["length"], 0.0, p["width"])
    return [_up(prof, p["top_el"] - p["thickness"], p["top_el"])]


def _beam(p):
    out = []
    w_, d_ = p["width"], p["depth"]
    top = p["reference"] == "top"
    for a, b in zip(p["path"][:-1], p["path"][1:]):
        d = tuple(b[i] - a[i] for i in range(3))
        length = math.sqrt(sum(c * c for c in d))
        w = _unit(d)
        u = (1.0, 0.0, 0.0) if abs(w[2]) > 0.999 else _unit(_cross((0.0, 0.0, 1.0), w))
        v = _cross(w, u)
        o = tuple(a)
        if p["section"] == "rectangle":
            prof = _rect(-w_ / 2, w_ / 2, -d_, 0.0) if top else _rect(-w_ / 2, w_ / 2, -d_ / 2, d_ / 2)
        else:
            prof = ("circle", w_ / 2) if p["section"] == "round" else ("ring", w_ / 2, p["wall"])
            if top:
                o = tuple(a[i] - v[i] * w_ / 2 for i in range(3))
        out.append(("extrude", prof, o, w, u, length))
    return out


def _volume(loops):
    vol = 0.0
    for loop in loops:
        p0 = loop[0]
        for p1, p2 in zip(loop[1:-1], loop[2:]):
            c = _cross(p1, p2)
            vol += p0[0] * c[0] + p0[1] * c[1] + p0[2] * c[2]
    return vol / 6.0


def sweep(section, path, closed):
    """A cross-section (offset, elevation) pushed along a plan path, mitred at the corners."""
    pts = [tuple(q) for q in path]
    if not closed and len(pts) == 2:
        (x0, y0), (x1, y1) = pts
        length = math.hypot(x1 - x0, y1 - y0)
        t = ((x1 - x0) / length, (y1 - y0) / length)
        return [("extrude", ("poly", [(-o, e) for o, e in section]), (x0, y0, 0.0), (t[0], t[1], 0.0), (-t[1], t[0], 0.0), length)]
    n = len(pts)
    segs = [(pts[i], pts[(i + 1) % n]) for i in range(n if closed else n - 1)]
    rights = []
    for a, b in segs:
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        rights.append(((b[1] - a[1]) / length, -(b[0] - a[0]) / length))
    rings = []
    for j in range(n):
        if closed:
            ra, rb = rights[j - 1], rights[j]
        else:
            ra, rb = rights[max(j - 1, 0)], rights[min(j, len(rights) - 1)]
        m = (ra[0] + rb[0], ra[1] + rb[1])
        ml = math.hypot(m[0], m[1])
        if ml < 1e-9:
            m = ra
        else:
            m = (m[0] / ml, m[1] / ml)
            k = 1.0 / max(m[0] * ra[0] + m[1] * ra[1], 0.25)
            m = (m[0] * k, m[1] * k)
        rings.append([(pts[j][0] + m[0] * o, pts[j][1] + m[1] * o, e) for o, e in section])
    loops = []
    k_n = len(section)
    for j in range(len(segs)):
        a, b = rings[j], rings[(j + 1) % n]
        for k in range(k_n):
            k2 = (k + 1) % k_n
            loops.append([a[k], b[k], b[k2], a[k2]])
    if not closed:
        loops.append(list(rings[0]))
        loops.append(list(reversed(rings[-1])))
    if _volume(loops) < 0:
        loops = [list(reversed(loop)) for loop in loops]
    return [("brep", loops)]


def _wall(p):
    t = p["thickness"]
    o0, o1 = {"centre": (-t / 2, t / 2), "left face": (0.0, t), "right face": (-t, 0.0)}[p["align"]]
    section = [(o0, p["bottom_el"]), (o1, p["bottom_el"]), (o1, p["top_el"]), (o0, p["top_el"])]
    return sweep(section, p["path"], p["closed"] == "yes")


def _section_sweep(p):
    return sweep([tuple(r) for r in p["section"]], p["path"], p["closed"] == "yes")


def _fender(p, kind):
    length, h, proj = p["length"], p["height"], p["projection"]
    if "cyl" in kind:
        return [("extrude", ("circle", proj / 2), (proj / 2, -length / 2, 0.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0), length)]
    if "cone" in kind or "cell" in kind:
        return [("extrude", ("circle", h / 2), (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), proj)]
    return [_up(_rect(0.0, proj, -length / 2, length / 2), -h / 2, h / 2)]


def _mooring(p, kind):
    h, d = p["height"], p["diameter"]
    if "cleat" in kind:
        return [_up(_rect(-d / 4, d / 4, -d / 8, d / 8), 0.0, h / 2), _up(_rect(-d / 2, d / 2, -d * 0.09, d * 0.09), h / 2, h)]
    if "hook" in kind or "ring" in kind:
        return [_up(_rect(-d / 2, d / 2, -d / 4, d / 4), 0.0, h)]
    return [_up(("circle", d * 0.6), 0.0, h * 0.08), _up(("circle", d * 0.3), h * 0.08, h * 0.75), _up(("circle", d / 2), h * 0.75, h)]


def local_solids(comp):
    t, p, kind = comp["type"], comp["params"], comp["kind"]
    if t == "pile":
        return _pile(p)
    if t == "block":
        return _block(p)
    if t == "slab":
        return _slab(p)
    if t == "beam":
        return _beam(p)
    if t == "wall":
        return _wall(p)
    if t == "section_sweep":
        return _section_sweep(p)
    if t == "fender":
        return _fender(p, kind)
    if t == "mooring":
        return _mooring(p, kind)
    raise SceneError("Unknown component type: %s" % t)


# ------------------------------------------------------------------------------------------ appearance
_PALETTE = [
    (("dredge", "cut", "water"), "Dredge limit", (0.35, 0.55, 0.80), 0.7),
    (("rubber", "fender", "foam"), "Rubber", (0.15, 0.15, 0.17), 0.0),
    (("armour", "armor", "rock", "stone", "riprap", "rubble", "revetment", "scour", "toe berm"), "Rock", (0.52, 0.50, 0.46), 0.0),
    (("underlayer", "filter", "bedding"), "Rock, underlayer", (0.64, 0.60, 0.52), 0.0),
    (("core", "fill", "sand", "gravel", "quarry"), "Granular fill", (0.74, 0.64, 0.44), 0.0),
    (("timber", "wood", "greenheart"), "Timber", (0.58, 0.43, 0.27), 0.0),
    (("alumin",), "Aluminium", (0.76, 0.79, 0.82), 0.0),
    (("steel", "sheet pile", "pipe", "tie rod", "iron"), "Steel", (0.33, 0.40, 0.49), 0.0),
    (("pontoon", "float"), "Float", (0.86, 0.86, 0.80), 0.0),
    (("concrete", "grout"), "Concrete", (0.72, 0.72, 0.70), 0.0),
]
_BY_TYPE = {"fender": "rubber", "mooring": "steel", "section_sweep": "rock", "wall": "concrete"}


def appearance(comp):
    """Material name, colour and transparency for a component."""
    hint = comp["material"].lower()
    if not hint:
        hint = comp["kind"]
        if comp["type"] == "pile" and comp["params"]["shape"] in ("pipe", "h"):
            hint += " steel"
        if comp["type"] == "beam" and comp["params"]["section"] == "pipe":
            hint += " steel"
    for text in (hint, _BY_TYPE.get(comp["type"], ""), "concrete"):
        for keys, name, rgb, tr in _PALETTE:
            if any(k in text for k in keys):
                return (comp["material"] or name), rgb, tr
    return (comp["material"] or "Concrete"), (0.72, 0.72, 0.70), 0.0


# ------------------------------------------------------------------------------------------ instancing
def _instances(comp):
    """Placements of a component. Repeats step in the parent's axes; each copy is rotated about its own origin."""
    at, deg = comp["at"], comp["rotate"]
    spot = lambda dx, dy, dz: place((at[0] + dx, at[1] + dy, at[2] + dz), deg)
    if comp.get("positions"):
        rows = comp["positions"]
        return [("[%d]" % (i + 1) if len(rows) > 1 else "", spot(r[0], r[1], r[2])) for i, r in enumerate(rows)]
    arr = comp.get("array")
    if arr:
        out = []
        for i in range(arr["nx"]):
            for j in range(arr["ny"]):
                label = "[%d,%d]" % (i + 1, j + 1) if arr["nx"] > 1 and arr["ny"] > 1 else "[%d]" % (i * arr["ny"] + j + 1)
                out.append((label, spot(i * arr["dx"], j * arr["dy"], 0.0)))
        return out
    return [("", spot(0.0, 0.0, 0.0))]


def walk(scene):
    """Return (parts, groups). A part is one physical piece; a group is one placed assembly."""
    parts, groups = [], []
    cache = {}

    def rec(comp, xf, parent, prefix, top_id):
        for label, ixf in _instances(comp):
            world = xf.mul(ixf)
            name = (prefix + comp["name"] + (" " + label if label else "")).strip()
            if comp["type"] == "assembly":
                key = len(groups)
                groups.append({"key": key, "comp": comp, "name": name, "parent": parent, "top_id": top_id})
                for child in comp["children"]:
                    rec(child, world, key, name + " / ", top_id)
            else:
                if id(comp) not in cache:
                    cache[id(comp)] = local_solids(comp)
                if len(parts) >= MAX_PARTS:
                    raise SceneError("The model has more than %d pieces. Reduce the repeat counts." % MAX_PARTS)
                parts.append({"comp": comp, "name": name, "parent": parent, "top_id": top_id,
                              "solids": [_apply(world, s) for s in cache[id(comp)]]})

    for comp in scene["components"]:
        rec(comp, Xf(), None, "", comp["id"])
    return parts, groups
