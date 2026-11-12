"""Graving dry dock structure (worked example: Dry Dock No. 5 general dredging plan).

Units: feet. Origin: dock centreline at the inside face of the head wall, elevation 0.00 of the
drawing datum. +x is the station toward the outer sill, +y the offset from centreline, +z elevation.
"""
from ..ifc.kit import Model
from .base import P, resolve, provenance_props, require

ID = "dry_dock"
TITLE = "Dry dock structure"
SUMMARY = ("A rectangular graving dock: floor slab, two side walls, head wall, outer sill with caisson "
           "grooves, gravel bed, cutoff sheet piling and the dredge limit.")
UNIT = "ft"
LOOK_FOR = ("transverse section through the dock, longitudinal section on the centreline, plan with "
            "stationing, sill and caisson seat details")

PARAMS = [
    P("length", "Length, head wall to outer sill line", 1102.33, "ft", "Alignment",
      "Overall dimension along the centreline; convert feet-inches to decimal feet."),
    P("concrete_end", "Station where the sill concrete ends", 1111.33, "ft", "Alignment",
      "Outer sill line plus the outer caisson groove and its lip."),
    P("half_width", "Half clear width between wall faces", 75.0, "ft", "Chamber", "Half of the face-to-face width."),
    P("wall_t", "Side wall thickness", 17.0, "ft", "Chamber", "Gross thickness; galleries are not modelled."),
    P("head_wall_t", "Head wall thickness", 14.67, "ft", "Chamber", ""),
    P("coping_el", "Coping (top of wall) elevation", 14.0, "ft", "Elevations", ""),
    P("floor_el", "Finished floor elevation", -37.3, "ft", "Elevations", ""),
    P("slab_bottom_el", "Underside of floor slab elevation", -55.3, "ft", "Elevations",
      "Floor elevation minus the slab thickness."),
    P("dredge_bottom_el", "Dredge bottom elevation", -57.3, "ft", "Elevations", "Underside of the gravel bed."),
    P("ground_el", "Existing ground at top of slope", 11.0, "ft", "Elevations", ""),
    P("toe_half_width", "Dredge toe, offset from centreline", 97.0, "ft", "Dredging", ""),
    P("side_slope", "Side slope, horizontal run per 1 vertical", 1.75, "", "Dredging", "'1 on 1 3/4' is 1.75."),
    P("head_toe_offset", "Dredge toe beyond the head wall inside face", 19.67, "ft", "Dredging",
      "Head wall thickness plus the toe clearance."),
    P("sill_start", "Station where the sill block starts", 1061.33, "ft", "Sill", ""),
    P("grooves", "Caisson grooves", [[1077.33, 1084.33], [1102.33, 1109.33]], "ft", "Sill",
      "One row per groove: start and end station.", "table",
      [{"name": "start station", "type": "number"}, {"name": "end station", "type": "number"}]),
    P("groove_depth", "Caisson groove depth", 2.0, "ft", "Sill", ""),
    P("thick_start", "Thickened floor section, start station", 895.33, "ft", "Floor", "Use equal start and end to omit."),
    P("thick_end", "Thickened floor section, end station", 965.33, "ft", "Floor", ""),
    P("thick_extra", "Extra slab depth in the thickened section", 2.0, "ft", "Floor", ""),
    P("sheet_pile_tip_el", "Cutoff sheet pile tip elevation", -78.0, "ft", "Sheet piling",
      "Often not annotated; scale it and mark it scaled."),
    P("fill_run", "Riverward gravel fill, length beyond the sill", 50.0, "ft", "Riverward fill", "Use 0 to omit."),
    P("fill_els", "Riverward fill elevations", [-42.5, -39.4, -50.0, -52.5], "ft", "Riverward fill",
      "Top at sheet piling, top at far end, bottom at far end, bottom at sheet piling.", "list"),
]


def rect(a, b, c, d):
    return [(a, c), (b, c), (b, d), (a, d)]


def build(params, meta=None):
    meta = meta or {}
    v, prov = resolve(PARAMS, params)
    L, END, hw, wt = v["length"], v["concrete_end"], v["half_width"], v["wall_t"]
    FL, SB, DB, COP = v["floor_el"], v["slab_bottom_el"], v["dredge_bottom_el"], v["coping_el"]
    require(L > 10, "length looks wrong")
    require(END >= L, "the sill concrete must end at or beyond the outer sill line")
    require(COP > FL > SB >= DB, "elevations must run coping > floor > slab underside >= dredge bottom")
    require(0 < v["sill_start"] < END, "sill start must lie inside the dock length")
    require(v["toe_half_width"] >= hw + wt, "dredge toe must be outside the side walls")
    grooves = sorted(v["grooves"])
    require(all(v["sill_start"] < a < b <= END for a, b in grooves), "each groove must lie inside the sill block")
    require(len(v["fill_els"]) == 4, "riverward fill needs four elevations")
    out = hw + wt
    name = meta.get("project_name") or "Dry dock structure"
    m = Model(name, unit="FOOT", site=meta.get("site") or "Site", building=meta.get("facility") or "Dry dock",
              storey="Drawing datum EL 0.00", author=meta.get("author") or "", timestamp=meta.get("timestamp"),
              filename=meta.get("filename") or "dry_dock.ifc")
    m.pset(m.building, "ModelInputs", provenance_props(PARAMS, v, prov))
    src = meta.get("source") or "Uploaded drawings"
    conf = {k: p["source"] for k, p in prov.items()}

    def tag(*keys):
        order = ["example default", "assumed", "scaled", "derived", "dimensioned"]
        return {"SourceDrawings": src, "Confidence": min((conf[k] for k in keys), key=order.index)}

    conc = m.style("Concrete", (0.72, 0.72, 0.70))
    gravel = m.style("Gravel", (0.62, 0.52, 0.36))
    steel = m.style("Steel sheet piling", (0.30, 0.34, 0.40))
    cut = m.style("Dredge limit", (0.35, 0.55, 0.80), 0.8)
    toe, toe0 = v["toe_half_width"], -v["head_toe_offset"]
    cs, ce, extra = v["thick_start"], v["thick_end"], v["thick_extra"]
    thick = ce > cs and extra > 0

    m.element("IfcSlab", "DOCK_CHAMBER_FLOOR", [m.ext_x(rect(-hw, hw, SB, FL), 0, v["sill_start"])], conc, "Concrete",
              predefined="BASESLAB", desc="Floor slab %g ft thick, finished floor EL %g." % (FL - SB, FL),
              props=tag("floor_el", "slab_bottom_el", "half_width"))
    if thick:
        m.element("IfcSlab", "DOCK_FLOOR_THICKENED_SECTION", [m.ext_x(rect(-out, out, SB - extra, SB), cs, ce)], conc,
                  "Concrete", predefined="BASESLAB", desc="Local slab thickening of %g ft; end transitions not modelled." % extra,
                  props=tag("thick_start", "thick_end", "thick_extra"))
    gz = FL - v["groove_depth"]
    sill = [(v["sill_start"], FL)]
    for a, b in grooves:
        sill += [(a, FL), (a, gz), (b, gz), (b, FL)]
    sill += [(END, FL), (END, SB), (v["sill_start"], SB)]
    clean = [p for i, p in enumerate(sill) if i == 0 or p != sill[i - 1]]
    m.element("IfcSlab", "OUTER_SILL", [m.ext_y(clean, -hw, hw)], conc, "Concrete", predefined="BASESLAB",
              otype="CAISSON_SILL", desc="Outer sill block with %d caisson groove(s)." % len(grooves),
              props=tag("sill_start", "grooves", "groove_depth", "concrete_end"))
    for nm, a, b in (("EAST_SIDE_WALL", hw, out), ("WEST_SIDE_WALL", -out, -hw)):
        m.element("IfcWall", nm, [m.ext_x(rect(a, b, SB, COP), 0, END)], conc, "Concrete", otype="RETAININGWALL",
                  desc="Gross wall outline; galleries and coping details not modelled.",
                  props=dict(tag("wall_t", "coping_el", "half_width"), Thickness_ft=wt))
    m.element("IfcWall", "HEAD_WALL", [m.ext_x(rect(-out, out, SB, COP), -v["head_wall_t"], 0)], conc, "Concrete",
              otype="RETAININGWALL", desc="Head wall as a plain block.", props=tag("head_wall_t", "coping_el"))
    bed = []
    if thick:
        bed = [m.ext_x(rect(-toe, toe, DB, SB), toe0, cs), m.ext_x(rect(-toe, toe, DB - extra, SB - extra), cs, ce),
               m.ext_x(rect(-toe, toe, DB, SB), ce, END)]
    elif SB > DB:
        bed = [m.ext_x(rect(-toe, toe, DB, SB), toe0, END)]
    if bed and SB > DB:
        m.element("IfcBuildingElementProxy", "GRAVEL_BED", bed, gravel, "Gravel", otype="EARTHWORKS FILL - SUBGRADE BED",
                  desc="Gravel fill %g ft thick under the dock." % (SB - DB), props=tag("dredge_bottom_el", "slab_bottom_el", "toe_half_width"))
    if v["fill_run"] > 0:
        e = v["fill_els"]
        w = [(END, e[0]), (END + v["fill_run"], e[1]), (END + v["fill_run"], e[2]), (END, e[3])]
        m.element("IfcBuildingElementProxy", "RIVERWARD_GRAVEL_FILL", [m.ext_y(w, -hw, hw)], gravel, "Gravel",
                  otype="EARTHWORKS FILL - BACKFILL", desc="Gravel fill against the cutoff sheet piling; width assumed equal to the entrance.",
                  props=tag("fill_run", "fill_els"))
    m.element("IfcPile", "CUTOFF_SHEET_PILING", [m.ext_x(rect(-out, out, v["sheet_pile_tip_el"], FL), END, END + 0.5)],
              steel, "Steel sheet piling", predefined="USERDEFINED", otype="STEEL_SHEET_PILE_CUTOFF",
              desc="Cutoff sheet piling at the outer face of the sill, shown 6 in thick.", props=tag("sheet_pile_tip_el"))
    s, top = v["side_slope"], v["ground_el"]
    o = (top - DB) * s
    p = [(toe0, -toe, DB), (END, -toe, DB), (END, toe, DB), (toe0, toe, DB),
         (toe0 - o, -toe - o, top), (END, -toe - o, top), (END, toe + o, top), (toe0 - o, toe + o, top)]
    faces = [[p[3], p[2], p[1], p[0]], [p[4], p[5], p[6], p[7]], [p[0], p[1], p[5], p[4]], [p[1], p[2], p[6], p[5]],
             [p[2], p[3], p[7], p[6]], [p[3], p[0], p[4], p[7]]]
    m.element("IfcBuildingElementProxy", "DREDGE_PRISM", [m.brep(faces)], cut, None, otype="EARTHWORKS CUT - DREDGING",
              desc="Dredge limit: bottom EL %g, toe %g ft each side, slopes 1 on %g to EL %g. Riverward end shown vertical." % (DB, toe, s, top),
              props=tag("dredge_bottom_el", "toe_half_width", "side_slope", "ground_el"))
    return m.finish()
