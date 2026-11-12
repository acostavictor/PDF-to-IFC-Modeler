"""Floating caisson gate (worked example: Dry Dock No. 4 caisson).

Units: feet. Origin: midship (frame 0) on the centreline at the underside of the keel.
+x forward, +y port, +z up. Depths in the parameters are measured down from the top deck.
"""
import math

from ..ifc.kit import Model
from .base import P, resolve, provenance_props, require

ID = "caisson_gate"
TITLE = "Floating caisson gate"
SUMMARY = ("A ship-shaped steel gate: shell plating, raked stems and keel, top and machinery decks, side "
           "stringers, watertight bulkheads, major transverse frames, concrete ballast and valve markers.")
UNIT = "ft"
LOOK_FOR = ("outboard elevation, deck plans, transverse sections at a major frame and at a bulkhead, "
            "frame numbering and spacing")

PARAMS = [
    P("depth", "Moulded depth, underside of keel to top deck", 49.667, "ft", "Hull", "Convert feet-inches to decimal feet."),
    P("levels", "Deck and stringer levels, depth below top deck", [7.833, 15.542, 23.25, 30.958, 38.667], "ft", "Hull",
      "From the top down, ending with the lowest level (top of ballast).", "list"),
    P("deck_depth", "Full-width deck level, depth below top deck", 23.25, "ft", "Hull",
      "The level in the list above that is a full plated deck (machinery deck)."),
    P("keel_top_depth", "Top of keel, depth below top deck", 47.167, "ft", "Hull", ""),
    P("half_breadth", "Half-breadth of the hull by depth", [[0, 9.333], [4, 9.59], [7.833, 9.73], [12, 9.89],
      [15.542, 10.0], [38.667, 10.0], [47.167, 2.0]], "ft", "Hull",
      "One row per point on the transverse section: depth below top deck, half-breadth.", "table",
      [{"name": "depth below top deck", "type": "number"}, {"name": "half-breadth", "type": "number"}]),
    P("half_length_top", "Half length overall at the top deck", 78.24, "ft", "Ends", "Half of the length over the stems."),
    P("stem_rake", "Stem rake, horizontal run per foot of depth", 0.1227, "", "Ends", "Total rake divided by the depth it occurs over."),
    P("stem_half_width", "Stem and keel half-width", 2.0, "ft", "Ends", ""),
    P("stem_t", "Stem thickness", 2.52, "ft", "Ends", ""),
    P("knuckle_x0", "End taper knuckle at top deck, distance from midship", 69.55, "ft", "Ends", "Usually scaled."),
    P("knuckle_slope", "End taper knuckle, run toward midship per foot of depth", 0.189, "", "Ends", "Usually scaled."),
    P("hopper_end", "End of hopper, distance from midship", 65.57, "ft", "Ends", "Usually scaled."),
    P("end_flat_depth", "Underside of end trunk, depth below top deck", 42.77, "ft", "Ends", "Usually scaled."),
    P("arc_cx", "Forefoot arc centre, distance from midship", 67.56, "ft", "Ends", "Usually scaled."),
    P("arc_depth", "Forefoot arc centre, depth below top deck", 44.4, "ft", "Ends", ""),
    P("arc_r_out", "Forefoot outer radius", 5.27, "ft", "Ends", ""),
    P("arc_r_in", "Forefoot inner radius", 2.77, "ft", "Ends", ""),
    P("frame_spacing", "Frame spacing", 2.0, "ft", "Framing", ""),
    P("major_frames", "Major frame numbers (each side of midship)", [0, 4, 8, 12, 16, 20, 24], "", "Framing", "", "list"),
    P("bulkhead_frame", "Watertight bulkhead frame number", 28.0, "", "Framing", "Mirrored fore and aft."),
    P("stringer_w", "Side stringer width", 2.1, "ft", "Framing", "Usually scaled."),
    P("valves", "Valves on the full deck", [["FTTFV", 52.5, 5.0], ["FTTDV", 52.5, 0.0], ["FTTDV2", 52.5, -5.0],
      ["FV1", 28.9, 7.0], ["DWP1D", 28.9, -7.0], ["FV2", -28.9, -7.0], ["DWP2D", -28.9, 7.0], ["ATTFV", -52.4, -5.0],
      ["ATTDV", -52.4, 0.0], ["ATTDV2", -52.4, 5.0]], "ft", "Outfit",
      "One row per valve: tag, distance forward of midship (negative aft), offset to port (negative starboard).", "table",
      [{"name": "tag", "type": "text"}, {"name": "x", "type": "number"}, {"name": "y", "type": "number"}]),
]

NOM_T = 0.042      # nominal 1/2 in plate where the drawings give no thickness


def build(params, meta=None):
    meta = meta or {}
    v, prov = resolve(PARAMS, params)
    D = v["depth"]
    levels = sorted(v["levels"])
    hb = sorted(v["half_breadth"])
    KT, G1 = v["keel_top_depth"], levels[-1]
    require(D > 5, "depth looks wrong")
    require(len(hb) >= 2 and hb[0][0] == 0, "half-breadth table must start at depth 0 (top deck)")
    require(all(0 < d < KT for d in levels), "every level must lie between the top deck and the top of keel")
    require(KT < D, "top of keel must be above the underside of keel")
    require(any(abs(d - v["deck_depth"]) < 1e-6 for d in levels), "the full deck level must be one of the listed levels")
    require(G1 < v["end_flat_depth"] < KT, "underside of end trunk must lie between the lowest level and the top of keel")
    SW, ST, LT, RAKE = v["stem_half_width"], v["stem_t"], v["half_length_top"], v["stem_rake"]
    HOP, EF = v["hopper_end"], v["end_flat_depth"]
    z = lambda d: D - d

    def b(d):
        if d <= hb[0][0]:
            return hb[0][1]
        for (d0, b0), (d1, b1) in zip(hb[:-1], hb[1:]):
            if d <= d1:
                return b0 + (b1 - b0) * (d - d0) / (d1 - d0) if d1 > d0 else b1
        return hb[-1][1]

    e_out = lambda d: LT - RAKE * d
    e_in = lambda d: e_out(d) - ST
    ts = lambda d: v["knuckle_x0"] - v["knuckle_slope"] * d
    require(e_in(0) > ts(0) > 0, "end taper knuckle must lie between midship and the stem")

    def ring(d, t=None, bb=None, e=None):
        t = ts(d) if t is None else t
        bb = b(d) if bb is None else bb
        e = e_in(d) if e is None else e
        zz = z(d)
        return [(t, bb, zz), (e, SW, zz), (e, -SW, zz), (t, -bb, zz), (-t, -bb, zz), (-e, -SW, zz), (-e, SW, zz), (-t, bb, zz)]

    name = meta.get("project_name") or "Floating caisson gate"
    m = Model(name, unit="FOOT", site=meta.get("site") or "Site", building=meta.get("facility") or "Dry dock",
              storey="Underside of keel", author=meta.get("author") or "", timestamp=meta.get("timestamp"),
              filename=meta.get("filename") or "caisson_gate.ifc")
    m.pset(m.building, "ModelInputs", provenance_props(PARAMS, v, prov))
    src = meta.get("source") or "Uploaded drawings"
    conf = {k: p["source"] for k, p in prov.items()}

    def tag(*keys):
        order = ["example default", "assumed", "scaled", "derived", "dimensioned"]
        return {"SourceDrawings": src, "Confidence": min((conf[k] for k in keys), key=order.index)}

    st = {"shell": m.style("Shell plating", (0.42, 0.47, 0.52), 0.55), "deck": m.style("Deck plating", (0.55, 0.58, 0.60)),
          "bhd": m.style("Bulkhead", (0.75, 0.55, 0.25), 0.2), "frame": m.style("Framing", (0.80, 0.30, 0.20)),
          "keel": m.style("Keel and stems", (0.20, 0.22, 0.26)), "conc": m.style("Concrete ballast", (0.70, 0.70, 0.66)),
          "valve": m.style("Valves", (0.10, 0.55, 0.30))}
    gate = m.element("IfcElementAssembly", "CAISSON GATE", None, predefined="USERDEFINED", otype="FLOATING_CAISSON_GATE")
    STEEL = "Steel plate"

    # shell: rings at every half-breadth point and level down to the lowest level, then the end trunk and hopper
    depths = sorted(set([d for d, _ in hb if d < G1] + levels))
    rings = [ring(d) for d in depths]
    bf = b(EF)
    rings.append(ring(EF, t=HOP, bb=bf))
    r_flat = ring(EF, t=HOP, bb=bf, e=HOP)
    r_keel = ring(KT, t=HOP, bb=SW, e=HOP)
    seq = rings + [r_flat, r_keel]
    sides = {"A": [], "B": []}
    for r0, r1 in zip(seq[:-1], seq[1:]):
        for i in range(8):
            j = (i + 1) % 8
            if i in (1, 5) and r0 is not r_flat and r1 is not r_flat:
                continue                      # stem faces are covered by the stem bar
            q = [r0[i], r0[j], r1[j], r1[i]]
            total = sum(pt[1] for pt in q)
            if abs(total) > 1e-6:
                sides["A" if total > 0 else "B"].append(q)
            else:                             # faces straddling the centreline are split along it
                m0 = ((q[0][0] + q[1][0]) / 2, 0.0, (q[0][2] + q[1][2]) / 2)
                m1 = ((q[2][0] + q[3][0]) / 2, 0.0, (q[2][2] + q[3][2]) / 2)
                for h in ([q[0], m0, m1, q[3]], [m0, q[1], q[2], m1]):
                    sides["A" if sum(pt[1] for pt in h) > 0 else "B"].append(h)
    for s, nm in (("A", "port"), ("B", "starboard")):
        m.element("IfcPlate", "SHELL_PLATING_SIDE_%s" % s, [m.surface(sides[s])], st["shell"], STEEL, otype="SHELL_PLATING",
                  desc="Side %s (%s) shell, end tapers and hopper plating, modelled as a surface without thickness." % (s, nm),
                  props=tag("half_breadth", "depth", "knuckle_x0", "knuckle_slope", "hopper_end", "end_flat_depth"), parent=gate)

    def arc(r, a0, a1, n=10):
        return [(v["arc_cx"] + r * math.cos(math.radians(a0 + (a1 - a0) * k / (n - 1))),
                 z(v["arc_depth"]) + r * math.sin(math.radians(a0 + (a1 - a0) * k / (n - 1)))) for k in range(n)]

    outer = [(e_out(0), D)] + arc(v["arc_r_out"], 0, -90)
    inner = arc(v["arc_r_in"], -90, 0) + [(e_in(0), D)]
    band = outer + [(-x, zz) for x, zz in reversed(outer)] + [(-x, zz) for x, zz in reversed(inner)] + inner
    m.element("IfcMember", "KEEL_AND_STEMS", [m.ext_y(band, -SW, SW)], st["keel"], STEEL, otype="KEEL_STEM_SEAL_BAR",
              desc="Continuous keel and raked stems that carry the seals.",
              props=tag("half_length_top", "stem_rake", "stem_half_width", "stem_t", "arc_cx", "arc_r_out"), parent=gate)
    e0, b0 = e_in(0), b(0)
    m.element("IfcPlate", "DECK_TOP", [m.ext_z([(e0, b0), (e0, -b0), (-e0, -b0), (-e0, b0)], D - NOM_T, NOM_T)], st["deck"],
              STEEL, otype="DECK_PLATING", desc="Top deck. Camber, hatches and deck fittings not modelled; nominal 1/2 in plate.",
              props=tag("depth", "half_breadth", "half_length_top"), parent=gate)
    dk = v["deck_depth"]
    m.element("IfcPlate", "DECK_MACHINERY", [m.ext_z([(p[0], p[1]) for p in ring(dk)][::-1], z(dk) - NOM_T, NOM_T)],
              st["deck"], STEEL, otype="DECK_PLATING", desc="Full-width deck at %g ft below the top deck; nominal 1/2 in plate." % dk,
              props=tag("deck_depth", "levels"), parent=gate)
    sw = v["stringer_w"]
    for d in levels[:-1]:
        if abs(d - dk) < 1e-6:
            continue
        t, bb = ts(d), b(d)
        items = [m.ext_z([(t, sg * bb), (t, sg * (bb - sw)), (-t, sg * (bb - sw)), (-t, sg * bb)][::sg], z(d) - NOM_T, NOM_T)
                 for sg in (1, -1)]
        m.element("IfcPlate", "STRINGER_%gft" % d, items, st["deck"], STEEL, otype="SIDE_STRINGER",
                  desc="Side stringer plates, both sides, parallel body only.", props=tag("levels", "stringer_w"), parent=gate)
    sec_d = sorted(set([d for d, _ in hb] + [KT]))
    section = [(b(d), z(d)) for d in sec_d] + [(-b(d), z(d)) for d in reversed(sec_d)]
    fs = v["frame_spacing"]
    xb = v["bulkhead_frame"] * fs
    for sg, nm in ((1, "FWD"), (-1, "AFT")):
        m.element("IfcPlate", "WT_BULKHEAD_%s" % nm, [m.ext_x(section, sg * xb - NOM_T / 2, sg * xb + NOM_T / 2)], st["bhd"],
                  STEEL, otype="WATERTIGHT_BULKHEAD", desc="Watertight bulkhead at frame %g %s; stiffeners not modelled." % (v["bulkhead_frame"], nm.lower()),
                  props=tag("bulkhead_frame", "frame_spacing"), parent=gate)
    hbar = m.rect("Frame member (placeholder)", 0.33, 0.5)
    tiers = list(zip([0.0] + levels[:-1], levels))
    for n in sorted(v["major_frames"]):
        for sg in ((1, -1) if n else (1,)):
            x = sg * n * fs
            items = []
            for d in levels:
                if abs(d - dk) < 1e-6:
                    continue
                items.append(m.sweep(hbar, (x, -b(d), z(d) - 0.25), (x, b(d), z(d) - 0.25), (1, 0, 0)))
            for up, lo in tiers:
                for s2 in (1, -1):
                    items.append(m.sweep(hbar, (x, 0, z(up) - 0.5), (x, s2 * (b(lo) - 0.8), z(lo) + 0.6), (1, 0, 0)))
            label = ("%02d%s" % (n, "F" if sg > 0 else "A")) if n else "00"
            m.element("IfcMember", "MAJOR_FRAME_%s" % label, items, st["frame"], STEEL, otype="TRANSVERSE_MAJOR_FRAME",
                      desc="Horizontal members and chevron bracing per tier. Member sizes are placeholders.",
                      props=dict(tag("major_frames", "frame_spacing", "levels"), FrameNumber=n, Station_ft=x), parent=gate)

    def rect3(d, xe):
        bb = b(d)
        return [(xe, bb, z(d)), (xe, -bb, z(d)), (-xe, -bb, z(d)), (-xe, bb, z(d))]

    rs = [rect3(G1, ts(G1)), rect3(EF, HOP), [(HOP, SW, z(KT)), (HOP, -SW, z(KT)), (-HOP, -SW, z(KT)), (-HOP, SW, z(KT))]]
    faces = [rs[0][::-1], rs[-1]]
    for r0, r1 in zip(rs[:-1], rs[1:]):
        for i in range(4):
            j = (i + 1) % 4
            faces.append([r0[i], r0[j], r1[j], r1[i]])
    m.element("IfcBuildingElementProxy", "CONCRETE_BALLAST", [m.brep(faces)], st["conc"], "Concrete", otype="CONCRETE_FILL",
              desc="Concrete fill in the hopper, modelled up to the lowest level.", props=tag("levels", "hopper_end", "end_flat_depth"),
              parent=gate)
    stem = m.circle("Valve marker", 0.5)
    for tagname, x, y in v["valves"]:
        m.element("IfcFlowController", tagname, [m.extrude(stem, m.a3((x, y, z(dk))), 1.5)], st["valve"], None,
                  otype="VALVE_OPERATOR_LOCATION", desc="Valve position marker on the full deck.", props=tag("valves"), parent=gate)
    return m.finish()
