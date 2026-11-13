"""Ask an AI model to compose a structure from drawing images, a written description, or both.

Two providers are supported. Anthropic (Claude) is the default and is talked to in its own Messages API form.
Gemini is reached through Google's OpenAI-compatible endpoint, in chat completions form; the same form serves any
other OpenAI-compatible provider by changing the URL, key and model. The model is given the component vocabulary
and asked to call one tool, record_structure. Each component it returns is validated on its own, so one bad
component does not lose the rest. Uses only urllib, so nothing needs installing on the host.
"""
import json
import re
import socket

from urllib.request import Request, urlopen
from urllib.parse import quote
from urllib.error import HTTPError, URLError

from . import scene as scene_mod

TOOL = "record_structure"
MEDIA = ("image/jpeg", "image/png")
AI_SOURCES = ("dimensioned", "derived", "scaled", "assumed")
PROVIDERS = ("anthropic", "gemini")


def _provider(cfg):
    provider = str(cfg.get("AI_PROVIDER") or "anthropic").lower()
    if provider not in PROVIDERS:
        raise AiError("Unknown AI_PROVIDER %r. Use one of: %s." % (provider, ", ".join(PROVIDERS)), 400)
    return provider


def _api_key(cfg, provider):
    key = cfg.get("ANTHROPIC_API_KEY") if provider == "anthropic" else cfg.get("GEMINI_API_KEY")
    if not key:
        raise AiError("No %s API key is configured on the server." % ("Anthropic" if provider == "anthropic" else "Gemini"), 503)
    return key


def _model(cfg):
    provider = _provider(cfg)
    return cfg["GEMINI_MODEL"] if provider == "gemini" else cfg["ANTHROPIC_MODEL"]


def describe(cfg):
    """(provider, model, key_present) for the health page and the set-up script. Never raises."""
    provider = str(cfg.get("AI_PROVIDER") or "anthropic").lower()
    if provider == "gemini":
        return provider, cfg.get("GEMINI_MODEL") or "", bool(cfg.get("GEMINI_API_KEY"))
    return "anthropic", cfg.get("ANTHROPIC_MODEL") or "", bool(cfg.get("ANTHROPIC_API_KEY"))


class AiError(Exception):
    def __init__(self, message, status=502):
        Exception.__init__(self, message)
        self.status = status


def vocabulary():
    lines = []
    for tid, t in scene_mod.TYPES.items():
        lines.append("%s: %s" % (tid, t["summary"]))
        lines.append("  kinds: " + ", ".join(t["kinds"]))
        for spec in t["params"]:
            if spec["type"] == "choice":
                kind = "one of " + "|".join(spec["options"])
            elif spec["type"] == "table":
                kind = "list of [%s]" % ", ".join(c["name"] for c in spec["columns"])
            elif spec["type"] == "text":
                kind = "text"
            else:
                kind = "length" if spec.get("length") else "number"
            lines.append("  params.%s (%s): %s%s" % (spec["key"], kind, spec["label"], (". " + spec["hint"]) if spec["hint"] else ""))
    return "\n".join(lines)


EXAMPLE = {
    "name": "Timber pier", "structure_type": "Pier or jetty", "units": "ft", "datum": "MLLW",
    "description": "120 ft x 16 ft timber pier on 7 bents at 20 ft.",
    "components": [
        {"type": "assembly", "name": "Pile bent", "kind": "pile bent", "at": [0, 0, 0], "array": {"nx": 7, "dx": 20, "ny": 1, "dy": 0},
         "source": "dimensioned", "note": "Sheet S-2 plan: bents at 20'-0\" o.c.", "children": [
             {"type": "beam", "name": "Cap", "kind": "pile cap beam", "material": "timber", "source": "dimensioned",
              "note": "S-3 Section A: 12x12 cap, top EL +9.0", "params": {"path": [[0, 0, 9], [0, 16, 9]], "section": "rectangle", "width": 1, "depth": 1}},
             {"type": "pile", "name": "Piles", "kind": "bearing pile", "material": "timber", "positions": [[0, 2], [0, 8], [0, 14]],
              "source": "scaled", "note": "S-3: 12 in dia; tip EL not given, scaled as -25",
              "params": {"shape": "round", "size": 1, "top_el": 8, "tip_el": -25}}]},
        {"type": "slab", "name": "Deck", "kind": "deck", "material": "timber", "at": [-1, 0, 0], "source": "dimensioned",
         "note": "S-2: 122'-0\" x 16'-0\", 3 in decking on stringers, top EL +10.0", "params": {"length": 122, "width": 16, "top_el": 10, "thickness": 1}}],
    "missing": ["Stringer sizes and spacing: not legible on S-3."],
    "general_notes": "Sheets S-2 and S-3 agree on bent spacing.",
}


def system_prompt():
    return (
        "You turn marine and waterfront engineering drawings, or a written description, into a structured 3D model. "
        "The model is a list of components from a fixed vocabulary. A person will check every component against the "
        "drawings before the model is used, so be accurate and say exactly where each value came from.\n\n"
        "COORDINATES\n"
        "x runs along the structure (stationing), y across it, z is elevation in the drawing's datum. Pick an origin that "
        "makes the numbers simple, such as the start of the structure on its centreline or a face, and say what you chose "
        "in the description. Give every length in one unit (ft, m or mm) and state it in units. Convert feet-inches-fractions "
        "exactly to decimal feet. Angles are degrees, counter-clockwise from +x.\n\n"
        "PLACEMENT AND REPEATS\n"
        "at is [x, y, z] and is added to the component's own coordinates and elevations, so leave z at 0 when the params "
        "already give true elevations. rotate turns the component about its own origin. array {nx, dx, ny, dy} repeats it on "
        "a grid in the parent's x and y; positions is a list of [x, y] offsets used instead of array. Use repeats wherever "
        "the drawing shows a pattern: do not list 40 identical piles one by one. Use an assembly for a unit that repeats as "
        "a whole, such as a pile bent, and put the repeat on the assembly.\n\n"
        "COMPONENT TYPES\n" + vocabulary() + "\n\n"
        "MODELLING GUIDANCE\n"
        "- Piers and wharves: one assembly per typical bent (cap beam plus piles), repeated; then deck slab, edge beams, "
        "fenders and mooring fittings.\n"
        "- Battered piles: batter is horizontal per 1 vertical; batter_dir is the direction the toe moves.\n"
        "- Breakwaters and revetments: one section_sweep per layer (armour, underlayer, core), each drawn as its own "
        "closed outline so layers do not overlap; the path follows the alignment.\n"
        "- Sheet pile and gravity walls: wall for constant thickness, section_sweep for a shaped section.\n"
        "- Floating docks: block with kind pontoon for floats, pile with kind guide pile, beam with kind gangway.\n"
        "- Anything else prismatic: section_sweep, slab with an outline, or block.\n"
        "- Shapes the vocabulary cannot express (curved hulls, complex steelwork) should be left out and listed in missing.\n\n"
        "SOURCES\n"
        "Every component needs a source: dimensioned when its sizes are written on the drawings or stated by the user; "
        "derived when computed from written values (show the arithmetic in the note); scaled when estimated from the "
        "linework because no dimension is given; assumed when you had to choose a value with no basis in the input. "
        "Use the weakest source that applies to any size in the component, and name the uncertain size in the note. "
        "The note should cite the page and view. Never present a guess as dimensioned. If a component cannot be sized at "
        "all, leave it out and describe it in missing.\n\n"
        "OUTPUT\n"
        "Call the %s tool exactly once. Do not answer in prose. Example of the tool input:\n%s"
    ) % (TOOL, json.dumps(EXAMPLE))


def tool_schema():
    comp = {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": list(scene_mod.TYPES)},
            "name": {"type": "string"}, "kind": {"type": "string"}, "material": {"type": "string"},
            "at": {"type": "array", "items": {"type": "number"}}, "rotate": {"type": "number"},
            "array": {"type": "object", "properties": {"nx": {"type": "integer"}, "dx": {"type": "number"},
                                                       "ny": {"type": "integer"}, "dy": {"type": "number"}}},
            "positions": {"type": "array", "items": {"type": "array", "items": {"type": "number"}}},
            "params": {"type": "object", "description": "The params listed for this component type."},
            "children": {"type": "array", "items": {"type": "object"}, "description": "Assembly only: components inside it."},
            "source": {"type": "string", "enum": list(AI_SOURCES)},
            "note": {"type": "string", "description": "Page and view the sizes came from, and anything uncertain."},
        },
        "required": ["type", "name", "source"],
    }
    return {"name": TOOL, "description": "Record the structure as a list of components.",
            "input_schema": {"type": "object", "properties": {
                "name": {"type": "string"}, "structure_type": {"type": "string", "enum": scene_mod.STRUCTURE_TYPES},
                "units": {"type": "string", "enum": ["ft", "m", "mm"]}, "datum": {"type": "string"},
                "description": {"type": "string", "description": "What the structure is and where the origin was placed."},
                "components": {"type": "array", "items": comp},
                "missing": {"type": "array", "items": {"type": "string"},
                            "description": "Parts shown on the drawings that were left out, and why."},
                "general_notes": {"type": "string", "description": "Conflicts between sheets and illegible areas."}},
                "required": ["name", "units", "components"]}}


def _anthropic_payload(cfg, images, notes, units=""):
    content = []
    for img in images:
        content.append({"type": "text", "text": str(img.get("label") or "Drawing image")[:200]})
        content.append({"type": "image", "source": {"type": "base64", "media_type": img["media_type"], "data": img["data"]}})
    ask = "Build the structure model from %s and call %s." % ("these drawings" if images else "this description", TOOL)
    if units in scene_mod.UNITS:
        ask += " Work in %s." % units
    if notes:
        ask += "\n\n%s\n%s" % ("Notes from the user:" if images else "Description from the user:", str(notes)[:6000])
    content.append({"type": "text", "text": ask})
    return {"model": cfg["ANTHROPIC_MODEL"], "max_tokens": cfg["MAX_OUTPUT_TOKENS"], "system": system_prompt(),
            "tools": [tool_schema()], "tool_choice": {"type": "auto"}, "messages": [{"role": "user", "content": content}]}


def _openai_payload(cfg, images, notes, units=""):
    """Same request in OpenAI chat completions form, for Gemini's OpenAI-compatible endpoint.

    The tool schema is already JSON Schema, so it is reused as the function parameters. The system prompt is sent
    as a system message, and each image as a data URL. The tool call is forced, so the reply should carry the
    structure as function arguments; when a model answers in prose instead, the JSON in its text is read back.
    """
    content = []
    for img in images:
        content.append({"type": "text", "text": str(img.get("label") or "Drawing image")[:200]})
        content.append({"type": "image_url", "image_url": {"url": "data:%s;base64,%s" % (img["media_type"], img["data"])}})
    ask = "Build the structure model from %s and call %s." % ("these drawings" if images else "this description", TOOL)
    if units in scene_mod.UNITS:
        ask += " Work in %s." % units
    if notes:
        ask += "\n\n%s\n%s" % ("Notes from the user:" if images else "Description from the user:", str(notes)[:6000])
    content.append({"type": "text", "text": ask})
    schema = tool_schema()
    function = {"name": schema["name"], "description": schema["description"], "parameters": schema["input_schema"]}
    return {"model": cfg["GEMINI_MODEL"], "max_tokens": cfg["MAX_OUTPUT_TOKENS"],
            "messages": [{"role": "system", "content": system_prompt()}, {"role": "user", "content": content}],
            "tools": [{"type": "function", "function": function}],
            "tool_choice": {"type": "function", "function": {"name": TOOL}}}


def build_payload(cfg, images, notes, units=""):
    if _provider(cfg) == "gemini":
        return _openai_payload(cfg, images, notes, units)
    return _anthropic_payload(cfg, images, notes, units)


def check_input(cfg, images, notes):
    if not isinstance(images, list):
        raise AiError("The drawing images were not sent correctly.", 400)
    if not images and not str(notes or "").strip():
        raise AiError("Add drawings to read, or describe the structure in words.", 400)
    if len(images) > cfg["MAX_IMAGES"]:
        raise AiError("Too many images (%d). The limit is %d; choose fewer pages or a lower detail level."
                      % (len(images), cfg["MAX_IMAGES"]), 400)
    for img in images:
        if not isinstance(img, dict) or img.get("media_type") not in MEDIA or not isinstance(img.get("data"), str):
            raise AiError("Each image needs a media_type of image/jpeg or image/png and base64 data.", 400)
        if len(img["data"]) > 10 * 1024 * 1024:
            raise AiError("One image is over the 10 MB API limit; use a lower detail level.", 400)


def call_api(cfg, payload, opener=urlopen):
    provider = _provider(cfg)
    key = _api_key(cfg, provider)
    name = "Gemini" if provider == "gemini" else "Claude"
    if provider == "gemini":
        url = cfg["GEMINI_URL"]
        headers = {"content-type": "application/json", "authorization": "Bearer " + key}
    else:
        url = cfg["ANTHROPIC_URL"]
        headers = {"content-type": "application/json", "x-api-key": key, "anthropic-version": cfg["ANTHROPIC_VERSION"]}
    req = Request(url, data=json.dumps(payload).encode("utf-8"), method="POST", headers=headers)
    try:
        resp = opener(req, timeout=cfg["REQUEST_TIMEOUT"])
        return json.loads(resp.read().decode("utf-8"))
    except HTTPError as err:
        detail = ""
        try:
            detail = json.loads(err.read().decode("utf-8")).get("error", {}).get("message", "")
        except Exception:
            pass
        raise AiError("The %s API returned an error (%d). %s" % (name, err.code, detail), 502)
    except socket.timeout:
        raise AiError("The %s API did not answer within %d seconds. Try fewer pages or a lower detail level."
                      % (name, cfg["REQUEST_TIMEOUT"]), 504)
    except URLError as err:
        if isinstance(getattr(err, "reason", None), socket.timeout):
            raise AiError("The %s API timed out. Try fewer pages or a lower detail level." % name, 504)
        raise AiError("Could not reach the %s API from this server: %s" % (name, err.reason), 502)


def _check_openai_model(cfg, opener=urlopen):
    """List the models the OpenAI-compatible endpoint offers and check ours is among them.

    The list reply does not say whether a model takes images, so that check is skipped here; a model that cannot
    read drawings fails the first real run, and the error names it.
    """
    key = _api_key(cfg, "gemini")
    base = cfg["GEMINI_URL"]
    if base.endswith("/chat/completions"):
        base = base[:-len("/chat/completions")]
    req = Request(base.rstrip("/") + "/models", method="GET", headers={"authorization": "Bearer " + key})
    try:
        info = json.loads(opener(req, timeout=30).read().decode("utf-8"))
    except HTTPError as err:
        detail = ""
        try:
            detail = json.loads(err.read().decode("utf-8")).get("error", {}).get("message", "")
        except Exception:
            pass
        if err.code in (401, 403):
            raise AiError("The Gemini API key was not accepted (%d). %s" % (err.code, detail), 502)
        raise AiError("The Gemini API returned an error (%d). %s" % (err.code, detail), 502)
    except socket.timeout:
        raise AiError("The Gemini API did not answer within 30 seconds.", 504)
    except URLError as err:
        raise AiError("Could not reach the Gemini API from this server: %s" % err.reason, 502)
    except ValueError:
        raise AiError("The Gemini API sent a reply that could not be read.", 502)
    ids = [m.get("id") for m in (info.get("data") or []) if isinstance(m, dict)]
    out = {"ok": True, "model": cfg["GEMINI_MODEL"], "display_name": "", "lifecycle": "", "images": None,
           "max_output_tokens": None, "warnings": []}
    if cfg["GEMINI_MODEL"] not in ids:
        out["warnings"].append("This model was not listed by the API; check GEMINI_MODEL.")
    return out


def check_model(cfg, opener=urlopen):
    """Ask the API about the configured model. Costs nothing, and proves the key, the model name and the network path."""
    if _provider(cfg) == "gemini":
        return _check_openai_model(cfg, opener)
    if not cfg.get("ANTHROPIC_API_KEY"):
        raise AiError("No Anthropic API key is configured on the server.", 503)
    url = cfg["ANTHROPIC_URL"].rsplit("/", 1)[0] + "/models/" + quote(str(cfg["ANTHROPIC_MODEL"]), safe="")
    req = Request(url, method="GET", headers={"x-api-key": cfg["ANTHROPIC_API_KEY"], "anthropic-version": cfg["ANTHROPIC_VERSION"]})
    try:
        info = json.loads(opener(req, timeout=30).read().decode("utf-8"))
    except HTTPError as err:
        detail = ""
        try:
            detail = json.loads(err.read().decode("utf-8")).get("error", {}).get("message", "")
        except Exception:
            pass
        if err.code in (401, 403):
            raise AiError("The Anthropic API key was not accepted (%d). %s" % (err.code, detail), 502)
        if err.code == 404:
            raise AiError("This API key cannot use the model '%s' (404). %s" % (cfg["ANTHROPIC_MODEL"], detail), 502)
        raise AiError("The Claude API returned an error (%d). %s" % (err.code, detail), 502)
    except socket.timeout:
        raise AiError("The Claude API did not answer within 30 seconds.", 504)
    except URLError as err:
        raise AiError("Could not reach the Claude API from this server: %s" % err.reason, 502)
    except ValueError:
        raise AiError("The Claude API sent a reply that could not be read.", 502)
    caps = info.get("capabilities") or {}
    out = {"ok": True, "model": info.get("id") or cfg["ANTHROPIC_MODEL"], "display_name": info.get("display_name") or "",
           "lifecycle": info.get("lifecycle") or "", "images": (caps.get("image_input") or {}).get("supported"),
           "max_output_tokens": info.get("max_tokens") or None, "warnings": []}
    if out["images"] is False:
        out["warnings"].append("This model does not accept images, so it cannot read drawings.")
    if out["lifecycle"] in ("deprecated", "retired"):
        out["warnings"].append("This model is %s; set ANTHROPIC_MODEL to a current one." % out["lifecycle"])
    if out["max_output_tokens"] and cfg["MAX_OUTPUT_TOKENS"] > out["max_output_tokens"]:
        out["warnings"].append("MAX_OUTPUT_TOKENS (%d) is above this model's limit (%d)." % (cfg["MAX_OUTPUT_TOKENS"], out["max_output_tokens"]))
    return out


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


def _scene_from_data(data, texts):
    if not isinstance(data, dict) or not isinstance(data.get("components"), list):
        raise AiError("The model did not return a structure. Its reply began: %s" % ("\n".join(texts)[:200] or "(empty)"), 502)
    head = {k: data.get(k) for k in ("name", "structure_type", "units", "datum", "description")}
    try:
        base = scene_mod.normalise(dict(head, components=[]))
    except scene_mod.SceneError:
        base = scene_mod.normalise({"units": "ft", "name": str(data.get("name") or "")})
    kept, rejected = [], []
    for number, raw in enumerate(data["components"], 1):
        try:
            if isinstance(raw, dict) and raw.get("source") not in AI_SOURCES:
                raw = dict(raw, source="assumed")
            kept.append(scene_mod.normalise_component(raw, base["units"]))
        except scene_mod.SceneError as err:                # each one is checked alone, so it reports itself as "Component 1"
            label = "Component %d" % number
            if isinstance(raw, dict) and raw.get("name"):
                label += " (%s)" % str(raw["name"])[:80]
            rejected.append(re.sub(r"^Component 1\b", lambda _m: label, str(err)))
    base["components"] = scene_mod.normalise(dict(base, components=kept))["components"]
    missing = [str(m)[:400] for m in (data.get("missing") or []) if m][:40]
    return base, missing, str(data.get("general_notes") or "")[:3000], rejected


def _parse_openai_response(response):
    """Read the tool call (or plain JSON in the text) out of a chat completions reply."""
    choice = (response.get("choices") or [{}])[0]
    if choice.get("finish_reason") == "length":
        raise AiError("The reply was cut off before it finished. Raise MAX_OUTPUT_TOKENS, or read fewer pages at a time.", 502)
    message = choice.get("message") or {}
    data, texts = None, []
    for call in message.get("tool_calls") or []:
        fn = call.get("function") or {}
        if fn.get("name") != TOOL:
            continue
        try:
            data = json.loads(fn.get("arguments") or "")
        except ValueError:
            data = None
        break
    if isinstance(message.get("content"), str) and message["content"]:
        texts.append(message["content"])
    if data is None:
        data = _json_from_text("\n".join(texts))
    return _scene_from_data(data, texts)


def parse_response(response):
    """Return (scene, missing, general_notes, rejected) from a Messages API or chat completions response."""
    if "choices" in response:
        return _parse_openai_response(response)
    if response.get("stop_reason") == "max_tokens":
        raise AiError("The reply was cut off before it finished. Raise MAX_OUTPUT_TOKENS, or read fewer pages at a time.", 502)
    data, texts = None, []
    for block in response.get("content") or []:
        if block.get("type") == "tool_use" and block.get("name") == TOOL and isinstance(block.get("input"), dict):
            data = block["input"]
            break
        if block.get("type") == "text":
            texts.append(block.get("text") or "")
    if data is None:
        data = _json_from_text("\n".join(texts))
    return _scene_from_data(data, texts)


def compose(cfg, images, notes="", units="", opener=urlopen):
    images = images or []
    check_input(cfg, images, notes)
    response = call_api(cfg, build_payload(cfg, images, notes, units), opener)
    sc, missing, general, rejected = parse_response(response)
    return {"scene": sc, "missing": missing, "general_notes": general, "rejected": rejected,
            "model": response.get("model") or _model(cfg), "usage": response.get("usage") or {},
            "pieces": scene_mod.count_parts(sc)}
