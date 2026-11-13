"""Operations shared by the server and the browser preview: check, preview, export and convert a model."""
import re

from . import ifcexport, mesh
from . import scene as scene_mod
from .scene import SceneError


def slug(text, fallback):
    s = re.sub(r"[^A-Za-z0-9]+", "_", str(text or "")).strip("_")[:60]
    return s or fallback


def preview(raw):
    """Validate a model and return its preview meshes with the tidied model."""
    sc = scene_mod.normalise(raw)
    out = mesh.build(sc)
    out["scene"] = sc
    counts = {}

    def tally(comp):
        if comp["type"] == "assembly":
            for kid in comp["children"]:
                tally(kid)
        else:
            counts[comp["source"]] = counts.get(comp["source"], 0) + 1
    for comp in sc["components"]:
        tally(comp)
    out["sources"] = counts
    return out


def export(raw, schema):
    text = ifcexport.export(raw, schema)
    name = raw.get("name") if isinstance(raw, dict) else ""
    return text, slug(name, "model") + ".ifc"


def convert(data):
    """Convert a whole model ({scene, units}) or one component ({component, from, to}) between units."""
    if not isinstance(data, dict):
        raise SceneError("Nothing to convert.")
    if "component" in data:
        src, dst = str(data.get("from") or ""), str(data.get("to") or "")
        if src not in scene_mod.UNITS or dst not in scene_mod.UNITS:
            raise SceneError("Units must be ft, m or mm.")
        comp = scene_mod.normalise_component(data["component"], src)
        return {"component": scene_mod.convert_component(comp, src, dst)}
    return {"scene": scene_mod.convert_scene(data.get("scene"), str(data.get("units") or ""))}
