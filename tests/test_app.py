"""The database, the AI composer and the web server."""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.error import HTTPError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import ai, auth, config, db, scene, server  # noqa: E402
from app.scene import SceneError  # noqa: E402

KEYS = ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "AI_PROVIDER", "GEMINI_MODEL", "GEMINI_URL", "APP_PASSWORD", "PDF2IFC_CONFIG",
        "ANTHROPIC_URL", "MAX_IMAGES", "DB_PATH", "MAX_BODY_MB", "SECRET_KEY")
PIER = {"name": "Test pier", "project": "Harbour job", "structure_type": "Pier or jetty", "units": "ft", "components": [
    {"type": "pile", "name": "Piles", "array": {"nx": 4, "dx": 10, "ny": 2, "dy": 8}, "params": {}},
    {"type": "slab", "name": "Deck", "params": {}}]}


class Env(unittest.TestCase):
    """Each test gets a clean environment and its own database file."""
    def setUp(self):
        self.saved = {k: os.environ.pop(k, None) for k in KEYS}
        self.tmp = tempfile.mkdtemp()
        os.environ["PDF2IFC_CONFIG"] = os.path.join(self.tmp, "no-such-config.json")
        os.environ["DB_PATH"] = os.path.join(self.tmp, "data", "test.sqlite3")

    def tearDown(self):
        for k, v in self.saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)


class StoreTest(Env):
    def test_first_use_creates_and_seeds_the_database_once(self):
        store = db.Store(os.environ["DB_PATH"])
        first = store.counts()
        self.assertEqual(first, {"models": 6, "library": 26})
        self.assertEqual(db.Store(os.environ["DB_PATH"]).counts(), first)
        self.assertEqual(db.Store(os.path.join(self.tmp, "empty.sqlite3"), seed=False).counts(), {"models": 0, "library": 0})
        store.delete_model(store.list_models("dolphin")[0]["id"])             # a deleted example stays deleted
        self.assertEqual(db.Store(os.environ["DB_PATH"]).counts()["models"], 5)

    def test_models_are_saved_found_updated_and_deleted(self):
        store = db.Store(os.environ["DB_PATH"])
        new_id = store.save_model(PIER)
        row = store.list_models("harbour")[0]
        self.assertEqual((row["id"], row["name"], row["pieces"], row["is_example"]), (new_id, "Test pier", 9, 0))
        self.assertEqual(store.list_models("")[0]["id"], new_id, "your own models are listed before the examples")
        got = store.get_model(new_id)
        self.assertEqual(got["scene"], scene.normalise(PIER))
        self.assertEqual(store.save_model(dict(PIER, name="Renamed pier"), new_id), new_id)
        self.assertEqual(store.get_model(new_id)["scene"]["name"], "Renamed pier")
        self.assertEqual(store.list_models("TEST PIER"), [])
        with self.assertRaises(SceneError):
            store.save_model(dict(PIER, name=" "))
        with self.assertRaises(SceneError):
            store.save_model(dict(PIER, components=[{"type": "pile", "name": "Bad", "params": {"size": 0}}]))
        store.delete_model(new_id)
        for call in (lambda: store.get_model(new_id), lambda: store.delete_model(new_id), lambda: store.save_model(PIER, new_id)):
            with self.assertRaises(db.NotFound):
                call()

    def test_library_items_are_reusable_components(self):
        store = db.Store(os.environ["DB_PATH"])
        bent = {"type": "assembly", "name": "Bent", "at": [50, 0, 0], "children": [{"type": "pile", "name": "P", "source": "dimensioned", "params": {}}]}
        new_id = store.save_library({"name": "Three pile bent", "category": "Assemblies", "description": "From Pier 4", "tags": "pier4", "units": "m", "item": bent})
        got = store.get_library(new_id)
        self.assertEqual((got["type"], got["units"], got["is_seed"]), ("assembly", "m", 0))
        self.assertEqual((got["item"]["source"], got["item"]["library_item"]), ("library", "Three pile bent"))
        self.assertEqual(got["item"]["children"][0]["source"], "dimensioned", "the parts keep their own record of where sizes came from")
        self.assertEqual([r["name"] for r in store.list_library("pier4")], ["Three pile bent"])
        odd = store.save_library({"name": "Odd one", "category": "Nonsense", "item": bent})
        self.assertEqual((store.get_library(odd)["category"], store.get_library(odd)["units"]), ("Other", "ft"))
        for bad in ({"name": "", "item": bent}, {"name": "Y", "units": "yd", "item": bent}, {"name": "Z", "item": {"type": "nope"}}):
            with self.assertRaises(SceneError):
                store.save_library(bad)
        store.delete_library(new_id)
        with self.assertRaises(db.NotFound):
            store.get_library(new_id)
        cats = [r["category"] for r in store.list_library("")]
        self.assertEqual(cats, sorted(cats))


class FakeResponse(object):
    def __init__(self, data):
        self.data = data

    def read(self):
        return json.dumps(self.data).encode("utf-8")


def tool_reply(payload, stop="tool_use"):
    return {"model": "m", "stop_reason": stop, "usage": {"input_tokens": 10, "output_tokens": 5},
            "content": [{"type": "text", "text": "Here it is."}, {"type": "tool_use", "id": "t", "name": ai.TOOL, "input": payload}]}


def openai_reply(payload=None, finish="tool_calls", content=None):
    calls = []
    if payload is not None:
        calls = [{"id": "c", "type": "function", "function": {"name": ai.TOOL, "arguments": json.dumps(payload)}}]
    return {"model": "gemini-2.5-flash", "usage": {"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28},
            "choices": [{"finish_reason": finish, "message": {"role": "assistant", "content": content, "tool_calls": calls}}]}


class AiTest(Env):
    def cfg(self, **over):
        os.environ["ANTHROPIC_API_KEY"] = "sk-test"
        cfg = config.load()
        cfg.update(over)
        return cfg

    def gemini_cfg(self, **over):
        cfg = self.cfg(AI_PROVIDER="gemini", GEMINI_API_KEY="gem-test", GEMINI_MODEL="gemini-2.5-flash")
        cfg.update(over)
        return cfg

    def test_request_shape(self):
        seen = {}

        def opener(req, timeout):
            seen["req"], seen["timeout"] = req, timeout
            return FakeResponse(tool_reply({"name": "Pier", "units": "m", "components": [{"type": "pile", "name": "P", "source": "dimensioned", "params": {}}]}))

        images = [{"label": "Page 1: whole sheet overview", "media_type": "image/jpeg", "data": "QUJD"}]
        out = ai.compose(self.cfg(), images, "Ignore sheet 3.", "m", opener)
        body = json.loads(seen["req"].data.decode("utf-8"))
        headers = {k.lower(): v for k, v in seen["req"].header_items()}
        self.assertEqual((headers["x-api-key"], headers["anthropic-version"]), ("sk-test", "2026-10-21"))
        self.assertEqual(body["model"], "claude-opus-5-5")
        self.assertEqual(body["tool_choice"], {"type": "auto"}, "forced tool choice is rejected by current models")
        self.assertEqual([t["name"] for t in body["tools"]], [ai.TOOL])
        content = body["messages"][0]["content"]
        self.assertEqual([b["type"] for b in content], ["text", "image", "text"])
        self.assertEqual(content[1]["source"], {"type": "base64", "media_type": "image/jpeg", "data": "QUJD"})
        self.assertIn("Ignore sheet 3.", content[2]["text"])
        self.assertIn("Work in m.", content[2]["text"])
        self.assertEqual(seen["timeout"], 280)
        self.assertEqual((out["scene"]["units"], out["pieces"], out["usage"]["input_tokens"]), ("m", 1, 10))
        self.assertEqual(out["scene"]["components"][0]["source"], "dimensioned")
        # a description alone is enough
        ai.compose(self.cfg(), [], "Timber pier 120 ft by 16 ft.", "", opener)
        text = json.loads(seen["req"].data.decode("utf-8"))["messages"][0]["content"]
        self.assertEqual(len(text), 1)
        self.assertIn("Description from the user:", text[0]["text"])

    def test_the_prompt_and_tool_cover_every_component_type(self):
        prompt = ai.system_prompt()
        for type_id, t in scene.TYPES.items():
            self.assertIn(type_id, prompt)
        schema = ai.tool_schema()
        self.assertEqual(schema["name"], ai.TOOL)
        self.assertEqual(schema["input_schema"]["properties"]["components"]["type"], "array")
        json.dumps(schema)
        example = scene.normalise(ai.EXAMPLE)
        self.assertGreaterEqual(scene.count_parts(example), 2)

    def test_good_parts_are_kept_and_bad_parts_reported(self):
        reply = tool_reply({"name": "Pier", "structure_type": "Pier or jetty", "units": "ft", "datum": "MLLW", "components": [
            {"type": "pile", "name": "Good", "source": "scaled", "params": {"size": 1.5}},
            {"type": "gantry", "name": "Crane"},
            {"type": "pile", "name": "Trusting", "source": "library", "params": {}},
            {"type": "slab", "name": "Thin", "params": {"thickness": 0}}],
            "missing": ["Handrail: no sizes"], "general_notes": "Sheet 2 and 4 disagree."})
        sc, missing, notes, rejected = ai.parse_response(reply)
        self.assertEqual([c["name"] for c in sc["components"]], ["Good", "Trusting"])
        self.assertEqual([c["source"] for c in sc["components"]], ["scaled", "assumed"], "the model may not claim a size came from the library")
        self.assertEqual(len(rejected), 2)
        self.assertIn("Component 2 (Crane)", rejected[0])
        self.assertIn("Thin", rejected[1])
        self.assertEqual((missing, notes, sc["datum"]), (["Handrail: no sizes"], "Sheet 2 and 4 disagree.", "MLLW"))

    def test_json_in_plain_text_is_accepted(self):
        text = 'Sure. {"units": "m", "components": [{"type": "block", "name": "Cap {A}", "params": {}}]} Done.'
        sc = ai.parse_response({"stop_reason": "end_turn", "content": [{"type": "text", "text": text}]})[0]
        self.assertEqual((sc["units"], sc["components"][0]["name"]), ("m", "Cap {A}"))

    def test_connection_check(self):
        from urllib.error import HTTPError, URLError
        seen = {}

        def good(req, timeout):
            seen["req"] = req
            return FakeResponse({"type": "model", "id": "claude-opus-5-5", "display_name": "Claude Opus 5.5", "lifecycle": "active", "max_tokens": 64000,
                                 "capabilities": {"image_input": {"supported": True}}})

        out = ai.check_model(self.cfg(), good)
        self.assertEqual((out["ok"], out["display_name"], out["images"], out["warnings"]), (True, "Claude Opus 5.5", True, []))
        self.assertEqual((seen["req"].get_method(), seen["req"].full_url), ("GET", "https://api.anthropic.com/v1/models/claude-opus-5-5"))
        self.assertEqual({k.lower(): v for k, v in seen["req"].header_items()}["x-api-key"], "sk-test")

        def limited(req, timeout):
            return FakeResponse({"id": "old", "lifecycle": "deprecated", "max_tokens": 4096, "capabilities": {"image_input": {"supported": False}}})

        self.assertEqual(len(ai.check_model(self.cfg(), limited)["warnings"]), 3)

        def refuse(code):
            def opener(req, timeout):
                raise HTTPError(req.full_url, code, "x", {}, io.BytesIO(b'{"error": {"message": "detail here"}}'))
            return opener

        def offline(req, timeout):
            raise URLError("certificate verify failed")

        for opener, text in ((refuse(401), "key was not accepted"), (refuse(404), "cannot use the model 'claude-opus-5-5'"), (refuse(529), "returned an error (529). detail here"),
                             (offline, "Could not reach the Claude API from this server: certificate verify failed")):
            with self.assertRaises(ai.AiError) as caught:
                ai.check_model(self.cfg(), opener)
            self.assertIn(text, str(caught.exception))
        with self.assertRaises(ai.AiError) as caught:
            ai.check_model(self.cfg(ANTHROPIC_API_KEY=""))
        self.assertEqual(caught.exception.status, 503)

    def test_failures_are_reported(self):
        from urllib.error import HTTPError, URLError
        import socket

        def http_error(req, timeout):
            raise HTTPError(req.full_url, 429, "Too Many", {}, io.BytesIO(b'{"error": {"message": "rate limited"}}'))

        def offline(req, timeout):
            raise URLError("no route")

        def slow(req, timeout):
            raise socket.timeout()

        image = {"media_type": "image/png", "data": "QUJD"}
        cases = [
            (lambda: ai.compose(self.cfg(), [image], "", "", http_error), 502, "rate limited"),
            (lambda: ai.compose(self.cfg(), [image], "", "", offline), 502, "Could not reach"),
            (lambda: ai.compose(self.cfg(), [image], "", "", slow), 504, "did not answer"),
            (lambda: ai.compose(self.cfg(ANTHROPIC_API_KEY=""), [image], "", ""), 503, "No Anthropic API key"),
            (lambda: ai.compose(self.cfg(), [], "  ", ""), 400, ""),
            (lambda: ai.compose(self.cfg(MAX_IMAGES=1), [image, image], "", ""), 400, "Too many images"),
            (lambda: ai.compose(self.cfg(), [{"media_type": "image/gif", "data": "x"}], "", ""), 400, "image/jpeg or image/png"),
            (lambda: ai.compose(self.cfg(), "images", "", ""), 400, ""),
            (lambda: ai.parse_response(tool_reply({"components": []}, stop="max_tokens")), 502, "cut off"),
            (lambda: ai.parse_response({"content": [{"type": "text", "text": "I cannot read these."}]}), 502, "I cannot read these."),
        ]
        for call, status, text in cases:
            with self.assertRaises(ai.AiError) as caught:
                call()
            self.assertEqual(caught.exception.status, status, text)
            self.assertIn(text, str(caught.exception))

    def test_gemini_request_shape(self):
        seen = {}

        def opener(req, timeout):
            seen["req"], seen["timeout"] = req, timeout
            return FakeResponse(openai_reply({"name": "Pier", "units": "m", "components": [{"type": "pile", "name": "P", "source": "dimensioned", "params": {}}]}))

        images = [{"label": "Page 1: whole sheet overview", "media_type": "image/jpeg", "data": "QUJD"}]
        out = ai.compose(self.gemini_cfg(), images, "Ignore sheet 3.", "m", opener)
        self.assertEqual(seen["req"].full_url, "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions")
        headers = {k.lower(): v for k, v in seen["req"].header_items()}
        self.assertEqual(headers["authorization"], "Bearer gem-test")
        self.assertNotIn("x-api-key", headers)
        body = json.loads(seen["req"].data.decode("utf-8"))
        self.assertEqual((body["model"], body["max_tokens"]), ("gemini-2.5-flash", 16000))
        self.assertEqual(body["tool_choice"], {"type": "function", "function": {"name": ai.TOOL}})
        self.assertEqual(body["tools"], [{"type": "function", "function": {"name": ai.TOOL, "description": ai.tool_schema()["description"],
                                                                            "parameters": ai.tool_schema()["input_schema"]}}])
        messages = body["messages"]
        self.assertEqual([m["role"] for m in messages], ["system", "user"])
        self.assertIn(ai.TOOL, messages[0]["content"])
        content = messages[1]["content"]
        self.assertEqual([b["type"] for b in content], ["text", "image_url", "text"])
        self.assertEqual(content[1]["image_url"], {"url": "data:image/jpeg;base64,QUJD"})
        self.assertIn("Ignore sheet 3.", content[2]["text"])
        self.assertIn("Work in m.", content[2]["text"])
        self.assertEqual(seen["timeout"], 280)
        self.assertEqual((out["scene"]["units"], out["pieces"], out["model"], out["usage"]["total_tokens"]), ("m", 1, "gemini-2.5-flash", 28))
        # a description alone is enough
        ai.compose(self.gemini_cfg(), [], "Timber pier 120 ft by 16 ft.", "", opener)
        text = json.loads(seen["req"].data.decode("utf-8"))["messages"][1]["content"]
        self.assertEqual(len(text), 1)
        self.assertIn("Description from the user:", text[0]["text"])

    def test_gemini_list_shaped_error_body_is_read(self):
        # Gemini's OpenAI-compatible layer wraps errors in a one-item list; the native API and Anthropic return an
        # object. Both shapes must surface the message, or the user sees only a bare status code.
        def failing_list(req, timeout):
            raise HTTPError(req.full_url, 503, "Unavailable", {},
                            io.BytesIO(b'[{"error": {"code": 503, "message": "high demand", "status": "UNAVAILABLE"}}]'))

        with self.assertRaises(ai.AiError) as caught:
            ai.call_api(self.gemini_cfg(), {"model": "gemini-3.8-flash", "messages": []}, failing_list)
        self.assertIn("high demand", str(caught.exception))

        def failing_object(req, timeout):
            raise HTTPError(req.full_url, 400, "Bad Request", {},
                            io.BytesIO(b'{"error": {"message": "bad key"}}'))

        with self.assertRaises(ai.AiError) as caught:
            ai.call_api(self.gemini_cfg(), {"model": "gemini-3.8-flash", "messages": []}, failing_object)
        self.assertIn("bad key", str(caught.exception))

    def test_gemini_tool_call_is_read_and_bad_parts_reported(self):
        reply = openai_reply({"name": "Pier", "structure_type": "Pier or jetty", "units": "ft", "datum": "MLLW", "components": [
            {"type": "pile", "name": "Good", "source": "scaled", "params": {"size": 1.5}},
            {"type": "gantry", "name": "Crane"},
            {"type": "slab", "name": "Thin", "params": {"thickness": 0}}],
            "missing": ["Handrail: no sizes"], "general_notes": "Sheet 2 and 4 disagree."})
        sc, missing, notes, rejected = ai.parse_response(reply)
        self.assertEqual([c["name"] for c in sc["components"]], ["Good"])
        self.assertEqual(len(rejected), 2)
        self.assertIn("Component 2 (Crane)", rejected[0])
        self.assertEqual((missing, notes, sc["datum"]), (["Handrail: no sizes"], "Sheet 2 and 4 disagree.", "MLLW"))

    def test_gemini_plain_text_json_is_accepted(self):
        text = 'Sure. {"units": "m", "components": [{"type": "block", "name": "Cap {A}", "params": {}}]} Done.'
        sc = ai.parse_response(openai_reply(None, finish="stop", content=text))[0]
        self.assertEqual((sc["units"], sc["components"][0]["name"]), ("m", "Cap {A}"))

    def test_gemini_failures_are_reported(self):
        from urllib.error import HTTPError, URLError
        import socket

        def http_error(req, timeout):
            raise HTTPError(req.full_url, 429, "Too Many", {}, io.BytesIO(b'{"error": {"message": "rate limited"}}'))

        def offline(req, timeout):
            raise URLError("no route")

        def slow(req, timeout):
            raise socket.timeout()

        image = {"media_type": "image/png", "data": "QUJD"}
        cases = [
            (lambda: ai.compose(self.gemini_cfg(), [image], "", "", http_error), 502, "Gemini API returned an error (429). rate limited"),
            (lambda: ai.compose(self.gemini_cfg(), [image], "", "", offline), 502, "Could not reach the Gemini API"),
            (lambda: ai.compose(self.gemini_cfg(), [image], "", "", slow), 504, "Gemini API did not answer"),
            (lambda: ai.compose(self.gemini_cfg(GEMINI_API_KEY=""), [image], "", ""), 503, "No Gemini API key"),
            (lambda: ai.compose(self.gemini_cfg(AI_PROVIDER="other"), [image], "", ""), 400, "Unknown AI_PROVIDER"),
            (lambda: ai.parse_response(openai_reply({"components": []}, finish="length")), 502, "cut off"),
            (lambda: ai.parse_response(openai_reply(None, finish="stop", content="I cannot read these.")), 502, "I cannot read these."),
        ]
        for call, status, text in cases:
            with self.assertRaises(ai.AiError) as caught:
                call()
            self.assertEqual(caught.exception.status, status, text)
            self.assertIn(text, str(caught.exception))

    def test_gemini_connection_check(self):
        from urllib.error import HTTPError, URLError
        seen = {}

        def listing(req, timeout):
            seen["req"] = req
            return FakeResponse({"object": "list", "data": [{"id": "gemini-2.5-flash", "object": "model"}, {"id": "gemini-2.5-pro", "object": "model"}]})

        out = ai.check_model(self.gemini_cfg(), listing)
        self.assertEqual((out["ok"], out["model"], out["warnings"]), (True, "gemini-2.5-flash", []))
        self.assertEqual((seen["req"].get_method(), seen["req"].full_url),
                         ("GET", "https://generativelanguage.googleapis.com/v1beta/openai/models"))
        self.assertEqual({k.lower(): v for k, v in seen["req"].header_items()}["authorization"], "Bearer gem-test")

        def unlisted(req, timeout):
            return FakeResponse({"object": "list", "data": [{"id": "gemini-2.5-pro", "object": "model"}]})

        self.assertEqual(len(ai.check_model(self.gemini_cfg(), unlisted)["warnings"]), 1)

        def compat_missing(req, timeout):
            # Gemini's OpenAI-compatible layer has no /models endpoint: it 404s,
            # so the check falls back to the native list one level up.
            if req.full_url.endswith("/openai/models"):
                raise HTTPError(req.full_url, 404, "Not Found", {}, io.BytesIO(b'{"error": {"message": "Requested entity was not found."}}'))
            seen["fallback_url"] = req.full_url
            return FakeResponse({"models": [{"name": "models/gemini-2.5-flash"}, {"name": "models/gemini-3.8-flash"}]})

        out = ai.check_model(self.gemini_cfg(), compat_missing)
        self.assertEqual((out["ok"], out["model"], out["warnings"]), (True, "gemini-2.5-flash", []))
        self.assertEqual(seen["fallback_url"], "https://generativelanguage.googleapis.com/v1beta/models")

        def refuse(code):
            def opener(req, timeout):
                raise HTTPError(req.full_url, code, "x", {}, io.BytesIO(b'{"error": {"message": "detail here"}}'))
            return opener

        def offline(req, timeout):
            raise URLError("certificate verify failed")

        for opener, text in ((refuse(401), "key was not accepted"), (refuse(403), "key was not accepted"),
                             (refuse(500), "returned an error (500). detail here"),
                             (offline, "Could not reach the Gemini API from this server: certificate verify failed")):
            with self.assertRaises(ai.AiError) as caught:
                ai.check_model(self.gemini_cfg(), opener)
            self.assertIn(text, str(caught.exception))
        with self.assertRaises(ai.AiError) as caught:
            ai.check_model(self.gemini_cfg(GEMINI_API_KEY=""))
        self.assertEqual(caught.exception.status, 503)

    def test_describe_reports_the_active_provider(self):
        self.assertEqual(ai.describe(self.cfg()), ("anthropic", "claude-opus-5-5", True))
        self.assertEqual(ai.describe(self.cfg(ANTHROPIC_API_KEY="")), ("anthropic", "claude-opus-5-5", False))
        self.assertEqual(ai.describe(self.gemini_cfg()), ("gemini", "gemini-2.5-flash", True))
        self.assertEqual(ai.describe(self.gemini_cfg(GEMINI_API_KEY="")), ("gemini", "gemini-2.5-flash", False))
        self.assertEqual(ai.describe({"AI_PROVIDER": "other"}), ("anthropic", "", False))


def request(method, path, body=None, cookie=None, addr="127.0.0.1", raw=None):
    path, _, query = path.partition("?")
    data = raw if raw is not None else (json.dumps(body).encode("utf-8") if body is not None else b"")
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": query, "CONTENT_LENGTH": str(len(data)), "wsgi.input": io.BytesIO(data),
           "wsgi.errors": io.StringIO(), "wsgi.url_scheme": "https", "REMOTE_ADDR": addr}
    if cookie:
        env["HTTP_COOKIE"] = cookie
    seen = {}

    def start(status, headers):
        seen["status"] = int(status.split()[0])
        seen["headers"] = dict(headers)

    out = b"".join(server.application(env, start))
    return seen["status"], seen["headers"], out


def get(path, **kw):
    status, _, body = request("GET", path, **kw)
    return status, json.loads(body)


def post(path, body, **kw):
    status, _, out = request("POST", path, body, **kw)
    return status, json.loads(out)


class ServerTest(Env):
    def login(self):
        status, headers, _ = request("POST", "/api/login", {"password": "pw"}, addr="203.0.113.9")
        self.assertEqual(status, 200)
        return headers["Set-Cookie"].split(";")[0]

    def test_pages_and_files(self):
        status, headers, body = request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"PDF to IFC Modeler", body)
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        for path in re.findall(r'(?:src|href)="\./(static/[^"]+)"', body.decode("utf-8")) + ["static/viewer.js", "static/vendor/three/three.core.js",
                                                                                           "static/vendor/three/OrbitControls.js", "static/vendor/pdfjs/pdf.worker.min.mjs"]:
            self.assertEqual(request("GET", "/" + path)[0], 200, path)
        self.assertEqual(request("GET", "/static/vendor/pdfjs/pdf.min.mjs")[1]["Content-Type"], "text/javascript; charset=utf-8")
        for bad in ("/static/../app/server.py", "/static/.hidden", "/app/server.py", "/config.local.json", "/app/seed.json", "/api/nothing"):
            self.assertEqual(request("GET", bad)[0], 404, bad)
        self.assertEqual(request("GET", "/api/preview")[0], 405)

    def test_on_your_own_machine_everything_works_without_a_password(self):
        status, health = get("/api/health")
        self.assertEqual((health["storage"], health["login_required"], health["ai_ready"], health["version"]), ("server", False, False, server.VERSION))
        self.assertEqual(health["db_counts"], {"models": 6, "library": 26})
        self.assertIn("No Anthropic API key", health["ai_reason"])
        self.assertTrue(os.path.isfile(os.environ["DB_PATH"]))
        cat = get("/api/catalogue")[1]
        self.assertEqual(cat["ifc_schemas"], ["IFC2X3", "IFC4X3"])
        self.assertEqual(len(cat["types"]), len(scene.TYPES))
        self.assertEqual(len(get("/api/seed")[1]["models"]), 6)

        status, out = post("/api/preview", {"scene": PIER})
        self.assertEqual((status, out["parts"], out["scene"]["name"]), (200, 9, "Test pier"))
        for schema, marker in (("IFC2X3", b"FILE_SCHEMA(('IFC2X3'))"), ("IFC4X3", b"FILE_SCHEMA(('IFC4X3_ADD2'))")):
            status, headers, body = request("POST", "/api/export", {"scene": PIER, "schema": schema})
            self.assertEqual(status, 200)
            self.assertIn('filename="Test_pier.ifc"', headers["Content-Disposition"])
            self.assertIn(marker, body)
        status, out = post("/api/convert", {"scene": PIER, "units": "m"})
        self.assertAlmostEqual(out["scene"]["components"][0]["array"]["dx"], 3.048)
        status, out = post("/api/convert", {"component": PIER["components"][0], "from": "ft", "to": "mm"})
        self.assertAlmostEqual(out["component"]["array"]["dx"], 3048.0)

        status, out = post("/api/models", {"scene": PIER})
        new_id = out["id"]
        self.assertEqual(status, 200)
        self.assertEqual(get("/api/models?q=harbour")[1]["models"][0]["id"], new_id)
        self.assertEqual(get("/api/models/%d" % new_id)[1]["scene"]["name"], "Test pier")
        self.assertEqual(post("/api/models", {"scene": dict(PIER, name="Second name"), "id": new_id})[1]["id"], new_id)
        self.assertEqual(get("/api/models/%d" % new_id)[1]["scene"]["name"], "Second name")
        self.assertEqual(post("/api/models/%d/delete" % new_id, {})[0], 200)
        self.assertEqual(get("/api/models/%d" % new_id)[0], 404)

        status, out = post("/api/library", {"name": "My pile", "category": "Piles", "units": "ft", "item": PIER["components"][0]})
        self.assertEqual(status, 200)
        self.assertEqual(get("/api/library/%d" % out["id"])[1]["item"]["source"], "library")
        self.assertEqual(len(get("/api/library?q=my+pile")[1]["items"]), 1)
        self.assertEqual(post("/api/library/%d/delete" % out["id"], {})[0], 200)
        self.assertEqual(post("/api/library/%d/delete" % out["id"], {})[0], 404)

    def test_errors_are_readable(self):
        bad = dict(PIER, components=[{"type": "pile", "name": "North pile", "params": {"size": "wide"}}])
        for path, body in (("/api/preview", {"scene": bad}), ("/api/export", {"scene": bad}), ("/api/models", {"scene": bad})):
            status, out = post(path, body)
            self.assertEqual(status, 400, path)
            self.assertIn("'North pile' (pile), diameter or width: 'wide' is not a number", out["error"])
        self.assertEqual(post("/api/export", {"scene": PIER, "schema": "IFC9"})[0], 400)
        self.assertEqual(post("/api/models", {"scene": dict(PIER, name="")})[0], 400)
        status, _, body = request("POST", "/api/preview", raw=b"{not json")
        self.assertEqual(status, 400)
        os.environ["MAX_BODY_MB"] = "1"
        status, _, body = request("POST", "/api/preview", raw=b" " * (1024 * 1024 + 10))
        self.assertEqual(status, 413)
        self.assertEqual(post("/api/compose", {"images": [], "notes": "A pier"})[0], 503)           # no key configured

    def test_an_ai_run_keeps_the_connection_alive_and_reports_failures_in_the_body(self):
        os.environ["ANTHROPIC_API_KEY"] = "sk-test"
        real_compose, real_beat = ai.compose, server.HEARTBEAT
        calls = []

        def slow(cfg, images, notes, units):
            calls.append((images, notes, units))
            time.sleep(0.35)
            if notes == "fail":
                raise ai.AiError("The Claude API returned an error (529). Overloaded", 502)
            if notes == "crash":
                raise RuntimeError("boom")
            return {"scene": scene.normalise(PIER), "pieces": 9, "missing": [], "rejected": [], "general_notes": "", "usage": {}}

        ai.compose, server.HEARTBEAT = slow, 0.1
        try:
            status, headers, body = request("POST", "/api/compose", {"images": [], "notes": "A pier", "units": "m"})
            self.assertEqual(status, 200)
            self.assertNotIn("Content-Length", headers)
            self.assertGreaterEqual(len(body) - len(body.lstrip(b" ")), 2, "keep-alive bytes go out while the model works")
            self.assertEqual(json.loads(body)["pieces"], 9)
            self.assertEqual(calls[0], ([], "A pier", "m"))
            status, _, body = request("POST", "/api/compose", {"images": [], "notes": "fail"})
            self.assertEqual((status, json.loads(body)), (200, {"error": "The Claude API returned an error (529). Overloaded", "status": 502}))
            err = io.StringIO()
            old, sys.stderr = sys.stderr, err
            try:
                status, _, body = request("POST", "/api/compose", {"images": [], "notes": "crash"})
            finally:
                sys.stderr = old
            self.assertEqual(json.loads(body)["status"], 500)
            self.assertNotIn("boom", body.decode("utf-8"))
            self.assertIn("boom", err.getvalue())
            # what can be refused at once still gets a proper status, and never reaches the model
            n = len(calls)
            self.assertEqual(post("/api/compose", {"images": [], "notes": " "})[0], 400)
            self.assertEqual(post("/api/compose", {"images": [{"media_type": "image/gif", "data": "x"}]})[0], 400)
            self.assertEqual(post("/api/compose", {"images": [], "notes": "A pier"}, addr="203.0.113.9")[0], 403)
            self.assertEqual(len(calls), n)
        finally:
            ai.compose, server.HEARTBEAT = real_compose, real_beat

    def test_connection_check_route(self):
        self.assertEqual(post("/api/ai-check", {})[0], 503)                                         # no key yet
        os.environ["ANTHROPIC_API_KEY"] = "sk-test"
        self.assertEqual(post("/api/ai-check", {}, addr="203.0.113.9")[0], 403)
        self.assertEqual(request("GET", "/api/ai-check")[0], 405)
        real = ai.check_model
        try:
            ai.check_model = lambda cfg: {"ok": True, "model": "m", "display_name": "M", "warnings": []}
            self.assertEqual(post("/api/ai-check", {}), (200, {"ok": True, "model": "m", "display_name": "M", "warnings": []}))

            def broken(cfg):
                raise ai.AiError("The Anthropic API key was not accepted (401). invalid x-api-key", 502)
            ai.check_model = broken
            status, out = post("/api/ai-check", {})
            self.assertEqual((status, out["error"]), (502, "The Anthropic API key was not accepted (401). invalid x-api-key"))
        finally:
            ai.check_model = real

    def test_a_visitor_from_elsewhere_gets_no_database_and_no_ai_without_a_password(self):
        os.environ["ANTHROPIC_API_KEY"] = "sk-test"
        there = {"addr": "203.0.113.9"}
        health = get("/api/health", **there)[1]
        self.assertEqual((health["storage"], health["ai_ready"], health["db_counts"]), ("browser", False, {}))
        self.assertIn("APP_PASSWORD", health["storage_reason"])
        self.assertFalse(os.path.exists(os.environ["DB_PATH"]), "the database is not even created for them")
        self.assertEqual(post("/api/preview", {"scene": PIER}, **there)[0], 200)
        self.assertEqual(request("POST", "/api/export", {"scene": PIER}, **there)[0], 200)
        self.assertEqual(get("/api/seed", **there)[0], 200)
        for method, path in (("GET", "/api/models"), ("POST", "/api/models"), ("GET", "/api/library"), ("POST", "/api/library/1/delete"), ("POST", "/api/compose")):
            status, _, body = request(method, path, {"scene": PIER} if method == "POST" else None, **there)
            self.assertEqual(status, 403, path)
            self.assertIn("APP_PASSWORD", json.loads(body)["error"])
        self.assertNotIn(b"sk-test", request("GET", "/api/health", **there)[2])

    def test_password_gate(self):
        os.environ["APP_PASSWORD"] = "pw"
        os.environ["ANTHROPIC_API_KEY"] = "sk-test"
        for addr in ("127.0.0.1", "203.0.113.9"):
            health = get("/api/health", addr=addr)[1]
            self.assertEqual((health["login_required"], health["logged_in"], health["storage"], health["ai_ready"]), (True, False, "browser", False))
            for method, path in (("GET", "/api/catalogue"), ("POST", "/api/preview"), ("GET", "/api/models"), ("GET", "/api/seed"), ("POST", "/api/compose")):
                self.assertEqual(request(method, path, {} if method == "POST" else None, addr=addr)[0], 401, path)
        self.assertEqual(request("GET", "/")[0], 200)
        self.assertEqual(post("/api/login", {"password": "nope"})[0], 401)
        cookie = self.login()
        self.assertIn("HttpOnly", request("POST", "/api/login", {"password": "pw"})[1]["Set-Cookie"])
        there = {"addr": "203.0.113.9", "cookie": cookie}
        health = get("/api/health", **there)[1]
        self.assertEqual((health["logged_in"], health["storage"], health["ai_ready"]), (True, "server", True))
        self.assertEqual(post("/api/models", {"scene": PIER}, **there)[0], 200)
        self.assertEqual(len(get("/api/models", **there)[1]["models"]), 7)
        self.assertEqual(get("/api/models", addr="203.0.113.9", cookie="p2i=forged.token")[0], 401)
        os.environ["APP_PASSWORD"] = "changed"
        self.assertEqual(get("/api/models", **there)[0], 401, "changing the password signs everyone out")

    def test_tokens_expire(self):
        os.environ["APP_PASSWORD"] = "pw"
        cfg = config.load()
        self.assertTrue(auth.token_ok(cfg, auth.new_token(cfg)))
        self.assertFalse(auth.token_ok(cfg, auth.new_token(cfg, now=1.0)))
        self.assertFalse(auth.token_ok(cfg, "junk"))

    def test_a_broken_database_does_not_take_the_app_down(self):
        os.environ["DB_PATH"] = os.path.join(self.tmp, "blocker", "x.sqlite3")
        with open(os.path.join(self.tmp, "blocker"), "w") as fh:
            fh.write("a file where the folder should be")
        health = get("/api/health")[1]
        self.assertEqual(health["storage"], "browser")
        self.assertTrue(health["db_error"])
        self.assertEqual(post("/api/preview", {"scene": PIER})[0], 200)


class CgiTest(Env):
    def test_runs_as_plain_cgi(self):
        env = dict(os.environ, REQUEST_METHOD="GET", PATH_INFO="/api/health", SCRIPT_NAME="/index.cgi", SERVER_NAME="x", SERVER_PORT="80",
                   SERVER_PROTOCOL="HTTP/1.1", REMOTE_ADDR="203.0.113.9")
        out = subprocess.run([sys.executable, os.path.join(ROOT, "index.cgi")], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60).stdout
        head, _, body = out.partition(b"\r\n\r\n")
        self.assertIn(b"200", head.split(b"\r\n")[0])
        self.assertEqual(json.loads(body)["version"], server.VERSION)

        body = json.dumps({"scene": PIER, "schema": "IFC4X3"}).encode("utf-8")
        env.update(REQUEST_METHOD="POST", PATH_INFO="/api/export", CONTENT_LENGTH=str(len(body)), CONTENT_TYPE="application/json")
        out = subprocess.run([sys.executable, os.path.join(ROOT, "index.cgi")], env=env, input=body, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60).stdout
        self.assertIn(b"ISO-10303-21;", out)
        self.assertIn(b"IFCMARINEFACILITY", out)


class SetupScriptTest(Env):
    """tools/setup_server.py: writes the private config and checks the machine."""
    def setUp(self):
        Env.setUp(self)
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import setup_server
        self.tool = setup_server
        self.home, os.environ["HOME"] = os.environ.get("HOME"), self.tmp
        self.cfg_path = os.path.join(self.tmp, "private", "config.json")
        os.environ["PDF2IFC_CONFIG"] = self.cfg_path
        self.mode = os.stat(os.path.join(ROOT, "index.cgi")).st_mode

    def tearDown(self):
        os.chmod(os.path.join(ROOT, "index.cgi"), self.mode)
        if self.home is not None:
            os.environ["HOME"] = self.home
        Env.tearDown(self)

    def run_tool(self, argv, secrets_typed=(), answers=(), opener=None):
        out, typed, said = io.StringIO(), list(secrets_typed), list(answers)
        code = self.tool.main(argv, ask=lambda prompt: said.pop(0), ask_secret=lambda prompt: typed.pop(0), out=out, opener=opener)
        self.assertEqual((typed, said), ([], []), "every prompt answer should have been used")
        return code, out.getvalue()

    @staticmethod
    def api(req, timeout):
        if req.get_method() == "GET":
            return FakeResponse({"id": "claude-opus-5-5", "display_name": "Claude Opus 5.5", "lifecycle": "active", "capabilities": {"image_input": {"supported": True}}})
        return FakeResponse(tool_reply({"name": "Pier", "units": "ft", "components": [
            {"type": "pile", "name": "Piles", "source": "dimensioned", "array": {"nx": 4, "dx": 20, "ny": 2, "dy": 8}, "params": {}},
            {"type": "slab", "name": "Deck", "source": "dimensioned", "params": {}}]}))

    def test_first_run_writes_a_private_config_and_everything_passes(self):
        code, text = self.run_tool([], secrets_typed=["sk-ant-test-1234", "a long password", "a long password"], opener=self.api)
        self.assertEqual(code, 0, text)
        with open(self.cfg_path) as fh:
            self.assertEqual(json.load(fh), {"ANTHROPIC_API_KEY": "sk-ant-test-1234", "APP_PASSWORD": "a long password"})
        if os.name != "nt":
            self.assertEqual(os.stat(self.cfg_path).st_mode & 0o777, 0o600)
            self.assertEqual(os.stat(os.path.dirname(self.cfg_path)).st_mode & 0o777, 0o700)
        self.assertNotIn("sk-ant-test-1234", text)
        self.assertNotIn("a long password", text)
        self.assertIn("ends in ...1234", text)
        for line in ("Python version", "SQLite", "Database", "Web entry point (index.cgi): answers as version %s; sign-in required" % server.VERSION,
                     "Claude API connection: Claude Opus 5.5 answered", "Ready. Open the app's address in a browser and sign in."):
            self.assertIn(line, text)
        self.assertNotIn("FAIL", text)
        self.assertTrue(os.path.isfile(os.environ["DB_PATH"]))
        # a second run asks nothing and changes nothing
        before = os.stat(self.cfg_path).st_mtime_ns
        code, text = self.run_tool([], opener=self.api)
        self.assertEqual((code, os.stat(self.cfg_path).st_mtime_ns), (0, before))

    def test_a_password_is_made_when_none_is_typed_and_weak_ones_are_refused(self):
        code, text = self.run_tool(["--check"])
        self.assertEqual(code, 0)
        self.assertFalse(os.path.exists(self.cfg_path), "--check writes nothing")
        self.assertIn("App password: not set", text)
        code, text = self.run_tool([], secrets_typed=["", "short", "long enough one", "different one", ""])
        with open(self.cfg_path) as fh:
            saved = json.load(fh)
        self.assertEqual(list(saved), ["APP_PASSWORD"])
        self.assertGreaterEqual(len(saved["APP_PASSWORD"]), 20)
        self.assertIn(saved["APP_PASSWORD"], text, "a generated password is shown once so it can be stored")
        self.assertIn("Use at least 10 characters.", text)
        self.assertIn("The two did not match.", text)
        self.assertIn("Anthropic API key: not set", text)

    def test_existing_settings_are_kept(self):
        self.tool.write_config(self.cfg_path, {"ANTHROPIC_API_KEY": "paste-your-key-here", "APP_PASSWORD": "kept password", "MAX_IMAGES": 40})
        code, text = self.run_tool([], secrets_typed=["sk-ant-new"], opener=self.api)
        with open(self.cfg_path) as fh:
            self.assertEqual(json.load(fh), {"ANTHROPIC_API_KEY": "sk-ant-new", "APP_PASSWORD": "kept password", "MAX_IMAGES": 40})

    def test_problems_are_named_with_a_fix(self):
        from urllib.error import HTTPError
        self.tool.write_config(self.cfg_path, {"ANTHROPIC_API_KEY": "sk-ant-bad", "APP_PASSWORD": "a long password"})

        def refused(req, timeout):
            raise HTTPError(req.full_url, 401, "x", {}, io.BytesIO(b'{"error": {"message": "invalid x-api-key"}}'))

        code, text = self.run_tool(["--check", "--ai-test"], opener=refused)
        self.assertEqual(code, 1)
        self.assertIn("[ FAIL ] Claude API connection: The Anthropic API key was not accepted (401). invalid x-api-key", text)
        self.assertIn("AI test run: skipped", text)
        self.assertIn("1 problem(s) to fix: Claude API connection", text)
        if os.name != "nt":
            os.chmod(os.path.join(ROOT, "index.cgi"), 0o644)
            code, text = self.run_tool(["--check"], opener=self.api)
            self.assertEqual(code, 1)
            self.assertIn("[ FAIL ] Permissions", text)
            code, text = self.run_tool([], opener=self.api)                    # without --check it repairs them
            self.assertEqual(code, 0, text)
            self.assertEqual(os.stat(os.path.join(ROOT, "index.cgi")).st_mode & 0o777, 0o755)
        with open(self.cfg_path, "w") as fh:
            fh.write("{broken")
        self.assertEqual(self.run_tool([])[0], 2)
        self.assertEqual(self.run_tool(["--check"])[0], 1)

    def test_billed_test_run_asks_first(self):
        self.tool.write_config(self.cfg_path, {"ANTHROPIC_API_KEY": "sk-ant-ok", "APP_PASSWORD": "a long password"})
        posts = []

        def api(req, timeout):
            if req.get_method() == "POST":
                posts.append(json.loads(req.data.decode("utf-8")))
            return self.api(req, timeout)

        code, text = self.run_tool(["--check", "--ai-test"], answers=["n"], opener=api)
        self.assertEqual((code, posts), (0, []))
        code, text = self.run_tool(["--check", "--ai-test"], answers=["y"], opener=api)
        self.assertEqual((code, len(posts)), (0, 1))
        self.assertEqual(posts[0]["messages"][0]["content"][0]["type"], "text")
        self.assertIn("AI test run: 2 components, 9 pieces", text)
        self.assertIn("- Piles (pile, sizes dimensioned)", text)
        code, text = self.run_tool(["--check", "--ai-test", "--yes"], opener=api)
        self.assertEqual(len(posts), 2)


class PackagingTest(unittest.TestCase):
    def test_browser_preview_loads_every_module_it_needs(self):
        with open(os.path.join(ROOT, "static", "app.js")) as fh:
            js = fh.read()
        listed = set(re.findall(r'"(app/[A-Za-z_/]+\.py)"', re.search(r"const PREVIEW_FILES = \[(.*?)\];", js, re.S).group(1)))
        needed, queue = set(), ["app/browser.py"]
        while queue:
            path = queue.pop()
            if path in needed:
                continue
            needed.add(path)
            folder = os.path.dirname(path)
            needed.add(folder + "/__init__.py")
            with open(os.path.join(ROOT, path)) as fh:
                src = fh.read()
            for dots, mod, names in re.findall(r"^from (\.+)([\w.]*) import ([\w, ]+)", src, re.M):
                base = folder if len(dots) == 1 else os.path.dirname(folder)
                targets = [mod.replace(".", "/")] if mod else [n.strip().split(" as ")[0] for n in names.split(",")]
                for t in targets + ([mod.replace(".", "/") + "/" + n.strip() for n in names.split(",")] if mod else []):
                    for cand in (base + "/" + t + ".py", base + "/" + t + "/__init__.py"):
                        if os.path.isfile(os.path.join(ROOT, cand)):
                            queue.append(cand)
        self.assertEqual(listed, needed)
        for path in listed:                                                     # nothing the page loads may need the server-only parts
            with open(os.path.join(ROOT, path)) as fh:
                self.assertNotRegex(fh.read(), r"import (sqlite3|urllib|socket|wsgiref)")
        self.assertIn(config.DEFAULTS["ANTHROPIC_MODEL"], "claude-opus-5-5")

    def test_nothing_secret_or_generated_is_committed(self):
        with open(os.path.join(ROOT, ".gitignore")) as fh:
            ignore = fh.read()
        for pattern in ("config.local.json", "*.sqlite3"):
            self.assertIn(pattern, ignore)
        with open(os.path.join(ROOT, ".htaccess")) as fh:
            rules = fh.read()
        self.assertIn("app|", rules)
        self.assertRegex(rules, r"sqlite")


if __name__ == "__main__":
    unittest.main()
