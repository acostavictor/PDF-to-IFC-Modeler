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

## 5. Turn on HTTPS

Make sure the domain has an SSL certificate (cPanel > SSL/TLS Status) and open the app with `https://`. The
sign-in cookie is only marked secure over HTTPS.

## 6. Test

1. Open `https://yourdomain/ifc/api/health`. You should see JSON with `"ok": true`.
   If you get a 404, try `https://yourdomain/ifc/index.cgi/api/health`; the page falls back to that address
   by itself when URL rewriting is off.
2. Open `https://yourdomain/ifc/`, sign in, pick a structure type and press **Download IFC model** without
   changing anything. That proves the server can build models.
3. Load a PDF, tick one page, and press **Read drawings with AI**. That proves the server can reach the
   Anthropic API.

## If something fails

| Symptom | Likely cause |
|---|---|
| 500 error on `/api/health` | Wrong Python path on line 1 of `index.cgi`, wrong permissions, or Windows line endings. Check cPanel > Errors. |
| The page loads but says the server part is not answering | CGI is not enabled for the folder. Confirm `.htaccess` was uploaded (it is a hidden file). |
| Drawing viewer stays blank | `.mjs` or `.wasm` files served with the wrong type. `.htaccess` sets these; confirm it is in place. |
| AI reading ends with a timeout or 5xx after a minute or two | The host stopped a long request. Read fewer pages at a time or use a lower detail level. |
| "Could not reach the Claude API" | Outbound HTTPS is blocked, or the server's Python has old TLS certificates. Ask HostGator support. |
| 413 or "Upload is larger than" | Too many images in one reading. Fewer pages or less detail. |

## Notes

- `.htaccess` blocks web access to `app/`, `tests/`, `tools/`, `docs/`, `.git/`, `*.py`, `*.md` and
  `config*.json`.
- Nothing is written to disk by the app, so no folder needs to be writable.
- For a VPS, the same code runs under any WSGI server through `app.server:application`.
