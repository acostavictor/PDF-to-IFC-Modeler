"""Shared parameter handling for the structure templates."""
import re

SOURCES = ("dimensioned", "derived", "scaled", "assumed", "example default")


class ParamError(ValueError):
    fit = False        # True when the values are valid on their own but do not fit together


def P(key, label, default, unit="", group="General", hint="", type_="number", columns=None):
    d = {"key": key, "label": label, "default": default, "unit": unit, "group": group, "hint": hint,
         "type": type_}
    if columns:
        d["columns"] = columns
    return d


def _num(x, key):
    if isinstance(x, bool):
        raise ParamError("%s: expected a number" % key)
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return float(str(x).strip().replace(",", ""))
    except ValueError:
        raise ParamError("%s: '%s' is not a number" % (key, x))


def _split(s):
    return [t for t in re.split(r"[,\s;]+", s.strip()) if t]


def coerce(spec, value):
    key, kind = spec["key"], spec["type"]
    if kind == "number":
        return _num(value, key)
    if kind == "text":
        return str(value)
    if kind == "list":
        if isinstance(value, str):
            value = _split(value)
        if not isinstance(value, (list, tuple)) or not value:
            raise ParamError("%s: expected a list of numbers" % key)
        return [_num(v, key) for v in value]
    if kind == "table":
        cols = spec["columns"]
        if isinstance(value, str):
            value = [[c.strip() for c in line.split(",")] for line in value.splitlines() if line.strip()]
        if not isinstance(value, (list, tuple)) or not value:
            raise ParamError("%s: expected a table with %d columns" % (key, len(cols)))
        rows = []
        for row in value:
            if not isinstance(row, (list, tuple)) or len(row) != len(cols):
                raise ParamError("%s: each row needs %d values (%s)" % (
                    key, len(cols), ", ".join(c["name"] for c in cols)))
            rows.append([str(c).strip() if col["type"] == "text" else _num(c, key)
                         for c, col in zip(row, cols)])
        return rows
    raise ParamError("%s: unknown parameter type" % key)


def resolve(specs, incoming):
    """Merge user/AI values over the template defaults.

    incoming maps key -> raw value, or -> {"value": ..., "source": ..., "note": ...}.
    Returns (values, provenance); provenance[key] = {"source": ..., "note": ...}.
    """
    incoming = incoming or {}
    values, prov = {}, {}
    for spec in specs:
        key = spec["key"]
        raw = incoming.get(key)
        source, note = None, ""
        if isinstance(raw, dict) and "value" in raw:
            source, note, raw = raw.get("source"), raw.get("note") or "", raw.get("value")
        if raw is None or raw == "" or raw == []:
            values[key] = coerce(spec, spec["default"])
            prov[key] = {"source": "example default", "note": ""}
        else:
            values[key] = coerce(spec, raw)
            prov[key] = {"source": source if source in SOURCES else "assumed", "note": str(note)[:300]}
    return values, prov


def provenance_props(specs, values, prov):
    """One property per parameter: value, unit and where it came from."""
    out = {}
    for spec in specs:
        key = spec["key"]
        v = values[key]
        if spec["type"] == "number":
            txt = "%g %s" % (v, spec["unit"])
        elif spec["type"] == "list":
            txt = ", ".join("%g" % x for x in v) + " " + spec["unit"]
        elif spec["type"] == "table":
            txt = "; ".join("/".join(("%g" % c) if isinstance(c, float) else c for c in row) for row in v)
        else:
            txt = str(v)
        txt = "%s [%s]" % (txt.strip(), prov[key]["source"])
        if prov[key]["note"]:
            txt += " " + prov[key]["note"]
        out[spec["label"][:60]] = txt
    return out


def require(cond, message):
    if not cond:
        err = ParamError(message)
        err.fit = True
        raise err
