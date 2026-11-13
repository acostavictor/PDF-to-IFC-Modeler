# Deploying on HostGator shared hosting (cPanel)

HostGator's compatibility page lists Python 3, CGI, SSH and a Git client for shared plans, and lists WSGI as
not available on them. The app is therefore deployed as a CGI script. These steps have not been run on a
HostGator account; treat them as a checklist and expect to adjust paths.

## What you need first

| Item | Where |
|---|---|
| An Anthropic API key with credit on the account | https://console.anthropic.com/ > API keys |
| A shell on the hosting account | cPanel > Terminal, or SSH (HostGator: enable SSH access in the customer portal) |
| An SSL certificate on the domain | cPanel > SSL/TLS Status |

## 1. Get the code onto the server

Pick a folder under `public_html`, for example `public_html/ifc`. In the shell:

```
cd ~/public_html
git clone https://github.com/acostavictor/PDF-to-IFC-Modeler.git ifc
```

- A private repository needs a deploy key or a personal access token for `git clone`.
- **cPanel's Git Version Control**, if your plan shows it, does the same from a form: clone URL as above,
  repository path `public_html/ifc`.
- **Without Git:** on GitHub choose Code > Download ZIP, upload it with File Manager and extract it. Turn on
  "Show hidden files" in File Manager so that `.htaccess` is not left behind.

## 2. Run the set-up script

```
cd ~/public_html/ifc
python3 tools/setup_server.py
```

It asks for two things, neither of which is shown as you type:

1. **Your Anthropic API key.** Paste it and press Enter.
2. **A password for signing in to the app.** Type one of 10 characters or more, or press Enter and it makes
   one and shows it once.

It writes them to `~/.pdf2ifc/config.json`, readable only by your hosting account and outside the web
folder. Then it checks the machine and prints one line per check:

| Check | What a failure means |
|---|---|
| Python version, SQLite, HTTPS support | The host's Python is too old or incomplete. Ask support which Python 3 to use and put that path on line 1 of `index.cgi`. |
| index.cgi interpreter, permissions, line endings | Repaired automatically where possible (`chmod 755`, Unix line endings). |
| Database | The app could not create `~/.pdf2ifc/pdf2ifc.sqlite3`. |
| Web entry point | `index.cgi` did not answer when run the way the web server runs it. |
| Claude API connection | The key was refused, the model is not available to the key, or the server cannot reach `api.anthropic.com`. The message says which. This check is free. |

Run it again whenever you like; it keeps what is already set. `python3 tools/setup_server.py --check` checks
without changing anything.

### Prove a full AI run

```
python3 tools/setup_server.py --check --ai-test
```

This sends one small real request (a described timber pier, no drawings), billed to your key, and prints
the components Claude returned and how long it took. If this passes, the server side of AI works.

## 3. Open the app

1. Open `https://yourdomain/ifc/` and sign in with the password.
2. In step 1 of the page press **Test AI connection**. It should say the connection works.
3. Press **Open**, open an example and press **Download IFC**: the server can build models.
4. Type a one-line description and press **Build model with AI**: the full path works from the browser.
5. Then try a PDF with one or two pages before a whole set.

If the page says the server part is not answering, open `https://yourdomain/ifc/api/health`. JSON with
`"ok": true` means the server is fine. A 404 there but JSON at `https://yourdomain/ifc/index.cgi/api/health`
means URL rewriting is off; the page uses that second address by itself.

## Without a shell

If you cannot get a Terminal or SSH:

1. Upload the files as in step 1 (ZIP route).
2. In File Manager set `index.cgi` to permission 755, and the `ifc` folder to 755.
3. In your home folder (one level above `public_html`) create a folder `.pdf2ifc` with permission 700, and in
   it a file `config.json` with permission 600 containing:
   ```
   {
     "ANTHROPIC_API_KEY": "your key",
     "APP_PASSWORD": "your long password"
   }
   ```
4. Open the app, sign in and press **Test AI connection**.

## Backing up and updating

- **Back up** by copying `~/.pdf2ifc/pdf2ifc.sqlite3` (File Manager, or `cp` in the shell). To restore, copy
  it back.
- **Update** with `cd ~/public_html/ifc && git pull`. This does not touch the database or the config.
- The starter library and examples are added once, when the database is created. Deleting one is permanent;
  to get them all back, move the database file aside and let the app create a new one.
- **Change the key or password** by editing `~/.pdf2ifc/config.json`. Changing the password signs everyone
  out.

## If something fails

| Symptom | Likely cause |
|---|---|
| 500 error on `/api/health` | Wrong Python path on line 1 of `index.cgi`, wrong permissions, or Windows line endings. Run the set-up script; check cPanel > Errors. |
| The page loads but says the server part is not answering | CGI is not enabled for the folder. Confirm `.htaccess` was uploaded (it is a hidden file). |
| The page says saved models stay in this browser only | `APP_PASSWORD` is not set, or the database could not be opened; `api/health` shows which. |
| "The Anthropic API key was not accepted" | The key was mistyped, revoked, or belongs to an account without credit. |
| "This API key cannot use the model" | Set `ANTHROPIC_MODEL` in the config to a model your account has. |
| "Could not reach the Claude API" | Outbound HTTPS is blocked, or the server's Python has old TLS certificates. Ask HostGator support. |
| An AI run stops after a fixed time with a 5xx page or "Request failed" | The host's time limit for one request. The app sends a keep-alive every 10 seconds, which avoids idle limits but not a hard cap. Read fewer pages at a time, or lower the detail. |
| "The reply was cut off before it finished" | The structure needs more output than allowed. Raise `MAX_OUTPUT_TOKENS`, or build it in parts using **Add to the model on screen**. |
| 413 or "Upload is larger than" | Too many images in one run. Fewer pages or less detail. |
| "database is locked" | Two saves collided on a slow disk. Try again. If it persists, the home folder may be on a network file system that SQLite handles poorly; ask support. |
| Drawing viewer stays blank | `.mjs` or `.wasm` files served with the wrong type. `.htaccess` sets these; confirm it is in place. |
| The 3D preview is blank | WebGL is off in the browser. The component list and the IFC export still work. |

## Notes

- `.htaccess` blocks web access to `app/`, `tests/`, `tools/`, `docs/`, `.git/`, `*.py`, `*.md`,
  `*.sqlite3` and `config*.json`.
- The only things the app writes are the database and config in `~/.pdf2ifc/`. Nothing under `public_html`
  needs to be writable.
- Each request opens the database, does one thing and closes it, which suits CGI. SQLite is comfortable
  with one person or a small team; it is not meant for many people saving at once.
- For a VPS, the same code runs under any WSGI server through `app.server:application`.

## Trying AI on your own computer first

The server version also runs on a PC or Mac with Python 3 installed, which is the quickest way to see how
well the AI reads your drawings before touching the host:

```
git clone https://github.com/acostavictor/PDF-to-IFC-Modeler.git
cd PDF-to-IFC-Modeler
python3 tools/setup_server.py
python3 tools/dev_server.py
```

Then open http://localhost:8000/. On Windows use `py` in place of `python3`. The database it creates is
local to that computer.
