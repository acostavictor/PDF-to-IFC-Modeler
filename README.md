# PDF to IFC Modeler

A web app for building IFC 3D models of marine and waterfront structures (piers, wharves, dolphins, marinas,
breakwaters, bulkheads, dry docks) from PDF drawings, and for keeping those models and their parts in a
database so the next project starts from the last one.

## How it works

Every model is a list of **components** drawn from nine building blocks. Whatever fills that list, the same
engine checks it, draws it in 3D and writes the IFC file.

```
 PDF drawings ──▶ AI proposes components ─┐
 Words ("timber pier 120 ft by 16 ft…") ──┤
 A saved model, copied and adjusted ──────┼──▶ component list ──▶ 3D preview ──▶ IFC file
 Parts from the library ──────────────────┤        ▲     │
 Components added by hand ────────────────┘        │     ▼
                                              you edit   saved to the database
```

1. **Start.** Load a PDF and let the AI propose components from the sheets you pick, describe the structure
   in words, open a saved model, or start empty.
2. **Check.** The model appears in 3D beside the drawings. Each component records where its sizes came from
   (written on the drawing, calculated, measured from the scan, assumed, or from the library) with a note.
   Colour the model by source to see what still rests on assumptions. Edit any value and the model redraws.
3. **Save and reuse.** Save the model to the database. Save any component or assembly (a pile bent, a
   dolphin, a fender system) to the library and insert it into later models; units are converted on the way.
4. **Export.** Download IFC2x3 or IFC 4.3.

### Building blocks

| Block | Used for |
|---|---|
| Pile | Bearing, batter, fender, guide and sheet-wall king piles: round, pipe, square, octagonal or H; plumb or battered |
| Block | Pile caps, dolphin caps, pontoons, mooring blocks, deadmen |
| Slab | Decks, aprons, relieving platforms, floors, ramps; rectangle or any outline |
| Beam or linear member | Cap beams, stringers, walers, bullrails, tie rods, braces, gangways |
| Wall | Sheet pile walls, bulkheads, seawalls, quay walls, wave walls |
| Swept cross-section | Breakwater and revetment layers, gravity walls, dock walls, dredge cuts: any section along a line |
| Fender | Cylindrical, arch, cone, cell and D fenders (simplified shapes) |
| Mooring fitting | Bollards, cleats, bitts, quick release hooks (simplified shapes) |
| Assembly | A group of the above placed and repeated as one unit |

Any component can be repeated on a grid or at listed positions.

### What "any structure" means here

Anything you can describe with those blocks. Straight members, prisms and constant sections along a line are
exact. Curved members, tapered sections, connection details, reinforcement and mechanical equipment are not
modelled; the AI is told to list what it left out rather than invent it. The AI's output is a proposal: it
can misread a dimension or a scale, which is why every component carries its source and sits next to the
drawing for checking.

## The database

- **Models.** Each saved model keeps its full component list, so it can be reopened, adjusted and saved as
  a copy for a new project. Search by name, project, structure type or description.
- **Library.** Reusable components and assemblies, grouped by category and searchable by name or tag.
- A new database starts with 26 library items and 6 example models (pier, mooring dolphin, marina dock,
  rubble mound breakwater, sheet pile bulkhead, dry dock). The example sizes are generic, not design values.
- It is one SQLite file, by default `~/.pdf2ifc/pdf2ifc.sqlite3`, outside the web folder. Back it up by
  copying that file.

## Output

| Choice | Use it when | Contents |
|---|---|---|
| **IFC2x3** (default) | Revit, Navisworks, STAAD and most viewers | `IfcPile`, `IfcBeam`, `IfcSlab`, `IfcWall`, `IfcFooting`, `IfcMember`; fenders and mooring fittings as `IfcDiscreteAccessory`; rock layers as proxies |
| **IFC 4.3** | The receiving tool reads 4.3 and you want marine classes | `IfcMarineFacility`, `IfcMooringDevice`, `IfcImpactProtectionDevice`, `IfcCourse` (armour, core, filter), `IfcEarthworksFill` |

Assemblies become `IfcElementAssembly`. Every element carries a `P2I_Component` property set with its
source, note, material and library origin. The 3D preview and the IFC file are produced from the same
geometry, and the tests confirm they have the same extents.

## Preview site

https://acostavictor.github.io/PDF-to-IFC-Modeler/ is this repository served by GitHub Pages. Pages cannot
run the Python server, so the page switches to **preview mode**: the Python engine is loaded into the browser
with Pyodide.

| | Preview site | Server version |
|---|---|---|
| Build, edit, 3D preview, IFC export | Yes | Yes |
| View a PDF beside the model | Yes | Yes |
| Saved models and library | In that browser only | Shared SQLite database |
| Build with AI | No | Yes |

AI is left out of preview mode because an API key cannot be kept secret in a public page. The first visit
downloads about 13 MB (Pyodide, from the jsDelivr CDN).

## Status

Tested:

- 44 unit tests on Python 3.8 and 3.13. With IfcOpenShell installed, every example model and library item
  is exported in both schemas, validated against the schema, checked to produce geometry for every piece,
  and compared with the preview's extents.
- The browser flows in Chromium: open, edit, save, library insert, unit change, export, sign-in, and
  building with AI against a stand-in for the Claude API. Preview mode was tested with the repository
  served as static files.

Not yet tested:

- **A real call to the Claude API.** `tools/setup_server.py --ai-test` makes one from your server with your
  key. How well it reads a given drawing set is unknown until you try it.
- **Running on HostGator**, including whether its Python has the `sqlite3` module (`/api/health` reports it).
- **Opening the exports in Revit, Navisworks or STAAD.** Only IfcOpenShell has read them.

## Requirements

- **Server:** Python 3 with the standard library only. Runs as plain CGI. Written for 3.6+; tested on 3.8 and 3.13.
- **Browser:** a current Chrome, Edge, Firefox or Safari with WebGL.
- **AI (optional):** an Anthropic API key. Each run is billed to that key.

## Run it locally

```
python3 tools/dev_server.py
```

Open http://localhost:8000/. On your own machine the database works without a password.

To turn on AI, run the set-up script. It asks for your Anthropic API key and a password without showing
them, saves them to a private file outside the repository, and checks the machine, including a free call
that proves the key and the connection:

```
python3 tools/setup_server.py              # set up and check
python3 tools/setup_server.py --check      # check only
python3 tools/setup_server.py --check --ai-test    # also one small real AI run, billed to your key
```

## Configuration

Values come from environment variables, or from a JSON file: `$PDF2IFC_CONFIG`, then
`~/.pdf2ifc/config.json`, then `config.local.json` in the app folder. Keep the file outside the web folder on
a public server.

| Key | Purpose | Default |
|---|---|---|
| `APP_PASSWORD` | Password for the app. On a public server the database and AI stay off until this is set. | none |
| `ANTHROPIC_API_KEY` | Your Anthropic API key. Needed for AI. | none |
| `DB_PATH` | Where the SQLite file lives. | `~/.pdf2ifc/pdf2ifc.sqlite3` |
| `ANTHROPIC_MODEL` | Model used to read drawings. | `claude-opus-5-5` |
| `ANTHROPIC_VERSION` | Value of the `anthropic-version` header. | `2026-10-21` |
| `MAX_IMAGES` | Most images accepted per run. | 60 |
| `MAX_BODY_MB` | Largest upload accepted. | 60 |
| `REQUEST_TIMEOUT` | Seconds to wait for the AI model. | 280 |
| `MAX_OUTPUT_TOKENS` | Output limit for one run. Raise it if large models are cut off. | 16000 |
| `SECRET_KEY` | Signs the sign-in cookie. Derived from the password and key if empty. | none |

There is one shared password and no user accounts; everyone who has it sees and can change the same database.

## Deploying

See [docs/DEPLOY_HOSTGATOR.md](docs/DEPLOY_HOSTGATOR.md) for shared cPanel hosting. In short: clone the
repository into a folder under `public_html`, run `python3 tools/setup_server.py` there, and open the folder's
address over HTTPS.

Long AI runs: shared hosts stop a request whose script stays silent, so the server sends a keep-alive byte
every 10 seconds while Claude works. A host's hard limit on total request time still applies.

## Privacy

The PDF never leaves the browser as a file. The page images you choose are posted to your server and
forwarded to the Anthropic API; they are not stored. Saved models and library items are stored in the
database. Do not send drawings you are not allowed to share with a third-party service.

## Layout

```
index.html, static/        the page, its script, the 3D viewer, and vendored PDF.js and three.js
index.cgi                  CGI entry point (shared hosting)
passenger_wsgi.py          entry point for hosts that use Passenger
app/scene.py               the model format: building blocks, checking, unit conversion
app/geometry.py            turns components into solids (shared by the preview and the IFC export)
app/mesh.py                solids to triangles for the 3D preview
app/ifcexport.py, app/ifc/ solids to IFC; dependency-free IFC writer
app/db.py, app/seed.json   SQLite storage; starter library and example models
app/ai.py                  the Claude API request, prompt and response handling
app/server.py              routes; app/browser.py is the same engine for the preview site
tests/                     unit tests
tools/setup_server.py      writes the private config and checks a server, including the Claude connection
tools/                     local server, seed generator, IFC validation with IfcOpenShell (developer only)
```

## Tests

```
python3 -m unittest discover -s tests
pip install ifcopenshell && VALIDATE_IFC=1 python3 -m unittest discover -s tests
```

## Extending

- **A new building block:** add its inputs to `TYPES` in `app/scene.py`, a builder in `app/geometry.py` and
  an IFC class in `app/ifcexport.py`. The editor form, the AI prompt and the tool schema are generated from
  `TYPES`.
- **More starter content:** edit `tools/make_seed.py` and run it. Existing databases are not re-seeded.

## Earlier version

The first version built three fixed structure types (sloped strut gate with a STAAD export, floating caisson
gate, dry dock) from templates. It is kept on the branch `v1-templates`. Of those, the dry dock can be built
with the current blocks and is one of the examples; the two gates relied on purpose-built steel framing
that the general blocks do not reproduce.

## Third-party code

`static/vendor/pdfjs` is PDF.js 6.2.108 (Apache-2.0) and `static/vendor/three` is three.js 0.187.0 (MIT),
both unmodified.
