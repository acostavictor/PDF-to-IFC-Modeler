"""Template registry. Each template turns a reviewed parameter set into an IFC2x3 model."""
from . import strut_gate, caisson_gate, dry_dock, strut_gate_staad

TEMPLATES = {t.ID: t for t in (strut_gate, caisson_gate, dry_dock)}
EXTRA_EXPORTS = {"strut_gate": {"std": ("STAAD.Pro input file", strut_gate_staad.build)}}


def describe(t):
    return {"id": t.ID, "title": t.TITLE, "summary": t.SUMMARY, "unit": t.UNIT, "look_for": t.LOOK_FOR,
            "params": t.PARAMS, "exports": ["ifc"] + sorted(EXTRA_EXPORTS.get(t.ID, {}))}


def catalogue():
    return [describe(TEMPLATES[k]) for k in ("strut_gate", "caisson_gate", "dry_dock")]
