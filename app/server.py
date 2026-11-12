"""WSGI application using only the standard library, so it runs as plain CGI on shared hosting."""
import json
import mimetypes
import os
import re
import sys
import time
import traceback

from . import auth, config, extract
from .templates import TEMPLATES, EXTRA_EXPORTS, catalogue
from .templates.base import ParamError

ROOT = config.ROOT
STATIC = os.path.join(ROOT, "static")
VERSION = "1.0.0"
_SAFE = re.compile(r"^[A-Za-z0-9_.-]+$")


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


def _file(path, download=None):
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


def _slug(text, fallback):
    s = re.sub(r"[^A-Za-z0-9]+", "_", str(text or "")).strip("_")[:60]
    return s or fallback


def _template(data):
    t = TEMPLATES.get(str(data.get("template") or ""))
    if t is None:
        raise HttpError(400, "Unknown structure type.")
    return t


def _meta(data):
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    return {k: str(meta.get(k) or "")[:200] for k in ("project_name", "facility", "site", "author", "source")}


def handle(environ, cfg):
    method = environ.get("REQUEST_METHOD", "GET").upper()
    path = environ.get("PATH_INFO") or "/"
    secure = environ.get("wsgi.url_scheme") == "https" or environ.get("HTTPS", "").lower() in ("on", "1")
    need_login = bool(cfg["APP_PASSWORD"])
    logged_in = need_login and auth.token_ok(cfg, auth.cookie_from(environ))

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

    if path == "/api/health":
        return _json(200, {"ok": True, "version": VERSION, "python": sys.version.split()[0],
                           "login_required": need_login, "logged_in": logged_in,
                           "ai_ready": bool(cfg["ANTHROPIC_API_KEY"]) and need_login,
                           "ai_reason": "" if (cfg["ANTHROPIC_API_KEY"] and need_login) else (
                               "Set APP_PASSWORD on the server to enable AI reading." if cfg["ANTHROPIC_API_KEY"]
                               else "No Anthropic API key is configured on the server."),
                           "model": cfg["ANTHROPIC_MODEL"], "max_images": cfg["MAX_IMAGES"],
                           "max_body_mb": cfg["MAX_BODY_MB"], "config_file_found": bool(cfg["_file"])})
    if path == "/api/login":
        if method != "POST":
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
    if path == "/api/templates" and method == "GET":
        return _json(200, {"templates": catalogue()})
    if path not in ("/api/extract", "/api/generate"):
        raise HttpError(404, "Not found.")
    if method != "POST":
        raise HttpError(405, "Use POST.")
    data = _read_json(environ, cfg)

    if path == "/api/extract":
        if not need_login:
            raise HttpError(403, "AI reading is off until APP_PASSWORD is set on the server.")
        t = _template(data)
        try:
            return _json(200, extract.extract(cfg, t, data.get("images"), data.get("notes") or ""))
        except extract.ExtractError as err:
            raise HttpError(err.status, str(err))
    if path == "/api/generate":
        t = _template(data)
        fmt = str(data.get("format") or "ifc")
        meta = _meta(data)
        base = _slug(meta["project_name"], t.ID)
        params = data.get("params") if isinstance(data.get("params"), dict) else {}
        try:
            if fmt == "ifc":
                meta["filename"] = base + ".ifc"
                return _download(t.build(params, meta), base + ".ifc", "application/x-step")
            exports = EXTRA_EXPORTS.get(t.ID, {})
            if fmt in exports:
                meta["date"] = time.strftime("%d-%b-%y")
                text, _stats = exports[fmt][1](params, meta)
                return _download(text, "%s.%s" % (base, fmt), "text/plain; charset=utf-8")
        except ParamError as err:
            hint = ""
            examples = [spec["key"] for spec in t.PARAMS if params.get(spec["key"]) in (None, "") or (
                isinstance(params[spec["key"]], dict) and params[spec["key"]].get("source") == "example default")]
            if err.fit and examples:
                hint = " Some inputs are still example values; they may not fit the dimensions you changed."
            raise HttpError(400, str(err) + "." + hint)
        except (ValueError, ZeroDivisionError, IndexError, KeyError) as err:
            raise HttpError(400, "These values do not make a buildable model (%s). Check the highlighted inputs." % err)
        raise HttpError(400, "Unknown output format.")
    raise HttpError(404, "Not found.")


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
    return [body]
