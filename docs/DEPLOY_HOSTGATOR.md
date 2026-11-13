# Deploying on HostGator shared hosting (cPanel)

HostGator's compatibility page lists Python 3, CGI, SSH and a Git client for shared plans, and lists WSGI as
not available on them. The app is therefore deployed as a CGI script. These steps have not been run on a
HostGator account; treat them as a checklist and expect to adjust paths.

## 1. Check Python

Open the cPanel Terminal, or connect over SSH, and run:

```
python3 --version
which python3
```

You need 3.6 or newer. If `python3` is missing or older, ask HostGator support which Python 3 path to use and
put that path on the first line of `index.cgi`.

The database needs Python's built-in `sqlite3` module. Check it with:

```
python3 -c "import sqlite3; print(sqlite3.sqlite_version)"
```

If that prints an error, the app still runs but keeps saved models in each browser instead of on the server;
ask HostGator support for a Python build that includes SQLite.

## 2. Get the code onto the server

Pick a folder under `public_html`, for example `public_html/ifc`.

- **With Git over SSH:** `cd ~/public_html && git clone https://github.com/acostavictor/PDF-to-IFC-Modeler.git ifc`.
  To update later: `cd ~/public_html/ifc && git pull`. A private repository needs a deploy key or token.
- **With cPanel's Git Version Control, if your plan shows it:** create a repository from the same clone URL
  with the repository path set to that folder, then use Update from Remote after each push.
- **Without Git:** download the repository as a zip from GitHub and upload it with File Manager.

## 3. Set permissions

```
cd ~/public_html/ifc
chmod 755 index.cgi
find . -type d -exec chmod 755 {} \;
```

CGI scripts are refused if they or their folder are writable by group or others.

## 4. Add the configuration, outside the web folder

```
mkdir -p ~/.pdf2ifc && chmod 700 ~/.pdf2ifc
cp ~/public_html/ifc/config.example.json ~/.pdf2ifc/config.json
chmod 600 ~/.pdf2ifc/config.json
```

Edit `~/.pdf2ifc/config.json` and set `ANTHROPIC_API_KEY` and a long `APP_PASSWORD`. Never commit this file.

The password matters: on a public server the shared database and AI stay switched off until `APP_PASSWORD`
is set.

The database file is created on first use at `~/.pdf2ifc/pdf2ifc.sqlite3`, in that same private folder, so
it is never reachable from the web. Set `DB_PATH` in the config file only if you want it somewhere else, and
keep it outside `public_html`.

## 5. Turn on HTTPS

Make sure the domain has an SSL certificate (cPanel > SSL/TLS Status) and open the app with `https://`. The
sign-in cookie is only marked secure over HTTPS.

## 6. Test

1. Open `https://yourdomain/ifc/api/health`. You should see JSON with `"ok": true` and
   `"login_required": true`.
   If you get a 404, try `https://yourdomain/ifc/index.cgi/api/health`; the page falls back to that address
   by itself when URL rewriting is off.
2. Open `https://yourdomain/ifc/` and sign in. Reload `api/health`: it should now show `"storage": "server"`
   and `"db_counts"` with 6 models and 26 library items. If `"db_error"` has text, the database could not be
   opened; the text says why.
3. Press **Open**, open an example, and press **Download IFC**. That proves the server can build models.
4. Change something, press **Save**, sign in from another browser and find the model under **Open**. That
   proves the database is shared.
5. Type a one-line description in step 1 of the page and press **Build model with AI**. That proves the
   server can reach the Anthropic API. Then try it with a PDF and one or two pages.

## Backing up and updating

- **Back up** by copying `~/.pdf2ifc/pdf2ifc.sqlite3` (cPanel File Manager, or `cp` over SSH). To restore,
  copy it back. Updating the app with `git pull` does not touch it.
- The starter library and examples are added once, when the database is created. Deleting one is permanent;
  to get them all back, move the database file aside and let the app create a new one.

## If something fails

| Symptom | Likely cause |
|---|---|
| 500 error on `/api/health` | Wrong Python path on line 1 of `index.cgi`, wrong permissions, or Windows line endings. Check cPanel > Errors. |
| The page loads but says the server part is not answering | CGI is not enabled for the folder. Confirm `.htaccess` was uploaded (it is a hidden file). |
| Drawing viewer stays blank | `.mjs` or `.wasm` files served with the wrong type. `.htaccess` sets these; confirm it is in place. |
| AI ends with a timeout or 5xx after a minute or two | The host stopped a long request. Read fewer pages at a time or use a lower detail level. |
| "The reply was cut off before it finished" | The structure needs more output than allowed. Raise `MAX_OUTPUT_TOKENS`, or build it in parts using **Add to the model on screen**. |
| The page says saved models stay in this browser only | `APP_PASSWORD` is not set, or the database could not be opened; `api/health` shows which. |
| "database is locked" | Two saves collided on a slow disk. Try again. If it persists, the home folder may be on a network file system that SQLite handles poorly; ask support. |
| The 3D preview is blank | WebGL is off in the browser. The component list and the IFC export still work. |
| "Could not reach the Claude API" | Outbound HTTPS is blocked, or the server's Python has old TLS certificates. Ask HostGator support. |
| 413 or "Upload is larger than" | Too many images in one run. Fewer pages or less detail. |

## Notes

- `.htaccess` blocks web access to `app/`, `tests/`, `tools/`, `docs/`, `.git/`, `*.py`, `*.md`,
  `*.sqlite3` and `config*.json`.
- The only thing the app writes is the database file in `~/.pdf2ifc/`. Nothing under `public_html` needs to
  be writable.
- Each request opens the database, does one thing and closes it, which suits CGI. SQLite is comfortable
  with one person or a small team; it is not meant for many people saving at once.
- For a VPS, the same code runs under any WSGI server through `app.server:application`.
