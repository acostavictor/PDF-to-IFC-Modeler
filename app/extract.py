"""Ask Claude to read drawing images and propose template parameters.

Uses only urllib, so nothing needs installing on the host. The model is asked to call one tool,
record_dimensions, whose schema is generated from the template's parameter list.
"""
import json
import socket

try:
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError, URLError
except ImportError:                                   # pragma: no cover
    raise

TOOL = "record_dimensions"
AI_SOURCES = ("dimensioned", "derived", "scaled", "not_found")
MEDIA = ("image/jpeg", "image/png")


class ExtractError(Exception):
    def __init__(self, message, status=502):
        Exception.__init__(self, message)
        self.status = status


def _value_schema(spec):
    kind = spec["type"]
    if kind == "number":
        return {"type": ["number", "null"]}
    if kind == "text":
        return {"type": ["string", "null"]}
    if kind == "list":
        return {"type": ["array", "null"], "items": {"type": "number"}}
    cols = ", ".join("%s (%s)" % (c["name"], c["type"]) for c in spec["columns"])
    return {"type": ["array", "null"], "description": "Rows of [%s]." % cols,
            "items": {"type": "array", "items": {"type": ["number", "string"]}}}


def tool_schema(template):
    props = {}
    for spec in template.PARAMS:
        desc = "%s. Unit: %s. %s" % (spec["label"], spec["unit"] or "none", spec["hint"])
        props[spec["key"]] = {
            "type": "object", "description": desc.strip(),
            "properties": {
                "value": _value_schema(spec),
                "source": {"type": "string", "enum": list(AI_SOURCES)},
                "sheet": {"type": "string", "description": "Page and view where the value was read."},
                "note": {"type": "string", "description": "Short note: the dimension as written, or how it was derived."},
            },
            "required": ["value", "source"],
        }
    props["general_notes"] = {"type": "string",
                              "description": "Conflicts between sheets, illegible areas, and anything about the "
                                             "drawings that does not fit this structure type."}
    return {"name": TOOL,
            "description": "Record every parameter of the structure that the drawings support, each with its source.",
            "input_schema": {"type": "object", "properties": props, "required": ["general_notes"]}}


def system_prompt(template):
    unit = "decimal feet" if template.UNIT == "ft" else "millimetres"
    return (
        "You read scanned engineering drawings and record dimensions for a parametric 3D model of a %s.\n"
        "%s\n\n"
        "You are given whole-sheet overviews and overlapping high-resolution tiles of the same sheets. Use the "
        "overviews to find the views (%s) and the tiles to read the small text.\n\n"
        "Rules:\n"
        "1. Give every length in %s. Convert feet-inches-fractions (for example 47'-9 5/8\") exactly. Where a "
        "drawing gives both imperial and bracketed metric values, use the one that needs no conversion.\n"
        "2. source = dimensioned when the value is written on a sheet; derived when you computed it from written "
        "dimensions (show the arithmetic in the note); scaled when you estimated it from the linework because no "
        "dimension is given; not_found, with value null, when you cannot read or find it.\n"
        "3. Never guess. A null with not_found is better than a plausible number. The user reviews every value "
        "against the drawing before a model is built.\n"
        "4. Prefer revision-clouded or later-dated values when sheets disagree, and report the conflict in "
        "general_notes.\n"
        "5. Call the %s tool exactly once with everything you found. Do not answer in prose."
    ) % (template.TITLE.lower(), template.SUMMARY, template.LOOK_FOR, unit, TOOL)


def build_payload(cfg, template, images, user_notes=""):
    content = []
    for img in images:
        content.append({"type": "text", "text": str(img.get("label") or "Drawing image")[:200]})
        content.append({"type": "image", "source": {"type": "base64", "media_type": img["media_type"], "data": img["data"]}})
    ask = "Read these drawings and call %s. All values in %s." % (TOOL, "decimal feet" if template.UNIT == "ft" else "millimetres")
    if user_notes:
        ask += "\n\nNotes from the user about these drawings:\n" + str(user_notes)[:2000]
    content.append({"type": "text", "text": ask})
    return {"model": cfg["ANTHROPIC_MODEL"], "max_tokens": cfg["MAX_OUTPUT_TOKENS"], "system": system_prompt(template),
            "tools": [tool_schema(template)], "tool_choice": {"type": "auto"},
            "messages": [{"role": "user", "content": content}]}


def check_images(cfg, images):
    if not isinstance(images, list) or not images:
        raise ExtractError("No drawing images were sent.", 400)
    if len(images) > cfg["MAX_IMAGES"]:
        raise ExtractError("Too many images (%d). The limit is %d; choose fewer pages or a lower detail level."
                           % (len(images), cfg["MAX_IMAGES"]), 400)
    for img in images:
        if not isinstance(img, dict) or img.get("media_type") not in MEDIA or not isinstance(img.get("data"), str):
            raise ExtractError("Each image needs a media_type of image/jpeg or image/png and base64 data.", 400)
        if len(img["data"]) > 10 * 1024 * 1024:
            raise ExtractError("One image is over the 10 MB API limit; use a lower detail level.", 400)


def call_api(cfg, payload, opener=urlopen):
    if not cfg.get("ANTHROPIC_API_KEY"):
        raise ExtractError("No Anthropic API key is configured on the server.", 503)
    req = Request(cfg["ANTHROPIC_URL"], data=json.dumps(payload).encode("utf-8"), method="POST",
                  headers={"content-type": "application/json", "x-api-key": cfg["ANTHROPIC_API_KEY"],
                           "anthropic-version": cfg["ANTHROPIC_VERSION"]})
    try:
        resp = opener(req, timeout=cfg["REQUEST_TIMEOUT"])
        return json.loads(resp.read().decode("utf-8"))
    except HTTPError as err:
        detail = ""
        try:
            detail = json.loads(err.read().decode("utf-8")).get("error", {}).get("message", "")
        except Exception:
            pass
        raise ExtractError("The Claude API returned an error (%d). %s" % (err.code, detail), 502)
    except socket.timeout:
        raise ExtractError("The Claude API did not answer within %d seconds. Try fewer pages or a lower detail level."
                           % cfg["REQUEST_TIMEOUT"], 504)
    except URLError as err:
        if isinstance(getattr(err, "reason", None), socket.timeout):
            raise ExtractError("The Claude API timed out. Try fewer pages or a lower detail level.", 504)
        raise ExtractError("Could not reach the Claude API from this server: %s" % err.reason, 502)


def _json_from_text(text):
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except ValueError:
                        break
        start = text.find("{", start + 1)
    return None


def parse_response(template, response):
    """Return ({key: {value, source, note}}, general_notes) from a Messages API response."""
    if response.get("stop_reason") == "max_tokens":
        raise ExtractError("The reading was cut off before it finished. Raise MAX_OUTPUT_TOKENS or send fewer pages.", 502)
    data = None
    texts = []
    for block in response.get("content") or []:
        if block.get("type") == "tool_use" and block.get("name") == TOOL and isinstance(block.get("input"), dict):
            data = block["input"]
            break
        if block.get("type") == "text":
            texts.append(block.get("text") or "")
    if data is None:
        data = _json_from_text("\n".join(texts))
    if not isinstance(data, dict):
        raise ExtractError("The model did not return structured values. Its reply began: %s"
                           % ("\n".join(texts)[:200] or "(empty)"), 502)
    out = {}
    for spec in template.PARAMS:
        item = data.get(spec["key"])
        if not isinstance(item, dict):
            continue
        value, source = item.get("value"), item.get("source")
        if value is None or value == [] or source == "not_found":
            continue
        note = " ".join(str(item.get(k)).strip() for k in ("sheet", "note") if item.get(k))
        out[spec["key"]] = {"value": value, "source": source if source in ("dimensioned", "derived", "scaled") else "scaled",
                            "note": note[:300]}
    return out, str(data.get("general_notes") or "")


def extract(cfg, template, images, user_notes="", opener=urlopen):
    check_images(cfg, images)
    response = call_api(cfg, build_payload(cfg, template, images, user_notes), opener)
    params, notes = parse_response(template, response)
    return {"params": params, "general_notes": notes, "model": response.get("model") or cfg["ANTHROPIC_MODEL"],
            "usage": response.get("usage") or {}, "found": len(params), "total": len(template.PARAMS)}
