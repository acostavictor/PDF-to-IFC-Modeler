import io
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import auth, config, extract, server
from app.templates import TEMPLATES

KEYS = ("ANTHROPIC_API_KEY", "APP_PASSWORD", "PDF2IFC_CONFIG", "ANTHROPIC_URL", "MAX_IMAGES")


def request(method, path, body=None, cookie=None):
    raw = json.dumps(body).encode("utf-8") if body is not None else b""
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw),
           "wsgi.errors": io.StringIO(), "wsgi.url_scheme": "https"}
    if cookie:
        env["HTTP_COOKIE"] = cookie
    seen = {}

    def start(status, headers):
        seen["status"] = int(status.split()[0])
        seen["headers"] = dict(headers)

    body = b"".join(server.application(env, start))
    return seen["status"], seen["headers"], body


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.saved = {k: os.environ.pop(k, None) for k in KEYS}
        os.environ["PDF2IFC_CONFIG"] = os.path.join(ROOT, "tests", "no-such-config.json")

    def tearDown(self):
        for k, v in self.saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v

    def login(self):
        status, headers, _ = request("POST", "/api/login", {"password": "pw"})
        self.assertEqual(status, 200)
        return headers["Set-Cookie"].split(";")[0]

    def test_open_mode_serves_pages_and_builds_but_will_not_call_the_api(self):
        status, headers, body = request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"PDF to IFC Modeler", body)
        self.assertEqual(request("GET", "/static/app.js")[0], 200)
        self.assertEqual(request("GET", "/static/vendor/pdfjs/pdf.min.mjs")[1]["Content-Type"], "text/javascript; charset=utf-8")
        for bad in ("/static/../app/server.py", "/static/.hidden", "/app/server.py", "/config.local.json"):
            self.assertEqual(request("GET", bad)[0], 404, bad)
        health = json.loads(request("GET", "/api/health")[2])
        self.assertFalse(health["ai_ready"])
        self.assertEqual(len(json.loads(request("GET", "/api/templates")[2])["templates"]), 3)
        status, headers, body = request("POST", "/api/generate", {"template": "dry_dock", "params": {}, "meta": {"project_name": "Dock 5"}})
        self.assertEqual(status, 200)
        self.assertIn("Dock_5.ifc", headers["Content-Disposition"])
        self.assertTrue(body.startswith(b"ISO-10303-21;"))
        self.assertEqual(request("POST", "/api/extract", {"template": "dry_dock", "images": []})[0], 403)

    def test_errors_are_readable(self):
        status, _, body = request("POST", "/api/generate", {"template": "strut_gate", "params": {"height": {"value": "tall", "source": "assumed"}}})
        self.assertEqual(status, 400)
        self.assertIn("not a number", json.loads(body)["error"])
        self.assertNotIn("example values", json.loads(body)["error"])
        status, _, body = request("POST", "/api/generate", {"template": "strut_gate", "params": {"height": 9000}})
        self.assertIn("example values", json.loads(body)["error"])
        self.assertEqual(request("POST", "/api/generate", {"template": "nope"})[0], 400)
        self.assertEqual(request("POST", "/api/generate", {"template": "dry_dock", "format": "exe"})[0], 400)
        self.assertEqual(request("GET", "/api/generate")[0], 405)
        self.assertEqual(request("GET", "/api/nothing")[0], 404)

    def test_password_gate(self):
        os.environ["APP_PASSWORD"] = "pw"
        self.assertEqual(request("GET", "/api/templates")[0], 401)
        self.assertEqual(request("POST", "/api/generate", {"template": "dry_dock"})[0], 401)
        self.assertEqual(request("GET", "/api/health")[0], 200)
        cookie = self.login()
        self.assertIn("HttpOnly", request("POST", "/api/login", {"password": "pw"})[1]["Set-Cookie"])
        self.assertEqual(request("GET", "/api/templates", cookie=cookie)[0], 200)
        self.assertEqual(request("GET", "/api/templates", cookie=cookie[:-2] + "00")[0], 401)
        status, headers, body = request("POST", "/api/generate", {"template": "strut_gate", "format": "std"}, cookie=cookie)
        self.assertEqual(status, 200)
        self.assertTrue(body.startswith(b"STAAD SPACE"))

    def test_tokens_expire(self):
        cfg = {"APP_PASSWORD": "pw", "ANTHROPIC_API_KEY": "k"}
        token = auth.new_token(cfg, now=1000)
        self.assertTrue(auth.token_ok(cfg, token, now=1000 + auth.LIFETIME - 1))
        self.assertFalse(auth.token_ok(cfg, token, now=1000 + auth.LIFETIME + 1))
        self.assertFalse(auth.token_ok({"APP_PASSWORD": "other", "ANTHROPIC_API_KEY": "k"}, token, now=1000))
        self.assertFalse(auth.password_ok({"APP_PASSWORD": ""}, ""))


class FakeResponse(object):
    def __init__(self, data):
        self.data = data

    def read(self):
        return json.dumps(self.data).encode("utf-8")


class ExtractTest(unittest.TestCase):
    cfg = dict(config.DEFAULTS, ANTHROPIC_API_KEY="k")
    image = {"label": "Page 1", "media_type": "image/jpeg", "data": "QUJD"}

    def test_request_shape_and_parsing(self):
        t = TEMPLATES["strut_gate"]
        sent = {}

        def opener(req, timeout=None):
            sent["headers"] = {k.lower(): v for k, v in req.header_items()}
            sent["body"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse({"model": "m", "stop_reason": "tool_use", "usage": {"input_tokens": 10, "output_tokens": 5},
                                 "content": [{"type": "tool_use", "name": extract.TOOL, "input": {
                                     "height": {"value": 14570, "source": "dimensioned", "sheet": "p2 Section 1", "note": "47'-9 5/8\""},
                                     "knee_lo": {"value": 12100, "source": "scaled"},
                                     "slope_deg": {"value": None, "source": "not_found"},
                                     "girder_x": {"value": [1245, 3988], "source": "weird"},
                                     "general_notes": "Sheets 2 and 6 disagree on the trench width."}}]})

        out = extract.extract(self.cfg, t, [self.image], "note", opener)
        self.assertEqual(sent["headers"]["x-api-key"], "k")
        self.assertEqual(sent["headers"]["anthropic-version"], self.cfg["ANTHROPIC_VERSION"])
        body = sent["body"]
        self.assertEqual(body["tool_choice"], {"type": "auto"})
        self.assertEqual(body["tools"][0]["name"], extract.TOOL)
        self.assertEqual(set(body["tools"][0]["input_schema"]["properties"]) - {"general_notes"}, {p["key"] for p in t.PARAMS})
        kinds = [b["type"] for b in body["messages"][0]["content"]]
        self.assertEqual(kinds, ["text", "image", "text"])
        self.assertEqual(out["params"]["height"], {"value": 14570, "source": "dimensioned", "note": "p2 Section 1 47'-9 5/8\""})
        self.assertEqual(out["params"]["girder_x"]["source"], "scaled")
        self.assertNotIn("slope_deg", out["params"])
        self.assertEqual(out["found"], 3)
        self.assertIn("trench", out["general_notes"])
        TEMPLATES["strut_gate"].build(dict(out["params"], girder_x=None))

    def test_falls_back_to_json_in_text(self):
        resp = {"content": [{"type": "text", "text": 'Here you go: {"length": {"value": 1102.33, "source": "dimensioned"}, "general_notes": "ok {x}"}'}]}
        params, notes = extract.parse_response(TEMPLATES["dry_dock"], resp)
        self.assertEqual(params["length"]["value"], 1102.33)

    def test_failures_are_reported(self):
        t = TEMPLATES["dry_dock"]
        with self.assertRaises(extract.ExtractError):
            extract.parse_response(t, {"stop_reason": "max_tokens", "content": []})
        with self.assertRaises(extract.ExtractError):
            extract.parse_response(t, {"content": [{"type": "text", "text": "I cannot read these."}]})
        with self.assertRaises(extract.ExtractError):
            extract.check_images(self.cfg, [self.image] * 61)
        with self.assertRaises(extract.ExtractError):
            extract.check_images(self.cfg, [{"media_type": "image/gif", "data": "x"}])
        with self.assertRaises(extract.ExtractError):
            extract.call_api(dict(self.cfg, ANTHROPIC_API_KEY=""), {})


class CgiTest(unittest.TestCase):
    def test_runs_as_plain_cgi(self):
        env = dict(os.environ, REQUEST_METHOD="GET", PATH_INFO="/api/health", SERVER_NAME="x", SERVER_PORT="80",
                   SCRIPT_NAME="/index.cgi", SERVER_PROTOCOL="HTTP/1.1", PDF2IFC_CONFIG="/nonexistent")
        for k in ("ANTHROPIC_API_KEY", "APP_PASSWORD"):
            env.pop(k, None)
        out = subprocess.check_output([sys.executable, os.path.join(ROOT, "index.cgi")], env=env)
        head, _, body = out.partition(b"\r\n\r\n")
        self.assertIn(b"200 OK", head)
        self.assertTrue(json.loads(body.decode("utf-8"))["ok"])


if __name__ == "__main__":
    unittest.main()
