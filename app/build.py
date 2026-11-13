"""Turn a reviewed parameter set into a downloadable file. Used by the server and by the browser preview."""
import re
import time

from .templates import TEMPLATES, EXTRA_EXPORTS
from .templates.base import ParamError


class BuildError(Exception):
    pass


def slug(text, fallback):
    s = re.sub(r"[^A-Za-z0-9]+", "_", str(text or "")).strip("_")[:60]
    return s or fallback


def clean_meta(meta):
    meta = meta if isinstance(meta, dict) else {}
    return {k: str(meta.get(k) or "")[:200] for k in ("project_name", "facility", "site", "author", "source")}


def generate(template_id, fmt, params, meta):
    """Return (text, filename, content_type). Raises BuildError with a message a person can act on."""
    t = TEMPLATES.get(str(template_id or ""))
    if t is None:
        raise BuildError("Unknown structure type.")
    fmt = str(fmt or "ifc")
    meta = clean_meta(meta)
    params = params if isinstance(params, dict) else {}
    base = slug(meta["project_name"], t.ID)
    try:
        if fmt == "ifc":
            meta["filename"] = base + ".ifc"
            return t.build(params, meta), base + ".ifc", "application/x-step"
        exports = EXTRA_EXPORTS.get(t.ID, {})
        if fmt in exports:
            meta["date"] = time.strftime("%d-%b-%y")
            text, _stats = exports[fmt][1](params, meta)
            return text, "%s.%s" % (base, fmt), "text/plain; charset=utf-8"
    except ParamError as err:
        examples = [spec["key"] for spec in t.PARAMS if params.get(spec["key"]) in (None, "") or (
            isinstance(params[spec["key"]], dict) and params[spec["key"]].get("source") == "example default")]
        hint = ""
        if err.fit and examples:
            hint = " Some inputs are still example values; they may not fit the dimensions you changed."
        raise BuildError(str(err) + "." + hint)
    except (ValueError, ZeroDivisionError, IndexError, KeyError) as err:
        raise BuildError("These values do not make a buildable model (%s). Check the inputs." % err)
    raise BuildError("Unknown output format.")
