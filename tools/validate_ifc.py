"""Developer check: validate IFC files against the schema and confirm every element produces geometry.
Needs IfcOpenShell (pip install ifcopenshell). The web app itself does not use it."""
import sys

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.validate


def check(path):
    f = ifcopenshell.open(path)
    log = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(f, log)
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    shapes = 0
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    for el in f.by_type("IfcElement"):
        if not el.Representation:
            continue
        verts = ifcopenshell.geom.create_shape(settings, el).geometry.verts
        shapes += 1
        for i in range(0, len(verts), 3):
            for k in range(3):
                lo[k] = min(lo[k], verts[i + k])
                hi[k] = max(hi[k], verts[i + k])
    return {"schema": f.schema, "elements": len(f.by_type("IfcElement")), "shapes": shapes,
            "issues": [s["message"] for s in log.statements], "bbox_m": (lo, hi)}


if __name__ == "__main__":
    bad = 0
    for p in sys.argv[1:]:
        r = check(p)
        print("%s: %s, %d elements, %d shapes, %d issues" % (p, r["schema"], r["elements"], r["shapes"], len(r["issues"])))
        print("   bbox (m): %s .. %s" % tuple([round(c, 3) for c in b] for b in r["bbox_m"]))
        for msg in r["issues"][:12]:
            print("   -", msg[:300])
        bad += len(r["issues"])
    sys.exit(1 if bad else 0)
