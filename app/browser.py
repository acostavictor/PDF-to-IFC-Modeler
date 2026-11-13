"""Entry points for the browser preview, where this package runs inside the page through Pyodide.

Everything goes in and out as JSON text. Only model building is available there; reading drawings with
AI needs the server, because an API key cannot be kept secret in a web page.
"""
import json

from . import build
from .templates import catalogue


def templates_json():
    return json.dumps({"templates": catalogue()})


def generate_json(request_json):
    req = json.loads(request_json)
    try:
        text, filename, ctype = build.generate(req.get("template"), req.get("format"), req.get("params"), req.get("meta"))
    except build.BuildError as err:
        return json.dumps({"error": str(err)})
    return json.dumps({"text": text, "filename": filename, "content_type": ctype})
