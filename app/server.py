"""WSGI application using only the standard library, so it runs as plain CGI on shared hosting."""
import json
import mimetypes
import os
import re
import sys
import threading
import time
import traceback

try:
    from urllib.parse import parse_qs
except ImportError:                                   # pragma: no cover
    from urlparse import parse_qs

from . import ai, auth, config, db, service
from .ifcexport import SCHEMAS
from .scene import SceneError, catalogue

ROOT = config.ROOT
STATIC = os.path.join(ROOT, "static")
VERSION = "2.1.0"
HEARTBEAT = 10.0                                      # seconds between keep-alive bytes during an AI run
_SAFE = re.compile(r"^[A-Za-z0-9_.-]+$")
_LOCAL = ("127.0.0.1", "::1", "localhost")


class HttpError(Exception):
    def __init__(self, status, message):
        Exception.__init__(self, message)
        self.status = status


def _status(code):
    names = {200: "OK", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found",
             405: "Method Not Allowed", 413: "Payload Too Large", 500: "Internal Server Error", 502: "Bad Gateway",
             503: "Service Unavailable", 504: "Gateway Timeout"}
    return "%d %s" % (code, names.get(code, "Error"))


def _json(code, data, extra=None):
    body = json.dumps(data).encode("utf-8")
    headers = [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(body))),
               ("Cache-Control", "no-store")] + (extra or [])
    return _status(code), headers, body


def _file(path):
    with open(path, "rb") as fh:
        body = fh.read()
    ext = os.path.splitext(path)[1].lower()
    ctype = {".mjs": "text/javascript", ".js": "text/javascript", ".wasm": "application/wasm"}.get(ext) or \
        mimetypes.guess_type(path)[0] or "application/octet-stream"
    if ctype.startswith("text/"):
        ctype += "; charset=utf-8"
    return _status(200), [("Content-Type", ctype), ("Content-Length", str(len(body)))], body


def _download(text, filename, ctype):
    body = text.encode("utf-8")
    return _status(200), [("Content-Type", ctype), ("Content-Length", str(len(body))), ("Cache-Control", "no-store"),
                          ("Content-Disposition", 'attachment; filename="%s"' % filename)], body


def _read_json(environ, cfg):
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        length = 0
    if length <= 0:
        raise HttpError(400, "Request body is empty.")
    if length > cfg["MAX_BODY_MB"] * 1024 * 1024:
        raise HttpError(413, "Upload is larger than %d MB. Choose fewer pages or a lower detail level." % cfg["MAX_BODY_MB"])
    raw = environ["wsgi.input"].read(length)
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise HttpError(400, "Request body is not valid JSON.")
    if not isinstance(data, dict):
        raise HttpError(400, "Request body must be a JSON object.")
    return data


def _compose_stream(cfg, data):
    """Run the AI call while sending a space every few seconds, then the JSON result.

    Shared hosts stop a request whose script stays silent too long, and an AI run can take minutes. JSON may start
    with white space, so the browser reads the reply as usual. The status line has gone out by the time the
    result is known, so a failure is reported inside the body as {"error": ..., "status": ...}.
    """
    result = {}

    def work():
        try:
            result["body"] = ai.compose(cfg, data.get("images"), data.get("notes") or "", str(data.get("units") or ""))
        except ai.AiError as err:
            result["body"] = {"error": str(err), "status": err.status}
        except Exception:
            traceback.print_exc(file=sys.stderr)
            result["body"] = {"error": "The server hit an unexpected error. Check the host's error log.", "status": 500}

    worker = threading.Thread(target=work)
    worker.daemon = True
    worker.start()

    def body():
        yield b" "                                     # sends the headers straight away
        while True:
            worker.join(HEARTBEAT)
            if not worker.is_alive():
                break
            yield b" "
        yield json.dumps(result["body"]).encode("utf-8")

    return _status(200), [("Content-Type", "application/json; charset=utf-8"), ("Cache-Control", "no-store"),
                          ("X-Accel-Buffering", "no")], body()


def _store(cfg):
    return db.Store(cfg["DB_PATH"] or db.default_path())


def _id(text):
    try:
        return int(text)
    except ValueError:
        raise HttpError(404, "Not found.")


def handle(environ, cfg):
    method = environ.get("REQUEST_METHOD", "GET").upper()
    path = environ.get("PATH_INFO") or "/"
    query = parse_qs(environ.get("QUERY_STRING") or "")
    q = lambda key: (query.get(key) or [""])[0]
    secure = environ.get("wsgi.url_scheme") == "https" or environ.get("HTTPS", "").lower() in ("on", "1")
    need_login = bool(cfg["APP_PASSWORD"])
    logged_in = need_login and auth.token_ok(cfg, auth.cookie_from(environ))
    # Without a password, the database and the AI are only offered to someone on the same machine.
    trusted = logged_in or (not need_login and environ.get("REMOTE_ADDR") in _LOCAL)

    if path in ("/", "/index.html") and method == "GET":
        return _file(os.path.join(ROOT, "index.html"))
    if path.startswith("/static/") and method == "GET":
        parts = path[len("/static/"):].split("/")
        full = os.path.join(STATIC, *parts)
        if not all(_SAFE.match(p) and not p.startswith(".") for p in parts) or not os.path.isfile(full):
            raise HttpError(404, "Not found.")
        return _file(full)
    if not path.startswith("/api/"):
        raise HttpError(404, "Not found.")
    post = method == "POST"

    if path == "/api/health":
        db_error, counts = "", {}
        try:
            counts = _store(cfg).counts() if trusted else {}
        except Exception as err:                       # a broken database must not take the whole app down
            db_error = "%s: %s" % (type(err).__name__, err)
        provider, model, key_present = ai.describe(cfg)
        ai_ready = key_present and trusted
        return _json(200, {
            "ok": True, "version": VERSION, "python": sys.version.split()[0], "login_required": need_login, "logged_in": logged_in,
            "storage": "server" if trusted and not db_error else "browser", "db_error": db_error, "db_counts": counts,
            "storage_reason": "" if trusted else "Set APP_PASSWORD on the server to use the shared database.",
            "ai_ready": ai_ready, "model": model, "ai_provider": provider,
            "ai_reason": "" if ai_ready else (("No %s API key is configured on the server." % ("Gemini" if provider == "gemini" else "Anthropic")) if trusted
                                              else "Set APP_PASSWORD on the server to enable AI."),
            "max_images": cfg["MAX_IMAGES"], "max_body_mb": cfg["MAX_BODY_MB"], "config_file_found": bool(cfg["_file"])})
    if path == "/api/login":
        if not post:
            raise HttpError(405, "Use POST.")
        data = _read_json(environ, cfg)
        if not auth.password_ok(cfg, data.get("password")):
            time.sleep(1.0)
            raise HttpError(401, "Wrong password.")
        return _json(200, {"ok": True}, [("Set-Cookie", auth.set_cookie(auth.new_token(cfg), secure))])
    if path == "/api/logout":
        return _json(200, {"ok": True}, [("Set-Cookie", auth.clear_cookie())])
    if need_login and not logged_in:
        raise HttpError(401, "Please sign in.")

    if path == "/api/seed" and method == "GET":
        return _file(db.SEED)
    if path == "/api/catalogue" and method == "GET":
        return _json(200, dict(catalogue(), ifc_schemas=list(SCHEMAS)))
    try:
        if path == "/api/ai-check":
            if not post:
                raise HttpError(405, "Use POST.")
            if not trusted:
                raise HttpError(403, "AI is off until APP_PASSWORD is set on the server.")
            try:
                return _json(200, ai.check_model(cfg))
            except ai.AiError as err:
                raise HttpError(err.status, str(err))
        if path in ("/api/preview", "/api/export", "/api/convert", "/api/compose"):
            if not post:
                raise HttpError(405, "Use POST.")
            data = _read_json(environ, cfg)
            if path == "/api/preview":
                return _json(200, service.preview(data.get("scene")))
            if path == "/api/export":
                text, filename = service.export(data.get("scene"), str(data.get("schema") or "IFC2X3"))
                return _download(text, filename, "application/x-step")
            if path == "/api/convert":
                return _json(200, service.convert(data))
            if not trusted:
                raise HttpError(403, "AI is off until APP_PASSWORD is set on the server.")
            try:                                      # what can be refused at once is refused with a proper status
                provider, _, key_present = ai.describe(cfg)
                if not key_present:
                    raise ai.AiError("No %s API key is configured on the server." % ("Gemini" if provider == "gemini" else "Anthropic"), 503)
                ai.check_input(cfg, data.get("images") or [], data.get("notes") or "")
            except ai.AiError as err:
                raise HttpError(err.status, str(err))
            return _compose_stream(cfg, data)

        m = re.match(r"^/api/(models|library)(?:/(\d+))?(/delete)?$", path)
        if not m:
            raise HttpError(404, "Not found.")
        if not trusted:
            raise HttpError(403, "The shared database is off until APP_PASSWORD is set on the server.")
        kind, item_id, delete = m.group(1), (_id(m.group(2)) if m.group(2) else None), bool(m.group(3))
        store = _store(cfg)
        if kind == "models":
            if delete and post:
                store.delete_model(item_id)
                return _json(200, {"ok": True})
            if post and not delete:
                data = _read_json(environ, cfg)
                new_id = store.save_model(data.get("scene"), item_id if item_id is not None else data.get("id"))
                return _json(200, {"id": new_id})
            if method == "GET" and item_id is None:
                return _json(200, {"models": store.list_models(q("q"))})
            if method == "GET":
                return _json(200, store.get_model(item_id))
        else:
            if delete and post:
                store.delete_library(item_id)
                return _json(200, {"ok": True})
            if post and not delete:
                data = _read_json(environ, cfg)
                new_id = store.save_library(data, item_id if item_id is not None else data.get("id"))
                return _json(200, {"id": new_id})
            if method == "GET" and item_id is None:
                return _json(200, {"items": store.list_library(q("q"))})
            if method == "GET":
                return _json(200, store.get_library(item_id))
        raise HttpError(405, "Method not allowed.")
    except SceneError as err:
        raise HttpError(400, str(err))
    except db.NotFound as err:
        raise HttpError(404, str(err))


def application(environ, start_response):
    try:
        cfg = config.load()
        status, headers, body = handle(environ, cfg)
    except HttpError as err:
        status, headers, body = _json(err.status, {"error": str(err)})
    except Exception:                                    # never leak a traceback to the browser
        traceback.print_exc(file=environ.get("wsgi.errors") or sys.stderr)
        status, headers, body = _json(500, {"error": "The server hit an unexpected error. Check the host's error log."})
    headers += [("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "same-origin")]
    start_response(status, headers)
    return [body] if isinstance(body, bytes) else body
