"""Regenerate app/seed.json: the starter library and example models. Run: python3 tools/make_seed.py

Sizes are generic examples in feet, apart from the dry dock, which uses values read from the Dry Dock
No. 5 general dredging plan. Nothing here is a design recommendation.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app import scene, ifcexport  # noqa: E402

EX = "Generic example value."


def comp(type_, name, kind="", params=None, **extra):
    d = {"type": type_, "name": name, "kind": kind, "params": params or {}, "source": "library", "note": ""}
    d.update(extra)
    return d


def pile(name, shape, size, top, tip, kind="bearing pile", **extra):
    p = {"shape": shape, "size": size, "top_el": top, "tip_el": tip}
    p.update(extra.pop("more", {}))
    return comp("pile", name, kind, p, **extra)


LIB = []


def lib(category, name, description, item, tags=""):
    LIB.append({"name": name, "category": category, "description": description, "tags": tags, "units": "ft", "item": item})


lib("Piles", "Pile, 24 in octagonal prestressed concrete", "Plumb bearing pile, head at +8, tip at -60.",
    pile("24 in octagonal pile", "octagonal", 2.0, 8.0, -60.0, material="Prestressed concrete"), "concrete, bearing")
lib("Piles", "Pile, 18 in square prestressed concrete", "Plumb bearing pile, head at +8, tip at -50.",
    pile("18 in square pile", "square", 1.5, 8.0, -50.0, material="Prestressed concrete"), "concrete, bearing")
lib("Piles", "Pile, 24 in steel pipe", "Plumb pipe pile with 1/2 in wall.",
    pile("24 in pipe pile", "pipe", 2.0, 8.0, -70.0, material="Steel", more={"wall": 0.042}), "steel, pipe")
lib("Piles", "Batter pile, 24 in steel pipe, 1H:4V", "Battered pipe pile; set the batter direction after placing.",
    pile("24 in batter pile", "pipe", 2.0, 8.0, -70.0, kind="batter pile", material="Steel", more={"wall": 0.042, "batter": 0.25}), "steel, batter")
lib("Piles", "Timber pile, 12 in", "Round timber pile, used for fender and guide piles.",
    pile("12 in timber pile", "round", 1.0, 10.0, -30.0, kind="fender pile", material="Timber"), "timber, fender")
lib("Piles", "Guide pile, 16 in steel pipe", "Guide pile for floating docks; head well above high water.",
    pile("16 in guide pile", "pipe", 1.333, 14.0, -40.0, kind="guide pile", material="Steel", more={"wall": 0.031}), "marina, guide")

lib("Pile caps and beams", "Pile cap beam, 4 ft x 3 ft concrete", "Cap beam 42 ft long, top at +10.5.",
    comp("beam", "Cap beam", "pile cap beam", {"path": [[0, -1, 10.5], [0, 41, 10.5]], "width": 4.0, "depth": 3.0}, material="Concrete"))
lib("Pile caps and beams", "Pile cap, 8 ft square", "Square pile cap 4 ft deep.",
    comp("block", "Pile cap", "pile cap", {"length": 8.0, "width": 8.0, "top_el": 10.0, "bottom_el": 6.0}, material="Concrete"))
lib("Decks", "Deck slab, 18 in concrete", "Rectangular deck 100 ft x 40 ft; edit the size or give an outline.",
    comp("slab", "Deck slab", "deck", {"length": 100.0, "width": 40.0, "top_el": 12.0, "thickness": 1.5}, material="Concrete"))
lib("Decks", "Timber bullrail, 12 in x 12 in", "Edge bullrail sitting on the deck.",
    comp("beam", "Bullrail", "bullrail", {"path": [[0, 0, 13], [100, 0, 13]], "width": 1.0, "depth": 1.0}, material="Timber"))

lib("Walls and bulkheads", "Steel sheet pile wall", "Straight wall 100 ft long, top +9, tip -35. Thickness is the system depth.",
    comp("wall", "Sheet pile wall", "sheet pile wall", {"path": [[0, 0], [100, 0]], "top_el": 9.0, "bottom_el": -35.0, "thickness": 1.5}, material="Steel"))
lib("Walls and bulkheads", "Concrete gravity quay wall", "Mass concrete section 100 ft long with a battered back.",
    comp("section_sweep", "Gravity quay wall", "quay wall", {"section": [[0, -30], [-20, -30], [-20, -26], [-9, 9], [0, 9]], "path": [[0, 0], [100, 0]]},
         material="Concrete"))
lib("Walls and bulkheads", "Sheet pile cell, 40 ft diameter", "Closed circular cell approximated with 16 sides.",
    comp("wall", "Sheet pile cell", "sheet pile wall",
         {"path": [[round(20 * __import__("math").cos(k * 3.14159265 / 8), 3), round(20 * __import__("math").sin(k * 3.14159265 / 8), 3)] for k in range(16)],
          "closed": "yes", "top_el": 10.0, "bottom_el": -30.0, "thickness": 1.0}, material="Steel"))

ARMOUR = [[-76, -20], [-8, 14], [8, 14], [76, -20], [64, -20], [6, 9], [-6, 9], [-64, -20]]
UNDER = [[-64, -20], [-6, 9], [6, 9], [64, -20], [54, -20], [4, 5], [-4, 5], [-54, -20]]
CORE = [[-54, -20], [-4, 5], [4, 5], [54, -20]]


def mound(path):
    return [comp("section_sweep", "Armour layer", "armour layer", {"section": ARMOUR, "path": path}, material="Armour rock"),
            comp("section_sweep", "Underlayer", "underlayer", {"section": UNDER, "path": path}, material="Underlayer rock"),
            comp("section_sweep", "Core", "core", {"section": CORE, "path": path}, material="Quarry run core")]


lib("Breakwaters and revetments", "Rubble mound breakwater section", "Armour, underlayer and core at 1V:2H, crest +14, seabed -20, 100 ft long.",
    comp("assembly", "Rubble mound", "breakwater section", children=mound([[0, 0], [100, 0]])), "armour, core")
lib("Breakwaters and revetments", "Rock revetment section", "Armour over a filter layer on a 1V:2H bank, 100 ft long.",
    comp("assembly", "Revetment", "other", children=[
        comp("section_sweep", "Armour", "armour layer", {"section": [[0, -10], [6, -10], [46, 10], [40, 10]], "path": [[0, 0], [100, 0]]}, material="Armour rock"),
        comp("section_sweep", "Filter", "filter layer", {"section": [[-3, -10], [0, -10], [40, 10], [37, 10]], "path": [[0, 0], [100, 0]]}, material="Filter rock")]))

lib("Fenders", "Cylindrical fender, 3 ft x 6 ft", "Projects toward +x; rotate to face the berth.",
    comp("fender", "Cylindrical fender", "cylindrical fender", {"length": 6.0, "height": 3.0, "projection": 3.0}))
lib("Fenders", "Arch fender, 6 ft", "Arch fender unit 6 ft long, 2 ft high, 1.5 ft projection.",
    comp("fender", "Arch fender", "arch fender", {"length": 6.0, "height": 2.0, "projection": 1.5}))
lib("Fenders", "Cone fender, 4 ft", "Cone fender 4 ft in diameter projecting 4 ft.",
    comp("fender", "Cone fender", "cone fender", {"length": 4.0, "height": 4.0, "projection": 4.0}))
lib("Mooring hardware", "Bollard, 100 t", "Single bollard on a deck.",
    comp("mooring", "Bollard", "bollard", {"height": 2.0, "diameter": 1.8, "capacity": "100 t"}, material="Cast steel"))
lib("Mooring hardware", "Cleat, 30 in", "Marina cleat.",
    comp("mooring", "Cleat", "cleat", {"height": 0.6, "diameter": 2.5, "capacity": ""}, material="Cast steel"))
lib("Mooring hardware", "Quick release hook", "Hook unit on a dolphin.",
    comp("mooring", "Quick release hook", "quick release hook", {"height": 2.5, "diameter": 4.0, "capacity": "75 t"}, material="Steel"))

lib("Floating docks", "Floating dock unit, 8 ft x 20 ft", "Concrete float with about 1.5 ft freeboard.",
    comp("block", "Float unit", "pontoon", {"length": 20.0, "width": 8.0, "top_el": 1.5, "bottom_el": -1.5}, material="Concrete float"))
lib("Floating docks", "Finger float, 4 ft x 30 ft", "Finger pier float; rotate 90 degrees to run across the walkway.",
    comp("block", "Finger float", "pontoon", {"length": 30.0, "width": 4.0, "top_el": 1.5, "bottom_el": -1.0}, material="Concrete float"))
lib("Floating docks", "Aluminium gangway, 4 ft x 45 ft", "Gangway from an abutment down to a float.",
    comp("beam", "Gangway", "gangway", {"path": [[0, 0, 9], [43, 0, 2.5]], "width": 4.0, "depth": 0.5}, material="Aluminium"))


def bent(n_x=1, dx=20.0):
    kids = [comp("beam", "Cap beam", "pile cap beam", {"path": [[0, -1, 10.5], [0, 41, 10.5]], "width": 4.0, "depth": 3.0}, material="Concrete"),
            pile("Plumb piles", "octagonal", 2.0, 8.0, -65.0, material="Prestressed concrete", positions=[[0, 5], [0, 15], [0, 25], [0, 35]]),
            pile("Batter pile, south", "octagonal", 2.0, 8.0, -65.0, kind="batter pile", material="Prestressed concrete", at=[0, 2, 0],
                 more={"batter": 0.1667, "batter_dir": 270}),
            pile("Batter pile, north", "octagonal", 2.0, 8.0, -65.0, kind="batter pile", material="Prestressed concrete", at=[0, 38, 0],
                 more={"batter": 0.1667, "batter_dir": 90})]
    d = comp("assembly", "Pile bent", "pile bent", children=kids)
    if n_x > 1:
        d["array"] = {"nx": n_x, "dx": dx, "ny": 1, "dy": 0}
    return d


def dolphin():
    kids = [comp("block", "Dolphin cap", "dolphin cap", {"length": 16.0, "width": 16.0, "top_el": 12.0, "bottom_el": 8.0}, material="Concrete"),
            pile("Plumb piles", "pipe", 2.5, 9.0, -70.0, material="Steel", more={"wall": 0.052}, positions=[[5, 5], [-5, 5], [-5, -5], [5, -5]])]
    for nm, x, y, d in (("east", 6, 0, 0), ("north", 0, 6, 90), ("west", -6, 0, 180), ("south", 0, -6, 270)):
        kids.append(pile("Batter pile, " + nm, "pipe", 2.5, 9.0, -70.0, kind="batter pile", material="Steel", at=[x, y, 0],
                         more={"wall": 0.052, "batter": 0.25, "batter_dir": d}))
    kids.append(comp("mooring", "Quick release hook", "quick release hook", {"height": 2.5, "diameter": 4.0, "capacity": "75 t"}, at=[0, 0, 12]))
    kids.append(comp("fender", "Cone fender", "cone fender", {"length": 4.0, "height": 4.0, "projection": 4.0}, at=[8, 0, 9.5]))
    return comp("assembly", "Mooring dolphin", "dolphin", children=kids)


lib("Assemblies", "Pile bent, 4 plumb and 2 batter piles", "Cap beam 42 ft long on 24 in octagonal piles at 10 ft, with a batter pile at each end.",
    bent(), "pier, wharf")
lib("Assemblies", "Mooring dolphin, 8 pipe piles", "16 ft square cap on four plumb and four battered 30 in pipe piles, with a hook and a cone fender.",
    dolphin(), "dolphin")

# ------------------------------------------------------------------------------------------ example models
MODELS = []


def model(name, stype, description, comps, datum="MLLW", source="assumed", note=EX):
    def tag(c):
        c = dict(c)
        c["source"], c["note"] = source, note
        if c.get("children"):
            c["children"] = [tag(k) for k in c["children"]]
        return c
    MODELS.append({"name": name, "project": "Examples", "structure_type": stype, "units": "ft", "datum": datum,
                   "description": description, "source_drawings": "", "components": [tag(c) for c in comps]})


model("Example: pile-supported pier", "Pier or jetty", "A 300 ft x 42 ft pier on 16 pile bents at 20 ft. Generic sizes for trying the app.", [
    bent(16, 20.0),
    comp("slab", "Deck slab", "deck", {"length": 304.0, "width": 42.0, "top_el": 12.0, "thickness": 1.5}, at=[-2, -1, 0], material="Concrete"),
    comp("beam", "Bullrail, south", "bullrail", {"path": [[-2, -0.5, 13], [302, -0.5, 13]], "width": 1.0, "depth": 1.0}, material="Timber"),
    comp("beam", "Bullrail, north", "bullrail", {"path": [[-2, 40.5, 13], [302, 40.5, 13]], "width": 1.0, "depth": 1.0}, material="Timber"),
    comp("mooring", "Bollards", "bollard", {"height": 2.0, "diameter": 1.8, "capacity": "100 t"}, at=[30, 2.5, 12], array={"nx": 7, "dx": 40, "ny": 1, "dy": 0}),
    comp("fender", "Arch fenders", "arch fender", {"length": 6.0, "height": 2.0, "projection": 1.5}, at=[10, -1, 9], rotate=-90,
         array={"nx": 15, "dx": 20, "ny": 1, "dy": 0})])
model("Example: mooring dolphin", "Mooring or breasting dolphin", "A single mooring dolphin on eight pipe piles.", [dolphin()])
model("Example: marina floating dock", "Marina or floating dock", "A 200 ft main walkway with five finger piers each side, guide piles and a gangway.", [
    comp("block", "Main walkway floats", "pontoon", {"length": 20.0, "width": 8.0, "top_el": 1.5, "bottom_el": -1.5}, at=[10, 0, 0],
         array={"nx": 10, "dx": 20, "ny": 1, "dy": 0}, material="Concrete float"),
    comp("block", "Finger floats, north", "pontoon", {"length": 30.0, "width": 4.0, "top_el": 1.5, "bottom_el": -1.0}, at=[20, 19, 0], rotate=90,
         array={"nx": 5, "dx": 40, "ny": 1, "dy": 0}, material="Concrete float"),
    comp("block", "Finger floats, south", "pontoon", {"length": 30.0, "width": 4.0, "top_el": 1.5, "bottom_el": -1.0}, at=[20, -19, 0], rotate=90,
         array={"nx": 5, "dx": 40, "ny": 1, "dy": 0}, material="Concrete float"),
    pile("Guide piles, walkway", "pipe", 1.333, 14.0, -40.0, kind="guide pile", material="Steel", more={"wall": 0.031}, at=[40, 0, 0],
         array={"nx": 5, "dx": 40, "ny": 1, "dy": 0}),
    pile("Guide piles, finger ends", "pipe", 1.333, 14.0, -40.0, kind="guide pile", material="Steel", more={"wall": 0.031}, at=[23, -35.5, 0],
         array={"nx": 5, "dx": 40, "ny": 2, "dy": 71}),
    comp("mooring", "Cleats, north fingers", "cleat", {"height": 0.6, "diameter": 1.0, "capacity": ""}, at=[21.5, 12, 1.5], array={"nx": 5, "dx": 40, "ny": 2, "dy": 14}),
    comp("mooring", "Cleats, south fingers", "cleat", {"height": 0.6, "diameter": 1.0, "capacity": ""}, at=[21.5, -26, 1.5], array={"nx": 5, "dx": 40, "ny": 2, "dy": 14}),
    comp("block", "Shore abutment", "footing", {"length": 10.0, "width": 12.0, "top_el": 9.0, "bottom_el": 2.0}, at=[-48, 0, 0], material="Concrete"),
    comp("beam", "Gangway", "gangway", {"path": [[-43, 0, 9.5], [0, 0, 2.5]], "width": 4.0, "depth": 0.5}, material="Aluminium")],
      datum="MLW")
PATH = [[0, 0], [250, 0], [400, 60]]
model("Example: rubble mound breakwater", "Breakwater", "A 410 ft breakwater with a dogleg: armour, underlayer, core and a crown wall.", mound(PATH) + [
    comp("section_sweep", "Crown wall", "crown wall", {"section": [[-8, 14], [-5, 14], [-5, 18], [-8, 18]], "path": PATH}, material="Concrete")])
model("Example: sheet pile bulkhead with tie-backs", "Bulkhead", "A 200 ft anchored sheet pile bulkhead with a cap, waler, tie rods and a deadman wall.", [
    comp("wall", "Sheet pile wall", "sheet pile wall", {"path": [[0, 0], [200, 0]], "top_el": 9.0, "bottom_el": -35.0, "thickness": 1.5}, material="Steel"),
    comp("beam", "Concrete cap", "pile cap beam", {"path": [[0, 0, 11], [200, 0, 11]], "width": 3.0, "depth": 2.5}, material="Concrete"),
    comp("beam", "Waler", "waler", {"path": [[0, 1.3, 4], [200, 1.3, 4]], "width": 1.0, "depth": 1.0, "reference": "centre"}, material="Steel"),
    comp("beam", "Tie rods", "tie rod", {"path": [[5, 0.8, 4], [5, 45, 4]], "section": "round", "width": 0.21, "reference": "centre"}, material="Steel",
         array={"nx": 20, "dx": 10, "ny": 1, "dy": 0}),
    comp("wall", "Deadman wall", "deadman wall", {"path": [[0, 45.75], [200, 45.75]], "top_el": 7.0, "bottom_el": -1.0, "thickness": 1.5}, material="Concrete")])

DD = "Dry Dock No. 5 general dredging plan, dwg P-2SD-199."
MODELS.append({"name": "Example: dry dock (Dry Dock No. 5 values)", "project": "Examples", "structure_type": "Dry dock", "units": "ft",
               "datum": "Yard datum EL 0.00", "description": "Dock chamber, walls, gravel bed, cutoff sheet piling and dredge limit. "
               "Station runs along x from the inside face of the head wall. Sill grooves, culvert thickening and galleries are not modelled.",
               "source_drawings": "P-2SD-199 (Bureau Y&D 273,080), Rev A", "components": [
    dict(comp("section_sweep", "Dock floor slab", "floor", {"section": [[-75, -55.3], [75, -55.3], [75, -37.3], [-75, -37.3]], "path": [[0, 0], [1111.33, 0]]},
              material="Concrete"), source="dimensioned", note="18 ft slab, finished floor EL -37.3. " + DD),
    dict(comp("section_sweep", "Side wall, right", "dock wall", {"section": [[75, -55.3], [92, -55.3], [92, 14], [75, 14]], "path": [[0, 0], [1111.33, 0]]},
              material="Concrete"), source="derived", note="17 ft gross thickness = 97 - 5 - 75; coping EL +14.0."),
    dict(comp("section_sweep", "Side wall, left", "dock wall", {"section": [[-92, -55.3], [-75, -55.3], [-75, 14], [-92, 14]], "path": [[0, 0], [1111.33, 0]]},
              material="Concrete"), source="derived", note="17 ft gross thickness = 97 - 5 - 75; coping EL +14.0."),
    dict(comp("section_sweep", "Head wall", "dock wall", {"section": [[-92, -55.3], [92, -55.3], [92, 14], [-92, 14]], "path": [[-14.67, 0], [0, 0]]},
              material="Concrete"), source="dimensioned", note="14 ft 8 in body, Section DD."),
    dict(comp("section_sweep", "Gravel bed", "bedding", {"section": [[-97, -57.3], [97, -57.3], [97, -55.3], [-97, -55.3]], "path": [[-19.67, 0], [1111.33, 0]]},
              material="Gravel"), source="dimensioned", note="2 ft minimum gravel fill."),
    dict(comp("wall", "Cutoff sheet piling", "cutoff wall", {"path": [[1111.58, -92], [1111.58, 92]], "top_el": -37.3, "bottom_el": -78.0, "thickness": 0.5},
              material="Steel"), source="scaled", note="Tip elevation is not annotated; scaled from Section CC."),
    dict(comp("section_sweep", "Dredge limit", "dredge cut", {"section": [[-97, -57.3], [97, -57.3], [216.5, 11], [-216.5, 11]], "path": [[-19.67, 0], [1111.33, 0]]}),
         source="dimensioned", note="Bottom EL -57.3, toe 97 ft each side, slopes 1 on 1 3/4 to EL +11. Head-end slope not modelled.")]})

def build():
    out = {"library": [], "models": []}
    for entry in LIB:
        item = scene.normalise_component(dict(entry["item"], library_item=entry["name"]), "ft")
        ifcexport.export({"units": "ft", "components": [item]}, "IFC4X3")
        out["library"].append(dict(entry, item=item))
    for m in MODELS:
        s = scene.normalise(m)
        ifcexport.export(s, "IFC2X3")
        out["models"].append(s)
    return json.loads(json.dumps(out))


if __name__ == "__main__":
    out = build()
    for s in out["models"]:
        print("%-48s %5d pieces" % (s["name"], scene.count_parts(s)))
    with open(os.path.join(ROOT, "app", "seed.json"), "w") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print("%d library items, %d example models" % (len(out["library"]), len(out["models"])))
