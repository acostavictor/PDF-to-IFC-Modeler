#!/usr/bin/env python3
"""Set up and check a server for PDF to IFC Modeler. Standard library only.

    python3 tools/setup_server.py             ask for the API key and password if needed, then check everything
    python3 tools/setup_server.py --check     check only; change nothing
    python3 tools/setup_server.py --ai-test   also send one small real request to Claude (billed to your key)

Run it on the machine that will serve the app: over SSH or in the cPanel Terminal on a web host, or in a terminal
on your own computer. The API key and password are typed here and written to a private file on that machine; they
are never put in the repository or shown on screen.
"""
from __future__ import print_function

import argparse
import getpass
import json
import os
import secrets
import shutil
import stat
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

OK, WARN, FAIL = "ok", "warn", "FAIL"
SAMPLE = ("A small timber fishing pier in feet. Deck 60 ft long and 12 ft wide, top of deck at elevation +10. "
          "Four pile bents at 20 ft centres, each with two 12 in round timber piles 8 ft apart, pile tips at -25, "
          "and a 12 in by 12 in timber cap beam under the deck.")


class Report(object):
    def __init__(self, out=sys.stdout):
        self.rows, self.out = [], out

    def add(self, level, title, detail="", fix=""):
        self.rows.append((level, title, detail, fix))
        mark = {OK: "  ok  ", WARN: " note ", FAIL: " FAIL "}[level]
        print("[%s] %s%s" % (mark, title, (": " + detail) if detail else ""), file=self.out)
        if fix and level != OK:
            print("         -> " + fix, file=self.out)

    def failed(self):
        return [r for r in self.rows if r[0] == FAIL]


def config_target():
    """The file this script writes: the one the app already reads if there is one, otherwise $PDF2IFC_CONFIG if set,
    otherwise the private folder in the home directory."""
    from app import config
    try:
        found = config._file_values()[1]
    except Exception:
        found = None
    for path in (os.environ.get("PDF2IFC_CONFIG"), os.path.join(os.path.expanduser("~"), ".pdf2ifc", "config.json")):
        if path and os.path.isfile(path):
            return path                                       # even if broken, so the problem is reported, not hidden
    return found or os.environ.get("PDF2IFC_CONFIG") or os.path.join(os.path.expanduser("~"), ".pdf2ifc", "config.json")


def in_web_folder(path):
    parts = os.path.abspath(path).replace("\\", "/").split("/")
    return any(p in ("public_html", "www", "htdocs", "httpdocs") for p in parts)


def read_config(path):
    if not os.path.isfile(path):
        return {}
    with open(path, "r") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("it must hold a JSON object")
    return data


def write_config(path, data):
    """Write the config so that only the account owner can read it."""
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
        if os.name != "nt":
            os.chmod(folder, 0o700)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)
    if os.name != "nt":
        os.chmod(path, 0o600)


def ask_settings(path, existing, ask=input, ask_secret=getpass.getpass, out=sys.stdout):
    """Ask for whatever is missing. Returns (settings, generated_password or None)."""
    data, generated = dict(existing), None
    placeholder = ("", "paste-your-key-here", "choose-a-long-password")
    if (data.get("ANTHROPIC_API_KEY") in placeholder or data.get("ANTHROPIC_API_KEY") is None) and not os.environ.get("ANTHROPIC_API_KEY"):
        print("\nAnthropic API key. Create one at https://console.anthropic.com/ (API keys). What you paste is not shown.", file=out)
        key = ask_secret("  API key (leave empty to skip AI for now): ").strip()
        if key:
            data["ANTHROPIC_API_KEY"] = key
            if not key.startswith("sk-ant-"):
                print("  Note: Anthropic keys normally start with sk-ant-. Kept as typed; the connection check will tell.", file=out)
        else:
            data.pop("ANTHROPIC_API_KEY", None)
    if (data.get("APP_PASSWORD") in placeholder or data.get("APP_PASSWORD") is None) and not os.environ.get("APP_PASSWORD"):
        print("\nPassword for signing in to the app. On a public server the database and AI stay off without one.", file=out)
        while True:
            first = ask_secret("  Password (leave empty and one is made for you): ")
            if not first:
                generated = secrets.token_urlsafe(18)
                data["APP_PASSWORD"] = generated
                break
            if len(first) < 10:
                print("  Use at least 10 characters.", file=out)
                continue
            if ask_secret("  Type it again: ") != first:
                print("  The two did not match.", file=out)
                continue
            data["APP_PASSWORD"] = first
            break
    return data, generated


def check_python(rep):
    v = sys.version_info
    if v < (3, 6):
        rep.add(FAIL, "Python version", "%d.%d is too old" % (v[0], v[1]), "Ask the host which Python 3 (3.6 or newer) to use and run this script with it.")
    else:
        rep.add(OK, "Python version", "%d.%d.%d at %s" % (v[0], v[1], v[2], sys.executable))
    try:
        import sqlite3
        rep.add(OK, "SQLite", sqlite3.sqlite_version)
    except Exception as err:                                  # pragma: no cover - depends on the host's Python build
        rep.add(FAIL, "SQLite", str(err), "This Python has no sqlite3 module, so models cannot be saved on the server. Ask the host for one that has it.")
    try:
        import ssl
        rep.add(OK, "HTTPS support", ssl.OPENSSL_VERSION)
    except Exception as err:                                  # pragma: no cover
        rep.add(FAIL, "HTTPS support", str(err), "This Python cannot make HTTPS calls, so the Claude API cannot be reached.")


def check_files(rep, fix):
    cgi = os.path.join(ROOT, "index.cgi")
    if not os.path.isfile(cgi):
        rep.add(FAIL, "index.cgi", "missing", "Upload the whole repository, including index.cgi.")
        return
    with open(cgi, "rb") as fh:
        raw = fh.read()
    if b"\r\n" in raw:
        if fix:
            with open(cgi, "wb") as fh:
                fh.write(raw.replace(b"\r\n", b"\n"))
            rep.add(OK, "index.cgi line endings", "converted from Windows to Unix")
        else:
            rep.add(FAIL, "index.cgi line endings", "Windows line endings", "Run this script without --check to convert them.")
    first = raw.split(b"\n", 1)[0].decode("ascii", "replace").strip()
    interp = first[2:].split() if first.startswith("#!") else []
    if os.name != "nt":
        found = interp and (shutil.which(interp[1]) if os.path.basename(interp[0]) == "env" and len(interp) > 1 else (interp[0] if os.path.exists(interp[0]) else None))
        if found:
            rep.add(OK, "index.cgi interpreter", "%s -> %s" % (first, found))
        else:
            rep.add(FAIL, "index.cgi interpreter", "'%s' was not found" % first, "Put '#!%s' on the first line of index.cgi." % sys.executable)
        todo = []
        for path, want in [(cgi, 0o755)] + [(d, 0o755) for d in (ROOT, os.path.join(ROOT, "app"), os.path.join(ROOT, "static"))]:
            mode = stat.S_IMODE(os.stat(path).st_mode)
            bad = (mode & 0o022) or (path == cgi and (mode & 0o755) != 0o755)
            if bad:
                todo.append((path, want, mode))
        if todo and fix:
            for path, want, _mode in todo:
                os.chmod(path, want)
            rep.add(OK, "Permissions", "set to 755 on " + ", ".join(os.path.relpath(p, ROOT) or "." for p, _w, _m in todo))
        elif todo:
            rep.add(FAIL, "Permissions", ", ".join("%s is %o" % (os.path.relpath(p, ROOT), m) for p, _w, m in todo),
                    "index.cgi must be 755 and folders must not be writable by others. Run this script without --check.")
        else:
            rep.add(OK, "Permissions", "index.cgi is executable; folders are not writable by others")
    if os.path.isfile(os.path.join(ROOT, ".htaccess")):
        rep.add(OK, ".htaccess", "present")
    else:
        rep.add(WARN, ".htaccess", "missing", "It is a hidden file and is easy to miss when uploading. On Apache hosts it turns on CGI and keeps the source private.")
    for name in ("config.local.json", "config.json"):
        if os.path.isfile(os.path.join(ROOT, name)) and in_web_folder(ROOT):
            rep.add(WARN, name, "a config file sits inside the web folder", "Move it to %s. .htaccess blocks it, but outside the web folder is safer." % config_target())


def check_config(rep):
    from app import config
    try:
        cfg = config.load()
    except Exception as err:
        rep.add(FAIL, "Configuration file", str(err), "Fix or delete the file and run this script again.")
        return None
    where = cfg["_file"] or "(none; using environment variables and defaults)"
    rep.add(OK, "Configuration file", where)
    if cfg["_file"] and os.name != "nt" and stat.S_IMODE(os.stat(cfg["_file"]).st_mode) & 0o077:
        rep.add(WARN, "Configuration file privacy", "others on this machine can read it", "chmod 600 %s" % cfg["_file"])
    if cfg["APP_PASSWORD"]:
        rep.add(OK, "App password", "set")
    else:
        rep.add(WARN, "App password", "not set", "Fine on your own computer. On a public server the database and AI stay off until it is set.")
    from app import ai
    _provider, _, _ = ai.describe(cfg)
    _label = "Gemini API key" if _provider == "gemini" else "Anthropic API key"
    _key = cfg["GEMINI_API_KEY"] if _provider == "gemini" else cfg["ANTHROPIC_API_KEY"]
    if _key:
        rep.add(OK, _label, "set (ends in ...%s)" % _key[-4:])
    else:
        rep.add(WARN, _label, "not set", "The app works, but Build model with AI stays off.")
    return cfg


def check_database(rep, cfg):
    from app import db
    path = cfg["DB_PATH"] or db.default_path()
    try:
        counts = db.Store(path).counts()
    except Exception as err:
        rep.add(FAIL, "Database", "%s: %s" % (type(err).__name__, err), "The app must be able to create and write %s." % path)
        return
    rep.add(OK, "Database", "%s (%d models, %d library items)" % (path, counts["models"], counts["library"]))
    if in_web_folder(path):
        rep.add(WARN, "Database location", "inside the web folder", "Set DB_PATH to a folder outside public_html.")


def check_web_entry(rep):
    """Run index.cgi the way the web server would, as a visitor from outside."""
    env = dict(os.environ, REQUEST_METHOD="GET", PATH_INFO="/api/health", SCRIPT_NAME="/index.cgi", SERVER_NAME="check",
               SERVER_PORT="443", SERVER_PROTOCOL="HTTP/1.1", REMOTE_ADDR="203.0.113.1", HTTPS="on")
    cgi = os.path.join(ROOT, "index.cgi")
    cmd = [sys.executable, cgi] if os.name == "nt" else [cgi]
    try:
        proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=ROOT)
        out, err = proc.communicate(timeout=60)
        body = out.split(b"\r\n\r\n", 1)[1] if b"\r\n\r\n" in out else out.split(b"\n\n", 1)[-1]
        health = json.loads(body.decode("utf-8"))
    except Exception as err:
        rep.add(FAIL, "Web entry point (index.cgi)", "%s: %s" % (type(err).__name__, err), "Run ./index.cgi by hand to see the error.")
        return
    if health.get("ok"):
        rep.add(OK, "Web entry point (index.cgi)", "answers as version %s; sign-in %s" % (health.get("version"), "required" if health.get("login_required") else "not required"))
    else:
        rep.add(FAIL, "Web entry point (index.cgi)", "unexpected reply", str(health)[:200])


def check_api(rep, cfg, opener=None):
    from app import ai
    provider, _, key_present = ai.describe(cfg)
    name = "Gemini" if provider == "gemini" else "Claude"
    if not key_present:
        return False
    try:
        info = ai.check_model(cfg, opener) if opener else ai.check_model(cfg)
    except ai.AiError as err:
        rep.add(FAIL, "%s API connection" % name, str(err), "Check the key. If the API cannot be reached at all, ask the host whether "
                "outbound HTTPS is allowed.")
        return False
    rep.add(OK, "%s API connection" % name, "%s answered; the key is accepted" % (info["display_name"] or info["model"]))
    for text in info["warnings"]:
        rep.add(WARN, "Model", text)
    return True


def ai_test(rep, cfg, opener=None, out=sys.stdout):
    from app import ai
    start = time.time()
    try:
        res = ai.compose(cfg, [], SAMPLE, "ft", opener) if opener else ai.compose(cfg, [], SAMPLE, "ft")
    except ai.AiError as err:
        rep.add(FAIL, "AI test run", str(err))
        return None
    use = res.get("usage") or {}
    rep.add(OK, "AI test run", "%d components, %d pieces in %.0f s (%s input and %s output tokens)" % (
        len(res["scene"]["components"]), res["pieces"], time.time() - start, use.get("input_tokens", "?"), use.get("output_tokens", "?")))
    for comp in res["scene"]["components"]:
        print("           - %s (%s, sizes %s)" % (comp["name"], comp["type"], comp["source"]), file=out)
    if res["rejected"]:
        rep.add(WARN, "AI test run", "%d component(s) came back unusable: %s" % (len(res["rejected"]), "; ".join(res["rejected"])[:300]))
    if res["pieces"] < 5:
        rep.add(WARN, "AI test run", "fewer pieces than the description calls for; look at the result in the app before relying on it")
    return res


def main(argv=None, ask=input, ask_secret=getpass.getpass, out=sys.stdout, opener=None):
    parser = argparse.ArgumentParser(description="Set up and check a server for PDF to IFC Modeler.")
    parser.add_argument("--check", action="store_true", help="check only; change nothing")
    parser.add_argument("--ai-test", action="store_true", help="send one small real request to the AI model (billed on Claude, free on the Gemini free tier)")
    parser.add_argument("--yes", action="store_true", help="do not ask before the billed test")
    args = parser.parse_args(argv)
    rep = Report(out)
    print("PDF to IFC Modeler: server set-up\n" + "=" * 34, file=out)

    if not args.check:
        target = config_target()
        try:
            existing = read_config(target)
        except Exception as err:
            print("The configuration file %s cannot be read (%s). Fix or delete it, then run this again." % (target, err), file=out)
            return 2
        data, generated = ask_settings(target, existing, ask, ask_secret, out)
        if data != existing:
            write_config(target, data)
            print("\nSaved to %s (readable only by this account)." % target, file=out)
        if generated:
            print("\nYour sign-in password, shown this once. Store it in your password manager:\n\n    %s\n" % generated, file=out)
        print("", file=out)

    check_python(rep)
    check_files(rep, fix=not args.check)
    cfg = check_config(rep)
    if cfg:
        check_database(rep, cfg)
        check_web_entry(rep)
        reachable = check_api(rep, cfg, opener)
        if args.ai_test and reachable:
            from app import ai as _ai
            _name = "Gemini" if _ai.describe(cfg)[0] == "gemini" else "Claude"
            go = args.yes or ask("\nSend one small test request to %s? It is billed to your key on Claude, and free on the Gemini free tier. [y/N] " % _name).strip().lower() in ("y", "yes")
            if go:
                print("Asking %s to build a small pier from a description. This can take a minute." % _name, file=out)
                ai_test(rep, cfg, opener, out)
        elif args.ai_test:
            rep.add(WARN, "AI test run", "skipped because the connection check did not pass")

    failed = rep.failed()
    print("\n" + "=" * 34, file=out)
    if failed:
        print("%d problem(s) to fix: %s" % (len(failed), "; ".join(r[1] for r in failed)), file=out)
        return 1
    print("Ready. Open the app's address in a browser%s." % (" and sign in" if cfg and cfg["APP_PASSWORD"] else ""), file=out)
    if cfg and (cfg["ANTHROPIC_API_KEY"] or cfg["GEMINI_API_KEY"]) and not args.ai_test:
        print("To prove a full AI run end to end, run:  python3 tools/setup_server.py --check --ai-test", file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
