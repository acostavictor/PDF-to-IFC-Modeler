"""STAAD.Pro input file (analysis model) for the sloped strut gate, from the same parameters as the IFC.

STAAD axes: X along the gate, Y up, Z = -(model y), so the struts are on the -Z side. Units: metre, kN.
The skin is 4-node shells on the outside-face work line; girders, the strut-level beam and the bulb
flats are prismatic beams on the skin nodes with rigid offsets to their centroids.
"""
import math

from .base import resolve
from .strut_gate import PARAMS, Geo, hp_props


def build(params, meta=None):
    meta = meta or {}
    v, _ = resolve(PARAMS, params)
    g = Geo(v)
    mm = lambda x: x / 1000.0
    joints, jl, groups = {}, [], {}

    def J(x, y, z):
        k = (round(mm(x), 4), round(mm(z), 4), round(-mm(y), 4))
        if k not in joints:
            joints[k] = len(jl) + 1
            jl.append(k)
        return joints[k]

    def M(key, a, b):
        if a != b:
            groups.setdefault(key, []).append((a, b))

    edges = [g.X0] + g.GX + [g.X1]
    xl = []
    for a, b in zip(edges[:-1], edges[1:]):
        n = max(1, int(round((b - a) / 750.0)))
        xl += [a + (b - a) * i / n for i in range(n)]
    xl.append(g.X1)
    size_at = dict(g.ROWS)
    sl = sorted(set([g.SKIN[0][0]] + [s for s, _ in g.ROWS] + [g.S_B1, g.S_TOP]))
    plates = {}
    nearest = lambda target: min(range(len(sl)), key=lambda i: abs(sl[i] - target))
    i_b1 = sl.index(g.S_B1)
    i_foot = nearest(g.s_at_z(v["shoe_top_z"], 0))
    i_tie = nearest(g.s_at_z(v["tie_z"], g.D_FL))
    lt = g.L_TIE
    ty = sorted(v["tie_y"])
    for sg in (-1, 1):
        xs = sorted(sg * x for x in xl)         # west to east, so member local x is +X
        N = [[J(x, *g.pt(s)) for x in xs] for s in sl]
        for i in range(len(sl) - 1):
            t = g.skin_t((sl[i] + sl[i + 1]) / 2)
            for j in range(len(xs) - 1):
                plates.setdefault(t, []).append((N[i][j], N[i][j + 1], N[i + 1][j + 1], N[i + 1][j]))
        for i, s in enumerate(sl):
            key = ("STF", size_at[s].upper(), g.skin_t(s)) if s in size_at else (("B1",) if s == g.S_B1 else None)
            if key:
                for j in range(len(xs) - 1):
                    M(key, N[i][j], N[i][j + 1])
        for gx in g.GX:
            x = sg * gx
            j = min(range(len(xs)), key=lambda q: abs(xs[q] - x))
            for i in range(i_foot, len(sl) - 1):
                sm = (sl[i] + sl[i + 1]) / 2
                zone = "LO" if sm < v["knee_lo"] else ("UP" if sm > v["knee_up"] else "TR")
                M(("PG", zone, g.skin_t(sm)), N[i][j], N[i + 1][j])
            nb = J(x, v["bearing_y"], -265.0)
            M(("LINK",), N[i_foot][j], nb)
            groups.setdefault("SUP", []).append(nb)
            n0, n1, n2 = J(x, *g.strut_pt(v["strut_base_len"])), J(x, *g.strut_pt(lt)), J(x, *g.strut_pt(g.L_FLANGE))
            M(("STRUT",), n0, n1)
            M(("STRUT",), n1, n2)
            M(("LINK",), n2, N[i_b1][j])
            groups["SUP"].append(n0)
            nf, nm = J(x, g.Y_TIE_REF, v["tie_z"]), J(x, ty[1], v["tie_z"])
            M(("LINK",), N[i_tie][j], nf)
            M(("TIE",), nf, nm)
            M(("TIE",), nm, n1)
        for a, b in zip(g.GX[:-1], g.GX[1:]):
            for y in (g.Y_TIE_REF, ty[1]):
                M(("TIE",), J(sg * a, y, v["tie_z"]), J(sg * b, y, v["tie_z"]))
            M(("TIE",), J(sg * a, *g.strut_pt(lt)), J(sg * b, *g.strut_pt(lt)))
            M(("TIE",), J(sg * a, g.Y_TIE_REF, v["tie_z"]), J(sg * b, ty[1], v["tie_z"]))

    wt, fw, ft = v["web_t"], v["flange_w"], v["flange_t"]

    def tee(web_d, t_skin):
        a1, a2 = web_d * wt, fw * ft
        c1, c2 = t_skin + web_d / 2, t_skin + web_d + ft / 2
        area = a1 + a2
        c = (a1 * c1 + a2 * c2) / area
        iz = wt * web_d ** 3 / 12 + a1 * (c1 - c) ** 2 + fw * ft ** 3 / 12 + a2 * (c2 - c) ** 2
        iy = web_d * wt ** 3 / 12 + ft * fw ** 3 / 12
        ix = (web_d * wt ** 3 + fw * ft ** 3) / 3
        return area, iz, iy, ix, c

    pris = lambda a, iz, iy, ix: "PRIS AX %.6g IX %.6g IY %.6g IZ %.6g" % (a * 1e-6, ix * 1e-12, iy * 1e-12, iz * 1e-12)
    off = lambda d: (0.0, round(-mm(d) * g.C, 4), round(-mm(d) * g.S, 4))
    beta = round(v["slope_deg"], 3)
    order, lines, offs, betas = [], [], [], []

    def add(key, line, d=None, b=None):
        if key in groups:
            order.append(key)
            lines.append(line)
            offs.append(d)
            betas.append(b)

    thicknesses = sorted(set(t for _, _, t in g.SKIN), reverse=True)
    for zone, dep in (("LO", v["depth_lower"]), ("TR", (v["depth_lower"] + v["depth_upper"]) / 2), ("UP", v["depth_upper"])):
        for t in thicknesses:
            a, iz, iy, ix, c = tee(dep, t)
            add(("PG", zone, t), pris(a, iz, iy, ix), c)
    a, iz, iy, ix, c = tee(v["depth_lower"], g.skin_t(g.S_B1))
    add(("B1",), pris(a, iz, iy, ix), c, beta)
    for size in sorted(set(s.upper() for _, s in g.ROWS)):
        bw, bt, cc, area, cg, ixx, _known = hp_props(size)
        if not ixx:
            ixx = bt * bw ** 3 / 12 + area * 0.02 * bw ** 2
        for t in thicknesses:
            add(("STF", size, t), pris(area, ixx, bw * bt ** 3 / 12 * 1.6, bw * bt ** 3 / 3 * 1.5), t + cg, beta)
    add(("STRUT",), "TABLE ST TUBE DT %.4f WT %.4f TH %.6f" % (mm(v["strut_b"]), mm(v["strut_b"]), mm(v["strut_t"])))
    add(("TIE",), "TABLE ST TUBE DT %.4f WT %.4f TH %.6f" % (mm(v["tie_b"]), mm(v["tie_b"]), mm(v["tie_t"])))
    add(("LINK",), "PRIS AX 0.1 IX 0.01 IY 0.01 IZ 0.01")
    mem, rng = [], {}
    for key in order:
        a = len(mem) + 1
        mem += groups[key]
        rng[key] = (a, len(mem))
    pl, prng = [], {}
    for t in thicknesses:
        if t in plates:
            a = len(mem) + len(pl) + 1
            pl += plates[t]
            prng[t] = (a, len(mem) + len(pl))
    R = lambda r: ("%d TO %d" % r) if r[1] > r[0] else "%d" % r[0]
    wrap = lambda items, per: "\n".join(" ".join(items[i:i + per]) for i in range(0, len(items), per))
    title = (meta.get("project_name") or "SLOPED STRUT GATE").upper()[:60]
    out = ["STAAD SPACE " + "".join(ch if 32 <= ord(ch) < 127 else " " for ch in title), "START JOB INFORMATION",
           "ENGINEER DATE " + (meta.get("date") or "01-Jan-26"), "END JOB INFORMATION"]
    for c in ["Generated by pdf-to-ifc-modeler from the reviewed gate parameters.",
              "Check BETA angles and member offsets in the 3D section view on first open.",
              "Axes: X along gate, Y up. Struts on the -Z side.",
              "Origin: gate CL at the skin work point on the dock floor.",
              "Skin: 4-node shells on the outside-face work line.",
              "Girders, strut-level beam and bulb flats: PRISMATIC beams on the skin",
              "nodes with rigid offsets to their centroids.",
              "Supports ASSUMED pinned at strut bases and girder bearings.",
              "No seal or end-wall restraint. Only self weight is defined.",
              "Not modelled: catwalk, door opening, lifting points, cut-outs, splices."]:
        out.append("* " + c)
    out += ["INPUT WIDTH 79", "UNIT METER KN", "JOINT COORDINATES",
            wrap(["%d %g %g %g;" % (i + 1, p[0], p[1], p[2]) for i, p in enumerate(jl)], 2),
            "MEMBER INCIDENCES", wrap(["%d %d %d;" % (i + 1, a, b) for i, (a, b) in enumerate(mem)], 5),
            "ELEMENT INCIDENCES SHELL", wrap(["%d %d %d %d %d;" % ((len(mem) + i + 1,) + p) for i, p in enumerate(pl)], 3),
            "ELEMENT PROPERTY"]
    out += ["%s THICKNESS %g" % (R(prng[t]), mm(t)) for t in thicknesses if t in prng]
    out += ["DEFINE MATERIAL START", "ISOTROPIC STEEL", "E 2.05e+008", "POISSON 0.3", "DENSITY 76.8195", "ALPHA 1.2e-005",
            "DAMP 0.03", "END DEFINE MATERIAL", "MEMBER PROPERTY AMERICAN"]
    for key, line in zip(order, lines):
        out += ["* " + " ".join(str(k) for k in key), "%s %s" % (R(rng[key]), line)]
    out += ["CONSTANTS", "MATERIAL STEEL ALL"]
    out += ["BETA %g MEMB %s" % (b, R(rng[k])) for k, b in zip(order, betas) if b]
    out.append("MEMBER OFFSET")
    for key, d in zip(order, offs):
        if d:
            o = off(d)
            out += ["%s START %g %g %g" % ((R(rng[key]),) + o), "%s END %g %g %g" % ((R(rng[key]),) + o)]
    out += ["SUPPORTS", wrap(["%d" % n for n in sorted(set(groups["SUP"]))], 14) + " PINNED",
            "LOAD 1 LOADTYPE Dead TITLE SELF WEIGHT", "SELFWEIGHT Y -1", "PERFORM ANALYSIS PRINT STATICS CHECK", "FINISH"]
    text = "\n".join(out) + "\n"
    stats = {"joints": len(jl), "members": len(mem), "plates": len(pl), "supports": len(set(groups["SUP"]))}
    return text, stats
