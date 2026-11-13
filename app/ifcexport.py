"""Write a scene as an IFC file, in IFC2X3 or IFC4X3."""
from . import geometry
from .ifc.kit import Model
from .scene import TYPES, UNITS, SceneError, normalise

SCHEMAS = ("IFC2X3", "IFC4X3")
_RETAINING = ("sheet pile", "bulkhead", "seawall", "quay", "retaining", "cutoff", "deadman", "gravity", "dock wall")
_FACILITY = [(("pier", "jetty"), "JETTY"), (("wharf", "quay", "bulkhead"), "QUAY"), (("floating", "marina"), "FLOATINGDOCK"),
             (("breakwater",), "BREAKWATER"), (("revetment", "seawall"), "REVETMENT"), (("dry dock", "drydock"), "DRYDOCK"),
             (("ramp", "slipway"), "SLIPWAY")]


def ifc_class(comp, schema):
    """Return (class, predefined type, object type) for a component in the given schema."""
    t, kind = comp["type"], comp["kind"]
    x3 = schema == "IFC4X3"
    label = (kind or TYPES[t]["title"]).upper()
    has = lambda *words: any(w in kind for w in words)
    if t == "pile":
        return "IfcPile", "USERDEFINED", (kind or "pile").upper() + " - " + comp["params"]["shape"].upper()
    if t == "block":
        if has("cap"):
            return "IfcFooting", "PILE_CAP", label
        if has("footing", "mooring block", "deadman"):
            return "IfcFooting", "PAD_FOOTING", label
        return "IfcBuildingElementProxy", ("USERDEFINED" if x3 else None), label
    if t == "slab":
        return "IfcSlab", ("BASESLAB" if has("mat", "floor", "base") else "FLOOR"), label
    if t == "beam":
        if has("handrail", "guardrail", "railing"):
            return "IfcRailing", ("GUARDRAIL" if has("guard") else "HANDRAIL"), label
        if has("tie"):
            return "IfcMember", ("TIEBAR" if x3 else None), label
        if has("brace"):
            return "IfcMember", ("BRACE" if x3 else None), label
        if has("waler", "pipe", "strut"):
            return "IfcMember", ("MEMBER" if x3 else None), label
        if x3:
            return "IfcBeam", ("PIERCAP" if has("cap") else ("BEAM" if not kind or has("beam", "stringer") else "USERDEFINED")), label
        return "IfcBeam", None, label
    if t == "wall":
        if not x3:
            return "IfcWall", None, label
        return "IfcWall", ("WAVEWALL" if has("wave") else ("RETAININGWALL" if has(*_RETAINING) else "STANDARD")), label
    if t == "section_sweep":
        if has("wall"):
            return "IfcWall", (("WAVEWALL" if has("crown", "wave") else "RETAININGWALL") if x3 else None), label
        if has("floor"):
            return "IfcSlab", "BASESLAB", label
        if x3 and not has("dredge", "cut"):
            if has("armour", "armor"):
                return "IfcCourse", "ARMOUR", label
            if has("core"):
                return "IfcCourse", "CORE", label
            if has("underlayer", "filter", "bedding"):
                return "IfcCourse", "FILTER", label
            if has("fill"):
                return "IfcEarthworksFill", "BACKFILL", label
            return "IfcCourse", "PROTECTION", label
        return "IfcBuildingElementProxy", ("USERDEFINED" if x3 else None), ("DREDGE LIMIT" if has("dredge", "cut") else label)
    if t == "fender":
        return ("IfcImpactProtectionDevice", "FENDER", label) if x3 else ("IfcDiscreteAccessory", None, label)
    if t == "mooring":
        if not x3:
            return "IfcDiscreteAccessory", None, label
        return "IfcMooringDevice", ("BOLLARD" if has("bollard") else ("MOORINGHOOKS" if has("hook") else "USERDEFINED")), label
    return "IfcElementAssembly", "USERDEFINED", label


def facility_type(structure_type):
    text = structure_type.lower()
    for words, enum in _FACILITY:
        if any(w in text for w in words):
            return enum
    return "USERDEFINED"


def _props(comp, units):
    props = {"ComponentType": TYPES[comp["type"]]["title"], "Kind": comp["kind"] or None, "Source": comp["source"],
             "Note": comp["note"] or None, "LibraryItem": comp.get("library_item")}
    for spec in TYPES[comp["type"]]["params"]:
        val = comp["params"].get(spec["key"])
        if spec["type"] == "number":
            props["%s%s" % (spec["label"], " (%s)" % units if spec.get("length") else "")] = val
        elif spec["type"] in ("choice", "text") and val:
            props[spec["label"]] = val
    return props


def export(raw_scene, schema="IFC2X3", timestamp=None):
    """Return IFC text for a scene. Raises SceneError for a scene that cannot be built."""
    if schema not in SCHEMAS:
        raise SceneError("Choose one of these IFC versions: %s." % ", ".join(SCHEMAS))
    scene = normalise(raw_scene)
    parts, groups = geometry.walk(scene)
    if not parts:
        raise SceneError("Add at least one component before exporting.")
    units = scene["units"]
    stype = scene["structure_type"] or "Marine structure"
    m = Model(scene["name"] or "Marine structure", unit=UNITS[units][0], site=scene["project"] or "Site",
              building=scene["name"] or stype, storey="Datum %s" % (scene["datum"] or "0.00"), author=scene["author"],
              timestamp=timestamp, filename="model.ifc", schema=schema,
              facility_type=facility_type(stype) if schema == "IFC4X3" else "NOTDEFINED")
    if schema == "IFC4X3" and facility_type(stype) == "USERDEFINED":
        m.building.args = m.building.args[:4] + (stype.upper(),) + m.building.args[5:]
    counts = {}
    for part in parts:
        counts[part["comp"]["source"]] = counts.get(part["comp"]["source"], 0) + 1
    m.pset(m.building, "P2I_Model", {
        "StructureType": stype, "Datum": scene["datum"] or None, "Units": units, "Description": scene["description"] or None,
        "SourceDrawings": scene["source_drawings"] or None, "Pieces": float(len(parts)),
        "PiecesBySource": ", ".join("%s %d" % (k, counts[k]) for k in sorted(counts)) or None,
        "Notice": "Reference model built from reviewed drawing values. Not for construction."})
    styles, elements = {}, {}
    for grp in groups:
        cls, pt, otype = ifc_class(grp["comp"], schema)
        parent = elements[grp["parent"]] if grp["parent"] is not None else None
        elements[grp["key"]] = m.element(cls, grp["name"], None, predefined=pt, otype=otype, desc=grp["comp"]["note"] or None,
                                         props=_props(grp["comp"], units), parent=parent, pset_name="P2I_Component")
    for part in parts:
        comp = part["comp"]
        mat, rgb, tr = geometry.appearance(comp)
        key = (mat, rgb, tr)
        if key not in styles:
            styles[key] = m.style(mat, rgb, tr)
        items = []
        for solid in part["solids"]:
            if solid[0] == "extrude":
                _, profile, o, w, u, depth = solid
                if profile[0] == "poly":
                    prof = m.polygon(profile[1])
                elif profile[0] == "circle":
                    prof = m.circle(None, profile[1])
                else:
                    prof = m.ring(None, profile[1], profile[2])
                items.append(m.extrude(prof, m.a3(o, w, u), depth))
            else:
                items.append(m.brep(solid[1]))
        cls, pt, otype = ifc_class(comp, schema)
        parent = elements[part["parent"]] if part["parent"] is not None else None
        m.element(cls, part["name"], items, styles[key], mat, otype=otype, desc=comp["note"] or None,
                  props=_props(comp, units), predefined=pt, parent=parent, pset_name="P2I_Component")
    return m.finish()
