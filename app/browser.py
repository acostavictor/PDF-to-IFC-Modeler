"""Entry points for the browser preview, where this package runs inside the page through Pyodide.

Everything goes in and out as JSON text. Model checking, the 3D preview and IFC export work there.
Reading drawings with AI and the shared database need the server.
"""
import json

from . import service
from .ifcexport import SCHEMAS
from .scene import SceneError, catalogue


def _run(fn):
    try:
        return json.dumps(fn())
    except SceneError as err:
        return json.dumps({"error": str(err)})


def catalogue_json():
    return json.dumps(dict(catalogue(), ifc_schemas=list(SCHEMAS)))


def preview_json(scene_json):
    return _run(lambda: service.preview(json.loads(scene_json)))


def export_json(request_json):
    def go():
        req = json.loads(request_json)
        text, filename = service.export(req.get("scene"), str(req.get("schema") or "IFC2X3"))
        return {"text": text, "filename": filename}
    return _run(go)


def convert_json(request_json):
    return _run(lambda: service.convert(json.loads(request_json)))
