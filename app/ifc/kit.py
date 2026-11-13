"""Modelling helpers on top of the STEP writer: project setup, geometry, elements, property sets.

Two schemas are supported. IFC2X3 (Coordination View 2.0) is the most widely read. IFC4X3 adds the
marine and earthworks classes (IfcMarineFacility, IfcMooringDevice, IfcCourse and so on).
Geometry is placed in world coordinates; every element has an identity placement under its container.
"""
import math

from .writer import File, E, Typed, STAR, guid

# Attributes that follow the eight shared product attributes, per schema and class.
_PT = lambda pt: (E(pt or "NOTDEFINED"),)
_TAIL = {
    "IFC2X3": {
        "IfcBeam": lambda pt: (), "IfcColumn": lambda pt: (), "IfcMember": lambda pt: (), "IfcPlate": lambda pt: (),
        "IfcWall": lambda pt: (), "IfcDiscreteAccessory": lambda pt: (), "IfcFlowController": lambda pt: (),
        "IfcRailing": _PT, "IfcSlab": _PT, "IfcFooting": _PT,
        "IfcBuildingElementProxy": lambda pt: (None,),
        "IfcPile": lambda pt: (E(pt or "NOTDEFINED"), None),
        "IfcElementAssembly": lambda pt: (None, E(pt or "NOTDEFINED")),
    },
    "IFC4X3": {
        "IfcBeam": _PT, "IfcColumn": _PT, "IfcMember": _PT, "IfcPlate": _PT, "IfcWall": _PT, "IfcDiscreteAccessory": _PT,
        "IfcRailing": _PT, "IfcSlab": _PT, "IfcFooting": _PT, "IfcBuildingElementProxy": _PT, "IfcMooringDevice": _PT,
        "IfcImpactProtectionDevice": _PT, "IfcEarthworksFill": _PT, "IfcCourse": _PT,
        "IfcPile": lambda pt: (E(pt or "NOTDEFINED"), None),
        "IfcElementAssembly": lambda pt: (None, E(pt or "NOTDEFINED")),
    },
}
_UNITS = {"FOOT": None, "MILLIMETRE": "MILLI", "METRE": None}


def unit_vec(v):
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v)


class Model(object):
    def __init__(self, project, unit="MILLIMETRE", site="Site", building="Building", storey="Datum",
                 author="", organization="", timestamp=None, filename="model.ifc", schema="IFC2X3",
                 facility_type="NOTDEFINED"):
        if schema not in _TAIL:
            raise ValueError("unsupported IFC schema: %s" % schema)
        if unit not in _UNITS:
            raise ValueError("unsupported length unit: %s" % unit)
        self.schema = schema
        self.f = File(schema="IFC4X3_ADD2" if schema == "IFC4X3" else schema, name=filename, author=author,
                      organization=organization, timestamp=timestamp,
                      view="CoordinationView_V2.0" if schema == "IFC2X3" else "ReferenceView")
        self.seed = project
        self._n = 0
        self._styles = {}
        self._materials = {}
        self._mat_users = {}
        self._contained = []
        self._children = {}
        f = self.f
        person = f.add("IfcPerson", None, author or "Unknown", None, None, None, None, None, None)
        org = f.add("IfcOrganization", None, organization or "Unknown", None, None, None)
        pao = f.add("IfcPersonAndOrganization", person, org, None)
        dev = f.add("IfcOrganization", None, "pdf-to-ifc-modeler", None, None, None)
        app = f.add("IfcApplication", dev, "1.0", "PDF to IFC Modeler", "pdf-to-ifc-modeler")
        self.oh = f.add("IfcOwnerHistory", pao, app, None, E("ADDED"), None, None, None, f.timestamp)
        if unit == "FOOT":
            metre = f.add("IfcSIUnit", STAR, E("LENGTHUNIT"), None, E("METRE"))
            dims = f.add("IfcDimensionalExponents", 1, 0, 0, 0, 0, 0, 0)
            conv = f.add("IfcMeasureWithUnit", Typed("IfcLengthMeasure", 0.3048), metre)
            length = f.add("IfcConversionBasedUnit", dims, E("LENGTHUNIT"), "FOOT", conv)
        elif unit == "METRE":
            length = f.add("IfcSIUnit", STAR, E("LENGTHUNIT"), None, E("METRE"))
        else:
            length = f.add("IfcSIUnit", STAR, E("LENGTHUNIT"), E("MILLI"), E("METRE"))
        area = f.add("IfcSIUnit", STAR, E("AREAUNIT"), None, E("SQUARE_METRE"))
        vol = f.add("IfcSIUnit", STAR, E("VOLUMEUNIT"), None, E("CUBIC_METRE"))
        angle = f.add("IfcSIUnit", STAR, E("PLANEANGLEUNIT"), None, E("RADIAN"))
        units = f.add("IfcUnitAssignment", [length, area, vol, angle])
        self.unit = unit
        ctx = f.add("IfcGeometricRepresentationContext", None, "Model", 3, 1.0e-5, self.a3(), None)
        self.body = f.add("IfcGeometricRepresentationSubContext", "Body", "Model", STAR, STAR, STAR, STAR,
                          ctx, None, E("MODEL_VIEW"), None)
        self.axis = f.add("IfcGeometricRepresentationSubContext", "Axis", "Model", STAR, STAR, STAR, STAR,
                          ctx, None, E("GRAPH_VIEW"), None)
        self.project = f.add("IfcProject", self.gid("project"), self.oh, project, None, None, None, None,
                             [ctx], units)
        p_site = f.add("IfcLocalPlacement", None, self.a3())
        self.site = f.add("IfcSite", self.gid("site"), self.oh, site, None, None, p_site, None, None,
                          E("ELEMENT"), None, None, None, None, None)
        f.add("IfcRelAggregates", self.gid("agg-site"), self.oh, None, None, self.project, [self.site])
        if schema == "IFC4X3":
            self.p_storey = f.add("IfcLocalPlacement", p_site, self.a3())
            self.building = f.add("IfcMarineFacility", self.gid("facility"), self.oh, building, None, None,
                                  self.p_storey, None, None, E("ELEMENT"), E(facility_type))
            self.storey = self.building
            f.add("IfcRelAggregates", self.gid("agg-bldg"), self.oh, None, None, self.site, [self.building])
        else:
            p_bldg = f.add("IfcLocalPlacement", p_site, self.a3())
            self.building = f.add("IfcBuilding", self.gid("building"), self.oh, building, None, None, p_bldg,
                                  None, None, E("ELEMENT"), None, None, None)
            self.p_storey = f.add("IfcLocalPlacement", p_bldg, self.a3())
            self.storey = f.add("IfcBuildingStorey", self.gid("storey"), self.oh, storey, None, None,
                                self.p_storey, None, None, E("ELEMENT"), 0.0)
            f.add("IfcRelAggregates", self.gid("agg-bldg"), self.oh, None, None, self.site, [self.building])
            f.add("IfcRelAggregates", self.gid("agg-storey"), self.oh, None, None, self.building, [self.storey])

    # ---- ids and primitives -------------------------------------------------------------
    def gid(self, tag):
        self._n += 1
        return guid("%s|%s|%d" % (self.seed, tag, self._n))

    def pt(self, *c):
        return self.f.add("IfcCartesianPoint", [float(x) for x in c])

    def dr(self, *c):
        return self.f.add("IfcDirection", [float(x) for x in c])

    def a3(self, o=(0, 0, 0), axis=(0, 0, 1), ref=(1, 0, 0)):
        return self.f.add("IfcAxis2Placement3D", self.pt(*o), self.dr(*axis), self.dr(*ref))

    def a2(self):
        return self.f.add("IfcAxis2Placement2D", self.pt(0, 0), self.dr(1, 0))

    # ---- profiles -----------------------------------------------------------------------
    def polygon(self, pts, name=None):
        pts = [tuple(float(c) for c in p) for p in pts]
        loop = [self.pt(*p) for p in pts]
        loop.append(loop[0])
        return self.f.add("IfcArbitraryClosedProfileDef", E("AREA"), name, self.f.add("IfcPolyline", loop))

    def rect(self, name, x, y):
        return self.f.add("IfcRectangleProfileDef", E("AREA"), name, self.a2(), float(x), float(y))

    def tube(self, name, b, t):
        return self.f.add("IfcRectangleHollowProfileDef", E("AREA"), name, self.a2(), float(b), float(b),
                          float(t), None, None)

    def circle(self, name, r):
        return self.f.add("IfcCircleProfileDef", E("AREA"), name, self.a2(), float(r))

    def ring(self, name, r, t):
        return self.f.add("IfcCircleHollowProfileDef", E("AREA"), name, self.a2(), float(r), float(t))

    def channel(self, name, depth, flange_w, web_t, flange_t):
        return self.f.add("IfcUShapeProfileDef", E("AREA"), name, self.a2(), float(depth), float(flange_w),
                          float(web_t), float(flange_t), None, None, None, None)

    def angle(self, name, leg, t):
        return self.f.add("IfcLShapeProfileDef", E("AREA"), name, self.a2(), float(leg), float(leg),
                          float(t), None, None, None, None, None)

    # ---- solids -------------------------------------------------------------------------
    def extrude(self, profile, placement, depth):
        return self.f.add("IfcExtrudedAreaSolid", profile, placement, self.dr(0, 0, 1), float(depth))

    def ext_x(self, yz, x0, x1):
        """Profile given as (y, z) points, extruded along +X between x0 and x1."""
        pl = self.a3((min(x0, x1), 0, 0), (1, 0, 0), (0, 1, 0))
        return self.extrude(self.polygon(yz), pl, abs(x1 - x0))

    def ext_y(self, xz, y0, y1):
        """Profile given as (x, z) points, extruded along Y between y0 and y1."""
        pl = self.a3((0, max(y0, y1), 0), (0, -1, 0), (1, 0, 0))
        return self.extrude(self.polygon(xz), pl, abs(y1 - y0))

    def ext_z(self, xy, z0, depth):
        return self.extrude(self.polygon(xy), self.a3((0, 0, z0)), depth)

    def box(self, x0, x1, y0, y1, z0, z1):
        return self.ext_x([(y0, z0), (y1, z0), (y1, z1), (y0, z1)], x0, x1)

    def sweep(self, profile, p0, p1, ref=None):
        """Extrude a profile along the straight line p0 -> p1; ref fixes the profile's local X."""
        ax = unit_vec(tuple(b - a for a, b in zip(p0, p1)))
        length = math.sqrt(sum((b - a) ** 2 for a, b in zip(p0, p1)))
        if ref is None:
            ref = (1, 0, 0) if abs(ax[0]) < 0.9 else (0, 1, 0)
        k = sum(a * b for a, b in zip(ax, ref))
        ref = unit_vec(tuple(r - k * a for r, a in zip(ref, ax)))
        return self.extrude(profile, self.a3(p0, ax, ref), length)

    def _faces(self, face_pts):
        cache = {}
        faces = []
        for fc in face_pts:
            loop = []
            for p in fc:
                key = tuple(round(float(c), 4) for c in p)
                if loop and loop[-1] == key:
                    continue
                loop.append(key)
            if len(loop) > 1 and loop[0] == loop[-1]:
                loop.pop()
            if len(set(loop)) < 3:
                continue
            pts = []
            for key in loop:
                if key not in cache:
                    cache[key] = self.pt(*key)
                pts.append(cache[key])
            bound = self.f.add("IfcFaceOuterBound", self.f.add("IfcPolyLoop", pts), True)
            faces.append(self.f.add("IfcFace", [bound]))
        return faces

    def brep(self, face_pts):
        return self.f.add("IfcFacetedBrep", self.f.add("IfcClosedShell", self._faces(face_pts)))

    def surface(self, face_pts):
        return self.f.add("IfcShellBasedSurfaceModel", [self.f.add("IfcOpenShell", self._faces(face_pts))])

    # ---- appearance and materials --------------------------------------------------------
    def style(self, name, rgb, transparency=0.0):
        if name not in self._styles:
            col = self.f.add("IfcColourRgb", None, float(rgb[0]), float(rgb[1]), float(rgb[2]))
            rend = self.f.add("IfcSurfaceStyleRendering", col, float(transparency), None, None, None, None,
                              None, None, E("FLAT"))
            ss = self.f.add("IfcSurfaceStyle", name, E("BOTH"), [rend])
            self._styles[name] = ss if self.schema == "IFC4X3" else self.f.add("IfcPresentationStyleAssignment", [ss])
        return self._styles[name]

    def material(self, name):
        if name not in self._materials:
            self._materials[name] = (self.f.add("IfcMaterial", name, None, None) if self.schema == "IFC4X3"
                                     else self.f.add("IfcMaterial", name))
            self._mat_users[name] = []
        return name

    # ---- property sets ------------------------------------------------------------------
    def pset(self, product, name, props):
        """Attach a property set. Values may be bool, number or text; None values are skipped."""
        items = []
        for key, val in props.items():
            if val is None:
                continue
            if isinstance(val, bool):
                tv = Typed("IfcBoolean", val)
            elif isinstance(val, (int, float)):
                tv = Typed("IfcReal", float(val))
            else:
                s = str(val)
                tv = Typed("IfcLabel" if len(s) <= 255 else "IfcText", s)
            items.append(self.f.add("IfcPropertySingleValue", str(key), None, tv, None))
        if not items:
            return None
        ps = self.f.add("IfcPropertySet", self.gid("pset"), self.oh, name, None, items)
        self.f.add("IfcRelDefinesByProperties", self.gid("relpset"), self.oh, None, None, [product], ps)
        return ps

    # ---- elements -----------------------------------------------------------------------
    def element(self, cls, name, items, style=None, material=None, otype=None, desc=None, props=None,
                axis=None, predefined=None, parent=None, pset_name="DrawingSource"):
        f = self.f
        rep = None
        if items:
            if style is not None:
                for it in items:
                    f.add("IfcStyledItem", it, [style], None)
            kinds = set(i.type for i in items)
            if kinds == {"IFCEXTRUDEDAREASOLID"}:
                rtype = "SweptSolid"
            elif kinds == {"IFCSHELLBASEDSURFACEMODEL"}:
                rtype = "SurfaceModel"
            else:
                rtype = "Brep"
            reps = []
            if axis:
                line = f.add("IfcPolyline", [self.pt(*p) for p in axis])
                reps.append(f.add("IfcShapeRepresentation", self.axis, "Axis", "Curve3D", [line]))
            reps.append(f.add("IfcShapeRepresentation", self.body, "Body", rtype, items))
            rep = f.add("IfcProductDefinitionShape", None, None, reps)
        placement = f.add("IfcLocalPlacement", self.p_storey, self.a3())
        if predefined == "USERDEFINED" and not otype:
            otype = name
        tail = _TAIL[self.schema][cls](predefined)
        el = f.add(cls, self.gid(name), self.oh, name, desc, otype, placement, rep, None, *tail)
        if material:
            self._mat_users[self.material(material)].append(el)
        if props:
            self.pset(el, pset_name, props)
        if parent is None:
            self._contained.append(el)
        else:
            self._children.setdefault(parent.id, (parent, []))[1].append(el)
        return el

    def finish(self):
        f = self.f
        if self._contained:
            f.add("IfcRelContainedInSpatialStructure", self.gid("contain"), self.oh, None, None,
                  self._contained, self.storey)
        for parent, kids in self._children.values():
            f.add("IfcRelAggregates", self.gid("decompose"), self.oh, None, None, parent, kids)
        for name, users in self._mat_users.items():
            if users:
                f.add("IfcRelAssociatesMaterial", self.gid("mat"), self.oh, None, None, users,
                      self._materials[name])
        return f.to_string()
