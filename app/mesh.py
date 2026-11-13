"""Triangle meshes for the 3D preview, built from the same solids as the IFC file."""
import math

from . import geometry

SEGMENTS = 20
SOURCE_RGB = {"dimensioned": (0.18, 0.55, 0.34), "derived": (0.11, 0.45, 0.58), "scaled": (0.88, 0.60, 0.12),
              "assumed": (0.78, 0.25, 0.20), "library": (0.42, 0.38, 0.70)}


def _area2(poly):
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(poly, poly[1:] + poly[:1]))


def triangulate(poly):
    """Ear clipping. Returns index triples into poly; handles concave outlines."""
    n = len(poly)
    if n < 3:
        return []
    idx = list(range(n))
    if _area2(poly) < 0:
        idx.reverse()
    tris = []

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    guard = 0
    while len(idx) > 3 and guard < 10000:
        guard += 1
        clipped = False
        for k in range(len(idx)):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            a, b, c = poly[i0], poly[i1], poly[i2]
            if cross(a, b, c) <= 1e-12:
                continue
            inside = False
            for j in idx:
                if j in (i0, i1, i2):
                    continue
                q = poly[j]
                if cross(a, b, q) >= 0 and cross(b, c, q) >= 0 and cross(c, a, q) >= 0:
                    inside = True
                    break
            if not inside:
                tris.append((i0, i1, i2))
                idx.pop(k)
                clipped = True
                break
        if not clipped:             # degenerate outline: fall back to a fan so something is still drawn
            break
    for k in range(1, len(idx) - 1):
        tris.append((idx[0], idx[k], idx[k + 1]))
    return tris


def profile_points(profile):
    if profile[0] == "poly":
        return list(profile[1])
    r = profile[1]
    return [(r * math.cos(2 * math.pi * k / SEGMENTS), r * math.sin(2 * math.pi * k / SEGMENTS)) for k in range(SEGMENTS)]


def _extrude(solid, out):
    _, profile, o, w, u, depth = solid
    v = geometry._cross(w, u)
    pts2 = profile_points(profile)
    if _area2(pts2) < 0:                                     # anticlockwise, so the side faces point outwards
        pts2.reverse()
    base = [(o[0] + x * u[0] + y * v[0], o[1] + x * u[1] + y * v[1], o[2] + x * u[2] + y * v[2]) for x, y in pts2]
    top = [(p[0] + w[0] * depth, p[1] + w[1] * depth, p[2] + w[2] * depth) for p in base]
    for a, b, c in triangulate(pts2):
        out.extend(base[a] + base[c] + base[b])
        out.extend(top[a] + top[b] + top[c])
    n = len(base)
    for k in range(n):
        k2 = (k + 1) % n
        out.extend(base[k] + base[k2] + top[k2])
        out.extend(base[k] + top[k2] + top[k])


def _brep(solid, out):
    for loop in solid[1]:
        nx = ny = nz = 0.0
        for a, b in zip(loop, loop[1:] + loop[:1]):          # Newell normal
            nx += (a[1] - b[1]) * (a[2] + b[2])
            ny += (a[2] - b[2]) * (a[0] + b[0])
            nz += (a[0] - b[0]) * (a[1] + b[1])
        ax = max(range(3), key=lambda i: abs((nx, ny, nz)[i]))
        i, j = [(1, 2), (2, 0), (0, 1)][ax]
        flat = [(p[i], p[j]) for p in loop]
        flip = (nx, ny, nz)[ax] < 0                          # triangulate() always winds anticlockwise in the flat view
        for a, b, c in triangulate(flat):
            out.extend(loop[a] + (loop[c] + loop[b] if flip else loop[b] + loop[c]))


def build(scene):
    """One mesh per top-level component: flat triangle coordinates, colours and a bounding box."""
    parts, _groups = geometry.walk(scene)
    by_id = {}
    order = []
    lo, hi = [float("inf")] * 3, [float("-inf")] * 3
    for part in parts:
        tid = part["top_id"]
        if tid not in by_id:
            by_id[tid] = {}
            order.append(tid)
        comp = part["comp"]
        key = id(comp)
        if key not in by_id[tid]:
            _mat, rgb, tr = geometry.appearance(comp)
            by_id[tid][key] = {"rgb": rgb, "opacity": round(1.0 - tr, 2), "source": comp["source"], "positions": []}
        buf = by_id[tid][key]["positions"]
        for solid in part["solids"]:
            (_extrude if solid[0] == "extrude" else _brep)(solid, buf)
    meshes = []
    for tid in order:
        for sub in by_id[tid].values():
            pos = sub["positions"]
            for k in range(0, len(pos), 3):
                for c in range(3):
                    val = pos[k + c]
                    if val < lo[c]:
                        lo[c] = val
                    if val > hi[c]:
                        hi[c] = val
            meshes.append({"id": tid, "rgb": sub["rgb"], "source_rgb": SOURCE_RGB.get(sub["source"], (0.5, 0.5, 0.5)),
                           "opacity": sub["opacity"], "positions": [round(c, 4) for c in pos]})
    if not meshes:
        lo, hi = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
    return {"meshes": meshes, "bbox": [lo, hi], "parts": len(parts)}
