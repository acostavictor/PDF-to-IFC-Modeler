"""Configuration from environment variables, falling back to a JSON file kept out of the repository.

Search order for the file: $PDF2IFC_CONFIG, ~/.pdf2ifc/config.json, <app folder>/config.local.json.
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULTS = {
    "ANTHROPIC_API_KEY": "",
    "ANTHROPIC_MODEL": "claude-opus-5-5",
    "ANTHROPIC_VERSION": "2026-10-21",
    "ANTHROPIC_URL": "https://api.anthropic.com/v1/messages",
    "AI_PROVIDER": "anthropic",
    "GEMINI_API_KEY": "",
    "GEMINI_MODEL": "gemini-3.8-flash",
    "GEMINI_URL": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
    "APP_PASSWORD": "",
    "SECRET_KEY": "",
    "MAX_IMAGES": 60,
    "MAX_BODY_MB": 60,
    "REQUEST_TIMEOUT": 280,
    "MAX_OUTPUT_TOKENS": 16000,
    "DB_PATH": "",
}


def _file_values():
    paths = [os.environ.get("PDF2IFC_CONFIG"), os.path.join(os.path.expanduser("~"), ".pdf2ifc", "config.json"),
             os.path.join(ROOT, "config.local.json")]
    for path in paths:
        if path and os.path.isfile(path):
            with open(path, "r") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                raise ValueError("config file must hold a JSON object: " + path)
            return data, path
    return {}, None


def load():
    values = dict(DEFAULTS)
    data, path = _file_values()
    for key in DEFAULTS:
        if key in data and data[key] not in (None, ""):
            values[key] = data[key]
        if os.environ.get(key):
            values[key] = os.environ[key]
    for key in ("MAX_IMAGES", "MAX_BODY_MB", "REQUEST_TIMEOUT", "MAX_OUTPUT_TOKENS"):
        values[key] = int(values[key])
    values["_file"] = path
    return values
