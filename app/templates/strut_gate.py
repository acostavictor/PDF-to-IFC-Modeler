"""Sloped steel gate propped by inclined struts (worked example: Dry Dock No. 4 intermediate gate).

Units: millimetres. Origin: gate centreline (x = 0) at the work point of the skin's outside face on the
dock floor (y = 0, z = 0). +x along the gate, +y toward the struts, +z up.
"""
import math
import re

from ..ifc.kit import Model
from .base import P, resolve, provenance_props, require

ID = "strut_gate"
TITLE = "Sloped strut gate"
SUMMARY = ("An inclined steel skin plate with vertical plate girders and horizontal bulb-flat stiffeners, "
           "propped by inclined tube struts and tied along the floor. Built as two mirrored halves.")
UNIT = "mm"
LOOK_FOR = ("typical cross-section through the gate, elevation with stiffener and girder labels, "
            "tie and catwalk framing plans, strut base and toe details")

# Bulb flats to EN 10067: b, t, bulb height c, area mm2, centroid from plate mm, Ix mm4 (ArcelorMittal table).
HP = {"HP240X10": (240, 10, 34, 3249.0, 147.7, 1865e4), "HP280X12": (280, 12, 40, 4548.0, 172.3, 3647e4),
      "HP300X12": (300, 12, 43, 4979.0, 187.0, 4459e4), "HP340X12": (340, 12, 49, 5884.0, 216.9, 6757e4)}

_ROWS = [[274, "HP340x12"]] + [[884 + 700 * n, s] for n, s in enumerate(
    ["HP340x12"] * 5 + ["HP300x12"] * 4 + ["HP280x12"] * 3)] + [[884 + 700 * (13 + n), s] for n, s in enumerate(
        ["HP280x12"] * 4 + ["HP240x10"] * 6)]

PARAMS = [
    P("height", "Height, dock floor to top of dock", 14570.0, "mm", "Datums",
      "Vertical dimension between DOCK FINISH FLOOR and TOP OF DOCK on the main cross-section."),
    P("slope_deg", "Skin plate angle from horizontal", 60.0, "deg", "Datums",
      "Angle of the inclined skin plate on the main cross-section."),
    P("half_width", "Gate centreline to face of dock wall", 22885.0, "mm", "Plan",
      "Half of the overall width between dock wall faces, on the elevation or plan."),
    P("end_gap", "Clear gap, gate end to dock wall", 150.0, "mm", "Plan", "Seal gap at each end of the gate."),
    P("cl_gap", "Gap between the two halves at the centreline", 50.0, "mm", "Plan",
      "Total gap between the two gate sections."),
    P("girder_x", "Plate girder lines, distance from centreline", [1245, 3988, 6731, 9731, 12731, 15731, 18731, 21731],
      "mm", "Plan", "Running dimensions to each girder line on one half of the elevation; the other half mirrors.",
      "list"),
    P("skin_zones", "Skin plate zones", [[4606, 12], [10702, 18], [16798, 20]], "mm", "Skin plate",
      "From the top down: slope distance from the top work point to the lower edge of each zone, and its thickness.",
      "table", [{"name": "slope distance from top", "type": "number"}, {"name": "thickness", "type": "number"}]),
    P("web_t", "Girder web thickness", 20.0, "mm", "Plate girders", "Section through the plate girder."),
    P("flange_w", "Girder flange width", 550.0, "mm", "Plate girders", ""),
    P("flange_t", "Girder flange thickness", 25.0, "mm", "Plate girders", ""),
    P("depth_lower", "Girder web depth, lower part", 1000.0, "mm", "Plate girders", ""),
    P("depth_upper", "Girder web depth, upper part", 700.0, "mm", "Plate girders", ""),
    P("knee_lo", "Depth change starts, slope distance from floor", 12080.0, "mm", "Plate girders",
      "Where the girder starts to get shallower. Often not dimensioned: scale it and mark it scaled."),
    P("knee_up", "Depth change ends, slope distance from floor", 12780.0, "mm", "Plate girders", ""),
    P("shoe_top_z", "Bottom of girder above floor", 265.0, "mm", "Plate girders",
      "Top of the bearing shoe above the dock floor, on the toe detail."),
    P("b1_from_top", "Strut-level beam, slope distance from top", 7483.0, "mm", "Strut-level beam",
      "Slope dimension from the top work point to the continuous beam where the struts connect."),
    P("stiffener_rows", "Horizontal stiffener rows", _ROWS, "mm", "Stiffeners",
      "One row per stiffener, bottom to top: slope distance from the floor work point, and the bulb flat size "
      "(for example HP300x12).", "table",
      [{"name": "slope distance from floor", "type": "number"}, {"name": "size", "type": "text"}]),
    P("strut_deg", "Strut angle from horizontal", 47.0, "deg", "Struts", ""),
    P("strut_b", "Strut tube width", 457.2, "mm", "Struts", "TS18x18 is 457.2 mm."),
    P("strut_t", "Strut tube wall thickness", 15.875, "mm", "Struts", "5/8 in is 15.875 mm."),
    P("strut_wp_y", "Strut work point, distance from floor work point", 12953.0, "mm", "Struts",
      "Horizontal distance from the skin work point at the floor to the strut work point."),
    P("strut_wp_z", "Strut work point, height above floor", -345.0, "mm", "Struts",
      "Negative when the work point is below the floor, in a pocket."),
    P("strut_base_len", "Work point to top of base plate, along strut", 146.0, "mm", "Struts", ""),
    P("tie_z", "Tie centreline above floor", 972.0, "mm", "Ties", ""),
    P("tie_b", "Tie tube width", 203.2, "mm", "Ties", "TS8x8 is 203.2 mm."),
    P("tie_t", "Tie tube wall thickness", 12.7, "mm", "Ties", ""),
    P("tie_y", "Longitudinal tie lines, distance from floor work point", [1968, 6340, 11413], "mm", "Ties",
      "From the tie framing plan.", "list"),
    P("bearing_y", "Girder bearing centreline, distance from floor work point", 763.0, "mm", "Bearing",
      "Often given as a dimension from the strut work point; subtract to get this value and mark it derived."),
    P("catwalk_y", "Catwalk stringer lines, distance from floor work point", [7624, 8844, 9911], "mm", "Catwalk",
      "Three stringer lines from the catwalk framing plan.", "list"),
    P("rail_h", "Railing height", 1067.0, "mm", "Catwalk", ""),
    P("post_sp", "Railing post spacing", 1219.0, "mm", "Catwalk", ""),
    P("trench_w", "Gate trench width", 1725.0, "mm", "Concrete context", ""),
    P("trench_d", "Gate trench depth", 390.0, "mm", "Concrete context", ""),
    P("wall_t", "Dock wall thickness shown", 4572.0, "mm", "Concrete context", "Context block only."),
    P("context", "Include dock floor and walls (1 = yes, 0 = no)", 1.0, "", "Concrete context", ""),
]

BASE_PL = (890.0, 610.0, 40.0)
CAP_PL = (530.0, 550.0, 25.0)
C10 = (254.0, 66.0, 6.1, 11.1)
C8 = (203.2, 57.4, 5.6, 9.9)
DECK_T = 7.0
SLAB_T = 760.0
POCKET_D = 528.0
CAT_END_GAP = 75.0


def hp_props(size):
    key = re.sub(r"\s+", "", size).upper()
    if key in HP:
        return HP[key] + (True,)
    m = re.match(r"^HP(\d+(?:\.\d+)?)X(\d+(?:\.\d+)?)$", key)
    require(m, "stiffener size '%s' not understood; use the form HP300x12" % size)
    b, t = float(m.group(1)), float(m.group(2))
    c = round(0.1435 * b)
    area = b * t + 0.75 * c * (0.8 * c)
    return (b, t, c, area, 0.62 * b, None, False)


class Geo(object):
    """All derived geometry for one parameter set."""

    def __init__(self, v):
        self.v = v
        self.H = v["height"]
        a = math.radians(v["slope_deg"])
        self.S, self.C = math.sin(a), math.cos(a)
        b = math.radians(v["strut_deg"])
        self.SS, self.SC = math.sin(b), math.cos(b)
        self.S_TOP = self.H / self.S
        self.X0, self.X1 = v["cl_gap"] / 2.0, v["half_width"] - v["end_gap"]
        self.GX = sorted(v["girder_x"])
        zones = sorted(v["skin_zones"], key=lambda r: r[0])
        self.SKIN = []          # (s_from, s_to, t) measured up the slope from the floor work point
        upper = self.S_TOP
        for dist, t in zones:
            lower = max(self.S_TOP - dist, 0.0)
            self.SKIN.append((lower, upper, t))
            upper = lower
        self.SKIN.sort()
        self.T_LO = self.SKIN[0][2]
        self.S_B1 = self.S_TOP - v["b1_from_top"]
        self.D_FL = self.T_LO + v["depth_lower"] + v["flange_t"]
        self.WP = (v["strut_wp_y"], v["strut_wp_z"])
        self.ROWS = sorted((r[0], r[1]) for r in v["stiffener_rows"])
        d0 = self.sd(*self.WP)[1]
        k = self.SC * self.S + self.SS * self.C
        self.L_FLANGE = (d0 - self.D_FL) / k
        self.L_CAP = (d0 - self.D_FL - CAP_PL[2]) / k
        self.Y_TIE_REF = self.pt(self.s_at_z(v["tie_z"], self.D_FL), self.D_FL)[0]
        self.L_TIE = (v["tie_z"] - self.WP[1]) / self.SS
        self.check()

    def check(self):
        v = self.v
        require(1000 <= self.H <= 60000, "height looks wrong: %g mm" % self.H)
        require(30 <= v["slope_deg"] <= 89, "skin angle must be between 30 and 89 degrees")
        require(20 <= v["strut_deg"] <= 80, "strut angle must be between 20 and 80 degrees")
        require(self.X1 - self.X0 > 1000, "gate half is too short; check half width and gaps")
        require(all(self.X0 < x < self.X1 for x in self.GX), "every girder line must lie inside the gate half")
        require(0 < self.S_B1 < self.S_TOP, "strut-level beam must lie on the skin plate")
        require(0 < v["knee_lo"] <= v["knee_up"] < self.S_TOP, "girder depth change must lie on the skin plate")
        require(all(0 < s < self.S_TOP for s, _ in self.ROWS), "every stiffener row must lie on the skin plate")
        require(len(v["catwalk_y"]) == 3, "catwalk needs exactly three stringer lines")
        require(len(v["tie_y"]) >= 2, "give at least two longitudinal tie lines")
        require(self.L_CAP > v["strut_base_len"] + 500, "strut does not reach the gate; check the strut work point")
        require(self.L_TIE > 0, "tie level must be above the strut work point")

    def pt(self, s, d=0.0):
        """Slope distance s from the floor work point, d perpendicular toward the struts -> (y, z)."""
        return (s * self.C + d * self.S, s * self.S - d * self.C)

    def sd(self, y, z):
        return (y * self.C + z * self.S, y * self.S - z * self.C)

    def s_at_z(self, z, d):
        return (z + d * self.C) / self.S

    def skin_t(self, s):
        for a, b, t in self.SKIN:
            if s <= b:
                return t
        return self.SKIN[-1][2]

    def depth(self, s):
        v = self.v
        if s <= v["knee_lo"]:
            return v["depth_lower"]
        if s >= v["knee_up"]:
            return v["depth_upper"]
        return v["depth_lower"] + (v["depth_upper"] - v["depth_lower"]) * (s - v["knee_lo"]) / max(
            v["knee_up"] - v["knee_lo"], 1e-6)

    def strut_pt(self, length):
        return (self.WP[0] - length * self.SC, self.WP[1] + length * self.SS)


def build(params, meta=None):
    meta = meta or {}
    v, prov = resolve(PARAMS, params)
    g = Geo(v)
    name = meta.get("project_name") or "Sloped strut gate"
    m = Model(name, unit="MILLIMETRE", site=meta.get("site") or "Site", building=meta.get("facility") or "Dry dock",
              storey="Dock finish floor", author=meta.get("author") or "", timestamp=meta.get("timestamp"),
              filename=meta.get("filename") or "strut_gate.ifc")
    m.pset(m.building, "ModelInputs", provenance_props(PARAMS, v, prov))
    src = meta.get("source") or "Uploaded drawings"
    conf = {k: p["source"] for k, p in prov.items()}

    def tag(*keys):
        order = ["example default", "assumed", "scaled", "derived", "dimensioned"]
        worst = min((conf[k] for k in keys), key=order.index)
        return {"SourceDrawings": src, "Confidence": worst}

    st = {"skin": m.style("Skin plate", (0.36, 0.45, 0.55)), "girder": m.style("Plate girder", (0.78, 0.30, 0.18)),
          "stiff": m.style("Bulb flat stiffener", (0.85, 0.65, 0.20)), "strut": m.style("Strut", (0.15, 0.42, 0.58)),
          "tie": m.style("Tie framing", (0.20, 0.60, 0.45)), "cat": m.style("Catwalk", (0.55, 0.57, 0.60)),
          "plate": m.style("Connection plate", (0.20, 0.22, 0.26)), "conc": m.style("Existing concrete", (0.75, 0.75, 0.72), 0.6)}
    M_PL, M_TS, M_HP, M_SH, M_C = ("Steel plate", "Steel tube", "Steel bulb flat", "Steel shapes", "Concrete (existing)")
    H, S_TOP = g.H, g.S_TOP

    def ext_sd(pts, x0, x1):
        return m.ext_x([g.pt(s, d) for s, d in pts], x0, x1)

    ts18 = m.tube("Strut tube %gx%g" % (v["strut_b"], v["strut_t"]), v["strut_b"], v["strut_t"])
    ts8 = m.tube("Tie tube %gx%g" % (v["tie_b"], v["tie_t"]), v["tie_b"], v["tie_t"])
    c10 = m.channel("C10x15.3", *C10)
    c8 = m.channel("C8x11.5", *C8)
    l3 = m.angle("L3x3x5/16", 76.2, 7.9)
    bar = m.circle("1in bar", 12.7)
    z_gt = H - DECK_T - C10[0]
    lo, up, ft, fw, wt = v["depth_lower"], v["depth_upper"], v["flange_t"], v["flange_w"], v["web_t"]
    t_top = g.skin_t(S_TOP)
    cy = v["catwalk_y"]

    for side, sg in (("W", -1), ("E", 1)):
        xa, xb = sg * g.X0, sg * g.X1
        for a, b, t in g.SKIN:
            m.element("IfcPlate", "%s-SKIN-%gmm" % (side, t), [ext_sd([(a, 0), (b, 0), (b, t), (a, t)], xa, xb)],
                      st["skin"], M_PL, otype="SKIN_PLATE",
                      desc="Skin plate %g mm, inclined %g deg; outside face on the work line." % (t, v["slope_deg"]),
                      props=dict(tag("height", "slope_deg", "skin_zones", "half_width"), Thickness_mm=t,
                                 SlopeLength_mm=round(b - a, 1)))
        # plate girders: web profile follows the skin thickness steps, flange follows the depth change
        sbo, sbi = g.s_at_z(v["shoe_top_z"], g.T_LO), g.s_at_z(v["shoe_top_z"], g.T_LO + lo)
        sto, sti = g.s_at_z(z_gt, t_top), g.s_at_z(z_gt, t_top + up)
        web = [(sbo, g.T_LO)]
        for a, b, t in g.SKIN:
            web += [(max(a, sbo), t), (min(b, sto), t)]
        da, db = g.T_LO + lo, t_top + up
        web += [(sti, db), (v["knee_up"], db), (v["knee_lo"], da), (sbi, da)]
        fl = [(sbi, da), (v["knee_lo"], da), (v["knee_up"], db), (sti, db), (g.s_at_z(z_gt, db + ft), db + ft),
              (v["knee_up"], db + ft), (v["knee_lo"], da + ft), (g.s_at_z(v["shoe_top_z"], da + ft), da + ft)]
        gprops = dict(tag("web_t", "flange_w", "flange_t", "depth_lower", "depth_upper", "knee_lo", "knee_up", "girder_x"),
                      WebThickness_mm=wt, FlangeWidth_mm=fw, FlangeThickness_mm=ft, WebDepthLower_mm=lo, WebDepthUpper_mm=up)
        for i, gx in enumerate(g.GX):
            x = sg * gx
            m.element("IfcBeam", "%s-GIRDER-%d" % (side, i + 1),
                      [ext_sd(web, x - wt / 2, x + wt / 2), ext_sd(fl, x - fw / 2, x + fw / 2)], st["girder"], M_PL,
                      otype="PLATE GIRDER", desc="Inclined plate girder: web and one flange on the strut side of the skin.",
                      props=dict(gprops, OffsetFromCL_mm=gx),
                      axis=[(x,) + g.pt(sbo, g.T_LO + lo / 2), (x,) + g.pt(sto, t_top + up / 2)])
        tb = g.skin_t(g.S_B1)
        m.element("IfcBeam", "%s-STRUT-LEVEL-BEAM" % side,
                  [ext_sd([(g.S_B1 - wt / 2, tb), (g.S_B1 + wt / 2, tb), (g.S_B1 + wt / 2, da), (g.S_B1 - wt / 2, da)], xa, xb),
                   ext_sd([(g.S_B1 - fw / 2, da), (g.S_B1 + fw / 2, da), (g.S_B1 + fw / 2, da + ft), (g.S_B1 - fw / 2, da + ft)], xa, xb)],
                  st["girder"], M_PL, otype="STRUT LEVEL BEAM",
                  desc="Continuous horizontal beam where the struts connect: web normal to the skin, one flange.",
                  props=tag("b1_from_top", "web_t", "flange_w", "flange_t"),
                  axis=[(xa,) + g.pt(g.S_B1, da / 2), (xb,) + g.pt(g.S_B1, da / 2)])
        for n, (s, size) in enumerate(g.ROWS):
            bw, bt, c, area, cg, ix, known = hp_props(size)
            ts = g.skin_t(s)
            pr = (area - bw * bt) / (0.75 * c)
            prof = [(s + bt / 2, ts), (s + bt / 2, ts + bw), (s - bt / 2 - pr, ts + bw), (s - bt / 2 - pr, ts + bw - c / 2),
                    (s - bt / 2, ts + bw - c), (s - bt / 2, ts)]
            props = dict(tag("stiffener_rows"), Size=size, SlopeFromFloorWorkPoint_mm=s, Area_mm2=round(area, 1),
                         CentroidFromPlate_mm=round(cg, 1),
                         SectionPropertySource="EN 10067 table" if known else "approximated from the size name")
            if ix:
                props["Ix_mm4"] = ix
            m.element("IfcMember", "%s-STIFFENER-%02d" % (side, n + 1), [ext_sd(prof, xa, xb)], st["stiff"], M_HP,
                      otype="%s BULB FLAT" % size.upper(), desc="Horizontal bulb flat stiffener on the strut side of the skin.",
                      props=props, axis=[(xa,) + g.pt(s, ts + cg), (xb,) + g.pt(s, ts + cg)])
        nb = (g.SS, g.SC)
        for i, gx in enumerate(g.GX):
            x = sg * gx
            p0, p1 = (x,) + g.strut_pt(v["strut_base_len"]), (x,) + g.strut_pt(g.L_CAP)
            m.element("IfcMember", "%s-STRUT-%d" % (side, i + 1), [m.sweep(ts18, p0, p1, (1, 0, 0))], st["strut"], M_TS,
                      otype="STRUT", desc="Inclined tube strut from the base plate to the cap plate on the strut-level beam.",
                      props=dict(tag("strut_deg", "strut_b", "strut_t", "strut_wp_y", "strut_wp_z"),
                                 Length_mm=round(g.L_CAP - v["strut_base_len"], 0)), axis=[p0, p1])
            yb0, zb0 = g.strut_pt(v["strut_base_len"] - BASE_PL[2])
            y1, z1 = g.strut_pt(v["strut_base_len"])
            hb = BASE_PL[0] / 2
            m.element("IfcPlate", "%s-STRUT-BASE-PL-%d" % (side, i + 1),
                      [m.ext_x([(yb0 - hb * nb[0], zb0 - hb * nb[1]), (yb0 + hb * nb[0], zb0 + hb * nb[1]),
                                (y1 + hb * nb[0], z1 + hb * nb[1]), (y1 - hb * nb[0], z1 - hb * nb[1])],
                               x - BASE_PL[1] / 2, x + BASE_PL[1] / 2)], st["plate"], M_PL, otype="STRUT BASE PLATE",
                      desc="Strut base plate; size is a fixed template value.", props={"SourceDrawings": src, "Confidence": "assumed"})
            sc = g.sd(*g.strut_pt(g.L_FLANGE))[0]
            m.element("IfcPlate", "%s-STRUT-CAP-PL-%d" % (side, i + 1),
                      [ext_sd([(sc - CAP_PL[0] / 2, g.D_FL), (sc + CAP_PL[0] / 2, g.D_FL), (sc + CAP_PL[0] / 2, g.D_FL + CAP_PL[2]),
                               (sc - CAP_PL[0] / 2, g.D_FL + CAP_PL[2])], x - CAP_PL[1] / 2, x + CAP_PL[1] / 2)],
                      st["plate"], M_PL, otype="STRUT CAP PLATE", desc="Cap plate on the strut-level beam flange; fixed template size.",
                      props={"SourceDrawings": src, "Confidence": "assumed"})
            w, yf = 305.0, v["bearing_y"] + 590.0
            m.element("IfcDiscreteAccessory", "%s-BEARING-SHOE-%d" % (side, i + 1),
                      [m.box(x - w, x + w, yf - 1042, yf, -305, -265), m.box(x - w, x + w, yf - 40, yf, -265, v["shoe_top_z"]),
                       m.box(x - w, x + w, v["bearing_y"] - 12.5, v["bearing_y"] + 12.5, -265, -10)], st["plate"], M_PL,
                      otype="GIRDER BEARING SHOE", desc="Girder bearing shoe in the gate trench, simplified.",
                      props=tag("bearing_y", "shoe_top_z"))
            t0, t1 = (x, g.Y_TIE_REF, v["tie_z"]), (x,) + g.strut_pt(g.L_TIE)
            m.element("IfcMember", "%s-TIE-T-%d" % (side, i + 1), [m.sweep(ts8, t0, t1, (1, 0, 0))], st["tie"], M_TS,
                      otype="TIE", desc="Transverse tie from the girder flange to the strut.", props=tag("tie_z", "tie_b", "tie_t"),
                      axis=[t0, t1])
        ty = sorted(v["tie_y"])
        for j, y in enumerate(ty):
            a0, a1 = (sg * g.GX[0], y, v["tie_z"]), (sg * g.GX[-1], y, v["tie_z"])
            m.element("IfcMember", "%s-TIE-L-%d" % (side, j + 1), [m.sweep(ts8, a0, a1, (0, 1, 0))], st["tie"], M_TS,
                      otype="TIE", desc="Longitudinal tie line.", props=tag("tie_y", "tie_z"), axis=[a0, a1])
        for i in range(len(g.GX) - 1):
            a0, a1 = (sg * g.GX[i], ty[0], v["tie_z"]), (sg * g.GX[i + 1], ty[1], v["tie_z"])
            m.element("IfcMember", "%s-TIE-D-%d" % (side, i + 1), [m.sweep(ts8, a0, a1, (0, 0, 1))], st["tie"], M_TS,
                      otype="TIE DIAGONAL", desc="Plan diagonal in the tie framing.", props=tag("tie_y", "girder_x"),
                      axis=[a0, a1])
        # catwalk
        xc, zt = sg * (v["half_width"] - CAT_END_GAP), H - DECK_T
        zc = zt - C10[0] / 2
        m.element("IfcPlate", "%s-CATWALK-DECK" % side, [m.box(xa, xc, cy[0], cy[2], zt, H)], st["cat"], M_SH,
                  otype="CATWALK DECK PLATE", desc="Deck plate; top at top of dock.", props=tag("catwalk_y", "height"))
        for j, y in enumerate(cy):
            a0, a1 = (xa, y, zc), (xc, y, zc)
            m.element("IfcBeam", "%s-CATWALK-STRINGER-%d" % (side, j + 1), [m.sweep(c10, a0, a1, (0, 1, 0))], st["cat"],
                      M_SH, otype="C10x15.3", desc="Catwalk stringer.", props=tag("catwalk_y"), axis=[a0, a1])
        xs = [(gx, c10, C10[0], cy[0], cy[2]) for gx in g.GX]
        xs += [(g.X0 + 40, c10, C10[0], cy[0], cy[2]), (v["half_width"] - CAT_END_GAP - 40, c10, C10[0], cy[0], cy[2])]
        for g0, g1 in zip(g.GX[:-1], g.GX[1:]):
            xs += [(g0 + (g1 - g0) / 3, c8, C8[0], cy[0], cy[1]), (g0 + 2 * (g1 - g0) / 3, c8, C8[0], cy[0], cy[1]),
                   ((g0 + g1) / 2, c10, C10[0], cy[1], cy[2])]
        items = [m.sweep(pr, (sg * gx, y0 + C10[1] / 2, zt - dep / 2), (sg * gx, y1 - C10[1] / 2, zt - dep / 2), (1, 0, 0))
                 for gx, pr, dep, y0, y1 in xs]
        m.element("IfcBeam", "%s-CATWALK-CROSS-FRAMING" % side, items, st["cat"], M_SH, otype="C10x15.3 / C8x11.5",
                  desc="Catwalk cross members at girder lines and typical intermediates; sizes are fixed template values.",
                  props={"SourceDrawings": src, "Confidence": "assumed"})
        for j, y in enumerate(cy[:2]):
            items = [m.sweep(bar, (xa, y, H + h), (xc, y, H + h), (0, 1, 0)) for h in (v["rail_h"], v["rail_h"] / 2)]
            span = abs(xc - xa)
            n = int(span // v["post_sp"])
            for k in range(n + 1):
                px = xa + sg * (span - n * v["post_sp"]) / 2 + sg * k * v["post_sp"]
                items.append(m.sweep(l3, (px, y, H), (px, y, H + v["rail_h"]), (1, 0, 0)))
            m.element("IfcRailing", "%s-CATWALK-RAILING-%d" % (side, j + 1), items, st["cat"], M_SH, otype="HANDRAIL",
                      predefined="HANDRAIL", desc="Posts with top and mid rails.", props=tag("rail_h", "post_sp"))

    if v["context"] >= 0.5:
        ya, yb, yp = -3000.0, max(16000.0, g.WP[0] + 3000.0), g.WP[0] - 1150.0
        run = POCKET_D / math.tan(math.radians(90 - v["strut_deg"]))
        floor = [(ya, 0), (0, 0), (0, -v["trench_d"]), (v["trench_w"], -v["trench_d"]), (v["trench_w"], 0), (yp, 0),
                 (yp, -POCKET_D), (g.WP[0] - 214, -POCKET_D), (g.WP[0] - 214 + run, 0), (yb, 0), (yb, -SLAB_T), (ya, -SLAB_T)]
        hw = v["half_width"]
        m.element("IfcSlab", "DOCK-FLOOR-SLAB", [m.ext_x(floor, -hw, hw)], st["conc"], M_C, predefined="BASESLAB",
                  otype="EXISTING DOCK FLOOR (CONTEXT)",
                  desc="Dock floor with the gate trench and strut pocket as continuous slots. Simplified context only.",
                  props=tag("trench_w", "trench_d"))
        for side, sg in (("W", -1), ("E", 1)):
            m.element("IfcWall", "%s-DOCK-WALL" % side, [m.box(sg * hw, sg * (hw + v["wall_t"]), ya, yb, -SLAB_T, H)],
                      st["conc"], M_C, otype="EXISTING DOCK WALL (CONTEXT)", desc="Dock side wall as a simple block.",
                      props=tag("half_width", "wall_t"))
    return m.finish()
