import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ifc import writer
from app.templates import TEMPLATES, strut_gate, strut_gate_staad, catalogue
from app.templates.base import ParamError, coerce, resolve


class WriterTest(unittest.TestCase):
    def test_formatting(self):
        self.assertEqual(writer.fmt(None), "$")
        self.assertEqual(writer.fmt(writer.STAR), "*")
        self.assertEqual(writer.fmt(True), ".T.")
        self.assertEqual(writer.fmt(3), "3")
        self.assertEqual(writer.fmt(3.0), "3.")
        self.assertEqual(writer.fmt(0.3048), "0.3048")
        self.assertEqual(writer.fmt(1e-12), "0.")
        self.assertEqual(writer.fmt(1.5e-7), "1.5E-07")
        self.assertEqual(writer.fmt(writer.E("AREA")), ".AREA.")
        self.assertEqual(writer.fmt("it's 5\\8"), "'it''s 5\\\\8'")
        self.assertEqual(writer.fmt(u"60°"), "'60\\X2\\00B0\\X0\\'")
        self.assertEqual(writer.fmt([1.0, (2, None)]), "(1.,(2,$))")
        self.assertEqual(writer.fmt(writer.Typed("IfcLabel", "x")), "IFCLABEL('x')")

    def test_guid_is_stable_and_well_formed(self):
        g = writer.guid("seed")
        self.assertEqual(g, writer.guid("seed"))
        self.assertNotEqual(g, writer.guid("seed2"))
        self.assertEqual(len(g), 22)
        self.assertIn(g[0], "0123")

    def test_rejects_non_finite(self):
        with self.assertRaises(ValueError):
            writer.fmt(float("nan"))


class ParamTest(unittest.TestCase):
    def test_coerce(self):
        spec = {"key": "k", "type": "list"}
        self.assertEqual(coerce(spec, "1, 2;3 4"), [1.0, 2.0, 3.0, 4.0])
        table = {"key": "t", "type": "table", "columns": [{"name": "a", "type": "number"}, {"name": "b", "type": "text"}]}
        self.assertEqual(coerce(table, "274, HP340x12\n884,HP300x12\n"), [[274.0, "HP340x12"], [884.0, "HP300x12"]])
        with self.assertRaises(ParamError):
            coerce({"key": "n", "type": "number"}, "47'-9\"")
        with self.assertRaises(ParamError):
            coerce(table, "1, 2, 3")

    def test_resolve_marks_defaults(self):
        values, prov = resolve(strut_gate.PARAMS, {"height": {"value": "15000", "source": "dimensioned", "note": "S-1"},
                                                    "slope_deg": 55, "web_t": ""})
        self.assertEqual(values["height"], 15000.0)
        self.assertEqual(prov["height"]["source"], "dimensioned")
        self.assertEqual(prov["slope_deg"]["source"], "assumed")
        self.assertEqual(prov["web_t"]["source"], "example default")
        self.assertEqual(values["web_t"], 20.0)


class TemplateTest(unittest.TestCase):
    def test_every_template_builds_from_defaults(self):
        expected = {"strut_gate": 187, "caisson_gate": 35, "dry_dock": 10}
        for tid, t in TEMPLATES.items():
            text = t.build({}, {"timestamp": 0})
            self.assertTrue(text.startswith("ISO-10303-21;"))
            self.assertIn("FILE_SCHEMA(('IFC2X3'));", text)
            self.assertTrue(text.rstrip().endswith("END-ISO-10303-21;"))
            n = sum(text.count("=%s(" % c) for c in (
                "IFCBEAM", "IFCMEMBER", "IFCPLATE", "IFCWALL", "IFCSLAB", "IFCPILE", "IFCRAILING", "IFCDISCRETEACCESSORY",
                "IFCFLOWCONTROLLER", "IFCBUILDINGELEMENTPROXY", "IFCELEMENTASSEMBLY"))
            self.assertEqual(n, expected[tid], tid)

    def test_output_is_deterministic(self):
        t = TEMPLATES["dry_dock"]
        self.assertEqual(t.build({}, {"timestamp": 5}), t.build({}, {"timestamp": 5}))

    def test_changed_value_changes_the_model(self):
        t = TEMPLATES["strut_gate"]
        a = t.build({}, {"timestamp": 0})
        b = t.build({"height": 15500, "girder_x": "1500, 6000, 12000, 18000"}, {"timestamp": 0})
        self.assertNotEqual(a, b)
        self.assertEqual(b.count("=IFCBEAM("), 2 * (4 + 1 + 3 + 1))     # girders, strut beam, stringers, cross framing
        self.assertIn("15500 mm [assumed]", b)
        self.assertIn("[example default]", b)

    def test_bad_values_are_explained(self):
        cases = [("strut_gate", {"slope_deg": 95}), ("strut_gate", {"height": 9000}), ("strut_gate", {"girder_x": "1245, 99999"}),
                 ("strut_gate", {"stiffener_rows": "274, FLAT200"}), ("dry_dock", {"floor_el": 20}),
                 ("caisson_gate", {"deck_depth": 3})]
        for tid, params in cases:
            with self.assertRaises(ParamError):
                TEMPLATES[tid].build(params)

    def test_unknown_bulb_flat_size_is_approximated(self):
        b, t, c, area, cg, ix, known = strut_gate.hp_props("HP 200 x 9")
        self.assertFalse(known)
        self.assertGreater(area, 200 * 9)

    def test_staad_export(self):
        text, stats = strut_gate_staad.build({})
        self.assertTrue(text.startswith("STAAD SPACE"))
        self.assertTrue(text.rstrip().endswith("FINISH"))
        self.assertLessEqual(max(len(line) for line in text.splitlines()), 79)
        self.assertEqual(stats["supports"], 32)
        self.assertGreater(stats["plates"], 1000)

    def test_catalogue_is_json_ready(self):
        import json
        cat = catalogue()
        json.dumps(cat)
        self.assertEqual([c["id"] for c in cat], ["strut_gate", "caisson_gate", "dry_dock"])
        self.assertIn("std", cat[0]["exports"])


@unittest.skipUnless(os.environ.get("VALIDATE_IFC"), "set VALIDATE_IFC=1 with IfcOpenShell installed")
class SchemaTest(unittest.TestCase):
    def test_generated_files_pass_schema_validation(self):
        import tempfile
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
        import validate_ifc
        variants = {"strut_gate": [{}, {"height": 15500, "girder_x": "1500, 6000, 12000, 18000", "context": 0}],
                    "caisson_gate": [{}], "dry_dock": [{}, {"thick_start": 0, "thick_end": 0, "fill_run": 0}]}
        for tid, sets in variants.items():
            for params in sets:
                with tempfile.NamedTemporaryFile("w", suffix=".ifc", delete=False) as fh:
                    fh.write(TEMPLATES[tid].build(params, {"timestamp": 0, "project_name": u"Test °"}))
                result = validate_ifc.check(fh.name)
                os.unlink(fh.name)
                self.assertEqual(result["issues"], [], tid)
                self.assertGreater(result["shapes"], 5)


if __name__ == "__main__":
    unittest.main()
