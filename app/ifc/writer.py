"""Minimal IFC (ISO 10303-21) writer using only the standard library.

Entities are written positionally, so the caller is responsible for attribute order.
tools/validate_ifc.py checks generated files against the schema with IfcOpenShell (dev only).
"""
import time
import uuid

_GUID_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$"


class Entity(object):
    __slots__ = ("id", "type", "args")

    def __init__(self, id_, type_, args):
        self.id = id_
        self.type = type_
        self.args = args


class Enum(str):
    """An EXPRESS enumeration value, written as .VALUE."""


class Typed(object):
    """A typed simple value, written as IFCLABEL('x')."""
    __slots__ = ("type", "value")

    def __init__(self, type_, value):
        self.type = type_
        self.value = value


class _Star(object):
    pass


STAR = _Star()          # a derived attribute, written as *


def E(name):
    return Enum(name)


def _real(v):
    v = float(v)
    if v != v or v in (float("inf"), float("-inf")):
        raise ValueError("non-finite number in IFC output")
    if abs(v) < 1e-9:
        return "0."
    s = "%.9g" % v
    if "e" in s:
        mant, exp = s.split("e")
        if "." not in mant:
            mant += "."
        return mant + "E" + exp
    return s if "." in s else s + "."


def _esc(s):
    out = []
    for ch in s:
        o = ord(ch)
        if ch == "'":
            out.append("''")
        elif ch == "\\":
            out.append("\\\\")
        elif 32 <= o <= 126:
            out.append(ch)
        elif o <= 0xFFFF:
            out.append("\\X2\\%04X\\X0\\" % o)
        else:
            out.append("?")
    return "".join(out)


def fmt(v):
    if v is None:
        return "$"
    if v is STAR:
        return "*"
    if isinstance(v, Entity):
        return "#%d" % v.id
    if isinstance(v, Enum):
        return "." + str(v) + "."
    if isinstance(v, Typed):
        return "%s(%s)" % (v.type.upper(), fmt(v.value))
    if isinstance(v, bool):
        return ".T." if v else ".F."
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return _real(v)
    if isinstance(v, str):
        return "'" + _esc(v) + "'"
    if isinstance(v, (list, tuple)):
        return "(" + ",".join(fmt(x) for x in v) + ")"
    raise TypeError("cannot write %r to IFC" % (v,))


def guid(seed):
    """Deterministic 22-character IFC GlobalId, so regenerating a model keeps its ids."""
    n = uuid.uuid5(uuid.NAMESPACE_URL, seed).int
    chars = []
    for _ in range(22):
        chars.append(_GUID_CHARS[n & 63])
        n >>= 6
    return "".join(reversed(chars))


class File(object):
    def __init__(self, schema="IFC2X3", name="model.ifc", author="", organization="",
                 application="pdf-to-ifc-modeler", view="CoordinationView_V2.0", timestamp=None):
        self.schema = schema
        self.name = name
        self.author = author
        self.organization = organization
        self.application = application
        self.view = view
        self.timestamp = int(time.time()) if timestamp is None else int(timestamp)
        self.entities = []

    def add(self, type_, *args):
        ent = Entity(len(self.entities) + 1, type_.upper(), args)
        self.entities.append(ent)
        return ent

    def by_type(self, type_):
        t = type_.upper()
        return [e for e in self.entities if e.type == t]

    def to_string(self):
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(self.timestamp))
        lines = [
            "ISO-10303-21;",
            "HEADER;",
            "FILE_DESCRIPTION(('ViewDefinition [%s]'),'2;1');" % _esc(self.view),
            "FILE_NAME(%s,%s,(%s),(%s),%s,%s,'');" % (
                fmt(self.name), fmt(stamp), fmt(self.author), fmt(self.organization),
                fmt(self.application), fmt(self.application)),
            "FILE_SCHEMA(('%s'));" % self.schema,
            "ENDSEC;",
            "DATA;",
        ]
        for e in self.entities:
            lines.append("#%d=%s(%s);" % (e.id, e.type, ",".join(fmt(a) for a in e.args)))
        lines += ["ENDSEC;", "END-ISO-10303-21;", ""]
        return "\n".join(lines)
