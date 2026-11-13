"""The model format, its geometry, the preview mesh and the IFC export."""
import json
import os
import re
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import geometry, ifcexport, mesh, scene, service  # noqa: E402
from app.scene import SceneError  # noqa: E402

with open(os.path.join(ROOT, "app", "seed.json")) as fh:
    SEED = json.load(fh)


def one(type_id, **over):
    comp = {"type": type_id, "name": over.pop("name", "Test " + type_id), "params": over.pop("params", {})}
    comp.update(over)
    if type_id == "assembly":
        comp.setdefault("children", [{"type": "pile", "name": "P", "params": {}}])
    return comp


def model(*components, **head):
    return dict({"name": "Test", "units": head.pop("units", "ft"), "components": list(components)}, **head)


def volume(positions):
    """Signed volume of a closed triangle mesh (flat coordinate list)."""
    total = 0.0
    for i in range(0, len(positions), 9):
        a, b, c = positions[i:i + 3], positions[i + 3:i + 6], positions[i + 6:i + 9]
        total += (a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0]) + a[2] * (b[0] * c[1] - b[1] * c[0])) / 6.0
    return total


class SceneTest(unittest.TestCase):
    def test_every_type_builds_from_its_defaults_in_every_unit(self):
        for units in scene.UNITS:
            for type_id in scene.TYPES:
                sc = scene.normalise(model(one(type_id), units=units))
                out = mesh.build(sc)
                self.assertGreaterEqual(out["parts"], 1, type_id)
                self.assertTrue(all(len(m["positions"]) % 9 == 0 and m["positions"] for m in out["meshes"]), type_id)

    def test_text_from_the_form_is_accepted(self):
        sc = scene.normalise(model(
            one("pile", at=["1", "2", "0"], rotate="15", array={"nx": "3", "dx": "10", "ny": "2", "dy": "8"}, positions="",
                params={"size": "2", "top_el": "10", "tip_el": "-40"}),
            one("beam", params={"path": "0, 0, 5\n20 0 5\n", "width": "2", "depth": "3"}),
            one("pile", positions="0, 0\n5, 5\n")))
        a, b, c = sc["components"]
        self.assertEqual((a["at"], a["rotate"], a["array"]["nx"], a["params"]["tip_el"]), ([1.0, 2.0, 0.0], 15.0, 3, -40.0))
        self.assertEqual(b["params"]["path"], [[0.0, 0.0, 5.0], [20.0, 0.0, 5.0]])
        self.assertEqual(len(c["positions"]), 2)
        self.assertEqual(scene.count_parts(sc), 6 + 1 + 2)
        self.assertEqual(len({k["id"] for k in sc["components"]}), 3)
        self.assertEqual(scene.normalise(sc), sc, "normalising twice must change nothing")

    def test_problems_name_the_component_in_plain_words(self):
        cases = [
            (model(one("pile", name="North pile", params={"size": "wide"})), "'North pile' (pile), diameter or width: 'wide' is not a number"),
            (model(one("pile", name="P", params={"size": -1})), "'P' (pile)"),
            (model(one("pile", params={"top_el": 0, "tip_el": 5})), "tip"),
            (model(one("pile", params={"shape": "star"})), "is not one of round, pipe"),
            (model(one("beam", params={"path": [[0, 0, 0]]})), "the path needs at least two points"),
            (model(one("beam", params={"path": "1, 2\n3, 4"})), "row 1: 3 values are needed (x, y, z)"),
            (model({"type": "widget", "name": "W"}), "'widget' is not a component type"),
            (model(one("assembly", children=[])), "needs at least one component inside it"),
            (model(one("pile", array={"nx": -2, "dx": 1, "ny": 1, "dy": 1})), "repeat counts"),
            (model(one("pile", array={"nx": 500, "dx": 1, "ny": 500, "dy": 1})), "repeat counts"),
            (model(one("pile", at=[1, "east", 0])), "is not a number"),
            (model(one("pile"), units="yards"), "Units must be ft, m or mm."),
            ("nonsense", "The model must be a JSON object."),
            ({"units": "ft", "components": "none"}, "The components must be a list."),
        ]
        for raw, text in cases:
            with self.assertRaises(SceneError) as caught:
                mesh.build(scene.normalise(raw))
            self.assertIn(text, str(caught.exception))
        deep = one("pile")
        for _ in range(scene.MAX_DEPTH + 1):
            deep = one("assembly", children=[deep])
        with self.assertRaises(SceneError):
            scene.normalise(model(deep))
        big = one("assembly", array={"nx": 150, "dx": 1, "ny": 1, "dy": 0}, children=[one("pile", array={"nx": 150, "dx": 1, "ny": 1, "dy": 0})])
        with self.assertRaises(SceneError) as caught:
            mesh.build(scene.normalise(model(big)))
        self.assertIn("pieces", str(caught.exception))

    def test_unit_conversion_keeps_the_real_size(self):
        for seed in SEED["models"]:
            ft = mesh.build(scene.normalise(seed))
            for units, per_ft in (("m", 0.3048), ("mm", 304.8)):
                conv = scene.convert_scene(seed, units)
                self.assertEqual(conv["units"], units)
                out = mesh.build(conv)
                self.assertEqual(out["parts"], ft["parts"])
                for k in range(3):
                    for end in (0, 1):
                        self.assertAlmostEqual(out["bbox"][end][k] / per_ft, ft["bbox"][end][k], places=2, msg=seed["name"])
                back = mesh.build(scene.convert_scene(conv, "ft"))
                self.assertAlmostEqual(back["bbox"][1][0], ft["bbox"][1][0], places=3)
        # angles, counts and ratios are not lengths
        comp = scene.normalise_component(one("pile", rotate=30, array={"nx": 3, "dx": 10, "ny": 1, "dy": 0}, params={"batter": 0.25, "size": 2}), "ft")
        m = scene.convert_component(comp, "ft", "m")
        self.assertEqual((m["rotate"], m["array"]["nx"], m["params"]["batter"]), (30.0, 3, 0.25))
        self.assertAlmostEqual(m["params"]["size"], 0.6096)
        self.assertAlmostEqual(m["array"]["dx"], 3.048)

    def test_catalogue_describes_every_input(self):
        cat = scene.catalogue()
        self.assertEqual([t["id"] for t in cat["types"]], list(scene.TYPES))
        for t in cat["types"]:
            self.assertTrue(t["title"] and t["summary"])
            for spec in t["params"]:
                self.assertIn(spec["type"], ("number", "choice", "table", "text"))
                self.assertTrue(spec["label"])
        json.dumps(cat)


class GeometryTest(unittest.TestCase):
    def test_sizes_come_out_as_entered(self):
        out = mesh.build(scene.normalise(model(one("slab", at=[10, 20, 0], params={"length": 40, "width": 12, "top_el": 9, "thickness": 1.5}))))
        self.assertEqual(out["bbox"], [[10.0, 20.0, 7.5], [50.0, 32.0, 9.0]])
        self.assertAlmostEqual(volume(out["meshes"][0]["positions"]), 40 * 12 * 1.5, places=3)
        out = mesh.build(scene.normalise(model(one("pile", params={"shape": "square", "size": 2, "top_el": 10, "tip_el": -30}))))
        self.assertEqual(out["bbox"], [[-1.0, -1.0, -30.0], [1.0, 1.0, 10.0]])
        self.assertAlmostEqual(volume(out["meshes"][0]["positions"]), 160.0, places=3)

    def test_a_battered_pile_leans_the_stated_amount(self):
        out = mesh.build(scene.normalise(model(one("pile", params={"shape": "square", "size": 1, "top_el": 0, "tip_el": -40, "batter": 0.25, "batter_dir": 0}))))
        lo, hi = out["bbox"]
        self.assertAlmostEqual(lo[2], -40.0, delta=0.15)                           # square-cut tip of a leaning pile
        self.assertAlmostEqual(hi[0] - lo[0], 10.0 + 1.0, delta=0.3)           # 1 horizontal in 4 vertical over 40, plus the width
        self.assertAlmostEqual(hi[1] - lo[1], 1.0, places=3)

    def test_repeats_step_in_the_parent_axes_and_turn_each_copy_in_place(self):
        comp = one("block", rotate=90, array={"nx": 3, "dx": 10, "ny": 1, "dy": 0},
                   params={"plan": "rectangle", "length": 4, "width": 2, "top_el": 1, "bottom_el": 0})
        out = mesh.build(scene.normalise(model(comp)))
        lo, hi = out["bbox"]
        self.assertEqual(out["parts"], 3)
        self.assertAlmostEqual(hi[0] - lo[0], 20 + 2, places=3)                 # copies still march along x
        self.assertAlmostEqual(hi[1] - lo[1], 4, places=3)                      # each one turned on the spot
        inside = one("assembly", at=[100, 0, 0], rotate=90, children=[dict(comp, rotate=0)])
        lo, hi = mesh.build(scene.normalise(model(inside)))["bbox"]
        self.assertAlmostEqual(hi[1] - lo[1], 20 + 4, places=3)                 # the assembly's x now points along y
        self.assertAlmostEqual(hi[0] - lo[0], 2, places=3)

    def test_sweeps_are_closed_solids_of_the_right_volume(self):
        tri = [[-5, 0], [5, 0], [0, 4]]                                         # 20 square units
        straight = one("section_sweep", params={"section": tri, "path": [[0, 0], [30, 0]]})
        self.assertAlmostEqual(volume(mesh.build(scene.normalise(model(straight)))["meshes"][0]["positions"]), 600.0, places=3)
        bent = one("section_sweep", params={"section": tri, "path": [[0, 0], [30, 0], [30, 30]]})
        out = mesh.build(scene.normalise(model(bent)))
        self.assertAlmostEqual(volume(out["meshes"][0]["positions"]), 1200.0, places=2)     # outward-facing, so positive
        ring = one("wall", params={"path": [[0, 0], [10, 0], [10, 10], [0, 10]], "closed": "yes", "top_el": 3, "bottom_el": 0, "thickness": 1, "align": "centre"})
        out = mesh.build(scene.normalise(model(ring)))
        self.assertAlmostEqual(volume(out["meshes"][0]["positions"]), 40 * 1 * 3, places=2)

    def test_triangulation_handles_concave_outlines(self):
        ell = [(0, 0), (4, 0), (4, 1), (1, 1), (1, 3), (0, 3)]
        for poly in (ell, ell[::-1]):
            tris = mesh.triangulate(poly)
            self.assertEqual(len(tris), len(poly) - 2)
            area = 0.0
            for a, b, c in ((poly[i], poly[j], poly[k]) for i, j, k in tris):
                twice = (b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])
                self.assertGreater(twice, 0)                                    # always anticlockwise
                area += twice / 2.0
            self.assertAlmostEqual(area, 6.0)

    def test_preview_reports_sources_and_selection_ids(self):
        out = service.preview(model(one("pile", id="a", source="dimensioned"), one("assembly", id="g", children=[one("pile", source="scaled"), one("slab")])))
        self.assertEqual(out["sources"], {"dimensioned": 1, "scaled": 1, "assumed": 1})
        self.assertEqual({m["id"] for m in out["meshes"]}, {"a", "g"})
        self.assertEqual(out["scene"]["schema"], scene.SCHEMA)
        json.dumps(out)


def entities(text):
    return re.findall(r"^#\d+=\s*(IFC[A-Z0-9]+)\(", text, re.M)


class IfcTest(unittest.TestCase):
    def check_text(self, text, schema):
        self.assertTrue(text.startswith("ISO-10303-21;"))
        self.assertTrue(text.rstrip().endswith("END-ISO-10303-21;"))
        self.assertIn("FILE_SCHEMA(('%s'))" % ("IFC2X3" if schema == "IFC2X3" else "IFC4X3_ADD2"), text)
        defined = set(re.findall(r"^#(\d+)=", text, re.M))
        used = set(re.findall(r"[(,=]#(\d+)", text))
        self.assertFalse(used - defined, "references to missing entities")
        guids = re.findall(r"^#\d+=\s*IFC[A-Z0-9]+\('([0-9A-Za-z_$]{22})'", text, re.M)
        self.assertEqual(len(guids), len(set(guids)), "GlobalIds must be unique")

    def test_examples_and_library_export_in_both_schemas(self):
        files = []
        for schema in ifcexport.SCHEMAS:
            for sc in SEED["models"]:
                text = ifcexport.export(sc, schema)
                self.check_text(text, schema)
                names = entities(text)
                solid = sum(names.count(n) for n in ("IFCEXTRUDEDAREASOLID", "IFCFACETEDBREP"))
                self.assertGreaterEqual(solid, 1)
                self.assertEqual(names.count("IFCMARINEFACILITY"), 1 if schema == "IFC4X3" else 0)
                self.assertEqual(names.count("IFCBUILDINGSTOREY"), 0 if schema == "IFC4X3" else 1)
                files.append((sc["name"], schema, text, scene.count_parts(sc), mesh.build(scene.normalise(sc))["bbox"], sc["units"]))
            for entry in SEED["library"]:
                sc = {"name": entry["name"], "units": entry["units"], "components": [entry["item"]]}
                text = ifcexport.export(sc, schema)
                self.check_text(text, schema)
                files.append((entry["name"], schema, text, scene.count_parts(scene.normalise(sc)), mesh.build(scene.normalise(sc))["bbox"], entry["units"]))
        if not os.environ.get("VALIDATE_IFC"):
            return
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        from validate_ifc import check
        with tempfile.TemporaryDirectory() as tmp:
            for name, schema, text, pieces, bbox, units in files:
                path = os.path.join(tmp, "m.ifc")
                with open(path, "w") as fh:
                    fh.write(text)
                res = check(path)
                self.assertEqual(res["issues"], [], "%s (%s)" % (name, schema))
                self.assertEqual(res["shapes"], pieces, "%s (%s): every piece must produce geometry" % (name, schema))
                to_m = scene.UNITS[units][1] / 1000.0 if units != "ft" else 0.3048
                for end in (0, 1):
                    for k in range(3):                                          # the IFC and the on-screen preview are the same shape
                        self.assertAlmostEqual(res["bbox_m"][end][k], bbox[end][k] * to_m, delta=0.02, msg="%s (%s)" % (name, schema))

    def test_same_model_and_time_give_the_same_file(self):
        sc = SEED["models"][0]
        self.assertEqual(ifcexport.export(sc, "IFC2X3", timestamp=1700000000), ifcexport.export(sc, "IFC2X3", timestamp=1700000000))

    def test_marine_classes_are_used_where_the_schema_has_them(self):
        def cls(type_id, kind, schema):
            return ifcexport.ifc_class(scene.normalise_component(one(type_id, kind=kind), "ft"), schema)[:2]
        self.assertEqual(cls("pile", "batter pile", "IFC2X3")[0], "IfcPile")
        self.assertEqual(cls("mooring", "bollard", "IFC4X3"), ("IfcMooringDevice", "BOLLARD"))
        self.assertEqual(cls("mooring", "bollard", "IFC2X3"), ("IfcDiscreteAccessory", None))
        self.assertEqual(cls("fender", "cone fender", "IFC4X3"), ("IfcImpactProtectionDevice", "FENDER"))
        self.assertEqual(cls("section_sweep", "armour layer", "IFC4X3"), ("IfcCourse", "ARMOUR"))
        self.assertEqual(cls("section_sweep", "armour layer", "IFC2X3")[0], "IfcBuildingElementProxy")
        self.assertEqual(cls("section_sweep", "dredge cut", "IFC4X3")[0], "IfcBuildingElementProxy")
        self.assertEqual(cls("beam", "pile cap beam", "IFC4X3"), ("IfcBeam", "PIERCAP"))
        self.assertEqual(cls("block", "pile cap", "IFC2X3"), ("IfcFooting", "PILE_CAP"))
        self.assertEqual(cls("assembly", "pile bent", "IFC4X3")[0], "IfcElementAssembly")

    def test_properties_record_where_each_size_came_from(self):
        text = ifcexport.export(model(one("pile", name="Pile A", source="scaled", note="Sheet S-2, no dimension"), datum="MLLW"), "IFC2X3")
        self.assertIn("P2I_Component", text)
        self.assertIn("'scaled'", text)
        self.assertIn("Sheet S-2, no dimension", text)
        self.assertIn("MLLW", text)
        with self.assertRaises(SceneError):
            ifcexport.export(model(one("pile")), "IFC5")
        with self.assertRaises(SceneError):
            ifcexport.export(model(), "IFC2X3")                                 # nothing to export

    def test_text_is_escaped(self):
        text = ifcexport.export(model(one("pile", name="Pile 'A' \\ 12×12 café")), "IFC2X3")
        self.check_text(text, "IFC2X3")
        self.assertIn("Pile ''A''", text)
        text.encode("ascii")


class SeedTest(unittest.TestCase):
    def test_seed_file_matches_its_generator(self):
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import make_seed
        self.assertEqual(make_seed.build(), SEED, "run: python tools/make_seed.py")

    def test_seed_is_already_tidy(self):
        for sc in SEED["models"]:
            self.assertEqual(scene.normalise(sc), sc, sc["name"])
            self.assertTrue(sc["name"].startswith("Example: "))
        cats = set()
        for entry in SEED["library"]:
            self.assertEqual(scene.normalise_component(entry["item"], entry["units"]), entry["item"], entry["name"])
            self.assertEqual(entry["item"]["source"], "library")
            self.assertIn(entry["category"], scene.LIBRARY_CATEGORIES)
            cats.add(entry["category"])
        self.assertGreaterEqual(len(cats), 8)


if __name__ == "__main__":
    unittest.main()
