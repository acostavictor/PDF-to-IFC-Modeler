# PDF to IFC Modeler

A small web app that turns engineering drawings (PDF) into an IFC 3D model, with a person checking every
dimension on the way.

1. **Choose a structure type.** Each type is a parametric template.
2. **Add the drawings.** The PDF is opened in your browser. The pages you pick are cut into an overview plus
   overlapping close-ups and sent to an AI model (Claude), which proposes each dimension and says whether it
   was written on the drawing, calculated, or measured from the scan.
3. **Review and build.** Every value sits beside the drawing with its source. Correct what is wrong, then
   download the IFC file. Values you have not replaced are flagged as example values.

The app does not turn an arbitrary drawing into a model on its own. It fills in a template, and a person
approves the numbers.

## Preview site

https://acostavictor.github.io/PDF-to-IFC-Modeler/ is this repository served by GitHub Pages from the
`gh-pages` branch. GitHub Pages cannot run the Python server, so the page switches to **preview mode**: the
same Python model builder is loaded into the browser with Pyodide, and models are built on your own machine.

| | Preview site | Server version (HostGator) |
|---|---|---|
| Open a PDF and view it beside the form | Yes | Yes |
| Type in values, download IFC and STAAD files | Yes | Yes |
| Read drawings with AI | No | Yes |
| Password | None; nothing to protect | Required for AI reading |

AI reading is left out of preview mode because an API key cannot be kept secret in a public web page. In
preview mode nothing is uploaded anywhere. The first visit downloads about 13 MB (Pyodide, from the jsDelivr
CDN). A workflow keeps `gh-pages` identical to `main` after every push to `main`.

## Structure types

| Type | What it builds | Units | Extra output |
|---|---|---|---|
| Sloped strut gate | Inclined skin plate, plate girders, bulb-flat stiffeners, struts, ties, catwalk, dock context | mm | STAAD.Pro input file (`.std`) |
| Floating caisson gate | Shell, keel and stems, decks, stringers, bulkheads, major frames, ballast, valve markers | ft | |
| Dry dock structure | Floor, side walls, head wall, sill with caisson grooves, gravel bed, sheet piling, dredge limit | ft | |

The default values of each type reproduce a worked example (Dry Dock No. 4 intermediate gate, Dry Dock No. 4
caisson, Dry Dock No. 5).

## Output

- **IFC2x3, Coordination View 2.0.** Chosen because it is the schema most widely read by BIM and structural tools.
- Every element carries a `DrawingSource` property set with the weakest source among the values it was built
  from. The building carries a `ModelInputs` property set listing every input, its value and its source.
- Element ids are stable: the same inputs give the same file.

## Status

- The IFC files of all three types pass IfcOpenShell schema validation, and every element produces geometry.
- The browser flow (sign in, open a PDF, cut pages into images, fill the form, download) was tested in
  Chromium against a stand-in for the Claude API.
- Preview mode was tested the same way, with the repository served as static files and the Pyodide CDN
  files supplied locally.
- **Not yet tested:** a real call to the Claude API, running on HostGator, and opening the STAAD file in
  STAAD.Pro. How well the AI reads a given drawing set is unknown until you try it; the review step exists
  for that reason.

## Requirements

- **Server:** Python 3, standard library only, with no packages to install. It runs as plain CGI. Written for 3.6 and newer; tested on 3.8, 3.11 and 3.13.
- **Browser:** a current Chrome, Edge, Firefox or Safari.
- **AI reading (optional):** an Anthropic API key. Each reading is billed to that key.

## Run it locally

```
python3 tools/dev_server.py
```

Open http://localhost:8000/. Without configuration you can fill in values by hand and build models. To turn on
AI reading, copy `config.example.json` to `config.local.json` and fill it in.

## Configuration

Values come from environment variables, or from a JSON file: `$PDF2IFC_CONFIG`, then
`~/.pdf2ifc/config.json`, then `config.local.json` in the app folder. Keep the file outside the web folder on
a public server.

| Key | Purpose | Default |
|---|---|---|
| `ANTHROPIC_API_KEY` | Your Anthropic API key. Needed for AI reading. | none |
| `APP_PASSWORD` | Password for the app. AI reading stays off until this is set. | none |
| `ANTHROPIC_MODEL` | Model used to read drawings. | `claude-opus-5-5` |
| `ANTHROPIC_VERSION` | Value of the `anthropic-version` header. | `2026-10-21` |
| `MAX_IMAGES` | Most images accepted per reading. | 60 |
| `MAX_BODY_MB` | Largest upload accepted. | 60 |
| `REQUEST_TIMEOUT` | Seconds to wait for the AI model. | 280 |
| `MAX_OUTPUT_TOKENS` | Output limit for one reading. | 8000 |
| `SECRET_KEY` | Signs the sign-in cookie. Derived from the password and key if empty. | none |

## Deploying

See [docs/DEPLOY_HOSTGATOR.md](docs/DEPLOY_HOSTGATOR.md) for shared cPanel hosting.

## Privacy

The PDF never leaves the browser as a file. The page images you choose to read are posted to your server and
forwarded to the Anthropic API; nothing is stored on the server. Do not read drawings you are not allowed to
send to a third-party service.

## Layout

```
index.html, static/        the page, its script and styles, and a vendored copy of PDF.js
index.cgi                  CGI entry point (shared hosting)
passenger_wsgi.py          entry point for hosts that use Passenger
app/server.py              routes: health, login, templates, extract, generate
app/extract.py             the Claude API request and response handling
app/build.py, browser.py   model building shared by the server and the browser preview
app/ifc/                   dependency-free IFC2x3 writer and modelling helpers
app/templates/             one module per structure type, plus the STAAD exporter
tests/                     unit tests (python3 -m unittest discover -s tests)
tools/                     local server; IFC validation with IfcOpenShell (developer only)
```

## Tests

```
python3 -m unittest discover -s tests
pip install ifcopenshell && VALIDATE_IFC=1 python3 -m unittest discover -s tests
```

The second line also validates the generated IFC files against the schema.

## Adding a structure type

Add a module in `app/templates/` with `ID`, `TITLE`, `SUMMARY`, `UNIT`, `LOOK_FOR`, a `PARAMS` list and a
`build(params, meta)` function that returns IFC text, then register it in `app/templates/__init__.py`. The
form, the AI prompt and the tool schema are generated from `PARAMS`.

## Third-party code

`static/vendor/pdfjs` is PDF.js 6.2.108 (Apache-2.0), unmodified.
