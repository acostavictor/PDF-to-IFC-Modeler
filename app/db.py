"""SQLite storage for saved models and the reusable component library. Standard library only."""
import contextlib
import json
import os
import sqlite3
import time

from . import scene as scene_mod

SEED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed.json")


class NotFound(Exception):
    pass


def default_path():
    return os.path.join(os.path.expanduser("~"), ".pdf2ifc", "pdf2ifc.sqlite3")


class Store(object):
    def __init__(self, path, seed=True):
        self.path = path
        folder = os.path.dirname(path)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)
            try:
                os.chmod(folder, 0o700)
            except OSError:
                pass
        with self._conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS models (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, project TEXT NOT NULL DEFAULT '',
                    structure_type TEXT NOT NULL DEFAULT '', units TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
                    is_example INTEGER NOT NULL DEFAULT 0, pieces INTEGER NOT NULL DEFAULT 0, scene TEXT NOT NULL,
                    created REAL NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS library (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, category TEXT NOT NULL DEFAULT 'Other',
                    description TEXT NOT NULL DEFAULT '', tags TEXT NOT NULL DEFAULT '', units TEXT NOT NULL,
                    type TEXT NOT NULL, is_seed INTEGER NOT NULL DEFAULT 0, item TEXT NOT NULL,
                    created REAL NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)
            if seed and not c.execute("SELECT 1 FROM meta WHERE key='seeded'").fetchone():
                self._seed(c)

    @contextlib.contextmanager
    def _conn(self):
        """One short-lived connection per operation: commit on success, roll back on error, always close."""
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _seed(self, c):
        with open(SEED, "r") as fh:
            data = json.load(fh)
        now = time.time()
        for entry in data["library"]:
            c.execute("INSERT INTO library (name, category, description, tags, units, type, is_seed, item, created, updated) "
                      "VALUES (?,?,?,?,?,?,1,?,?,?)", (entry["name"], entry["category"], entry["description"], entry["tags"],
                                                       entry["units"], entry["item"]["type"], json.dumps(entry["item"]), now, now))
        for sc in data["models"]:
            c.execute("INSERT INTO models (name, project, structure_type, units, description, is_example, pieces, scene, created, updated) "
                      "VALUES (?,?,?,?,?,1,?,?,?,?)", (sc["name"], sc["project"], sc["structure_type"], sc["units"], sc["description"],
                                                       scene_mod.count_parts(sc), json.dumps(sc), now, now))
        c.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('seeded', ?)", (str(now),))

    # ---- models -----------------------------------------------------------------------------
    def list_models(self, query=""):
        like = "%" + query.strip().lower() + "%"
        with self._conn() as c:
            rows = c.execute("SELECT id, name, project, structure_type, units, description, is_example, pieces, updated FROM models "
                             "WHERE lower(name || ' ' || project || ' ' || structure_type || ' ' || description) LIKE ? "
                             "ORDER BY is_example, updated DESC", (like,)).fetchall()
        return [dict(r) for r in rows]

    def get_model(self, model_id):
        with self._conn() as c:
            row = c.execute("SELECT id, is_example, updated, scene FROM models WHERE id=?", (model_id,)).fetchone()
        if not row:
            raise NotFound("That model is no longer in the database.")
        return {"id": row["id"], "is_example": row["is_example"], "updated": row["updated"], "scene": json.loads(row["scene"])}

    def save_model(self, raw_scene, model_id=None):
        sc = scene_mod.normalise(raw_scene)
        if not sc["name"]:
            raise scene_mod.SceneError("Give the model a name before saving it.")
        now = time.time()
        vals = (sc["name"], sc["project"], sc["structure_type"], sc["units"], sc["description"], scene_mod.count_parts(sc), json.dumps(sc), now)
        with self._conn() as c:
            if model_id is not None:
                cur = c.execute("UPDATE models SET name=?, project=?, structure_type=?, units=?, description=?, pieces=?, scene=?, "
                                "updated=?, is_example=0 WHERE id=?", vals + (model_id,))
                if cur.rowcount == 0:
                    raise NotFound("That model is no longer in the database.")
                return model_id
            cur = c.execute("INSERT INTO models (name, project, structure_type, units, description, pieces, scene, updated, created) "
                            "VALUES (?,?,?,?,?,?,?,?,?)", vals + (now,))
            return cur.lastrowid

    def delete_model(self, model_id):
        with self._conn() as c:
            if c.execute("DELETE FROM models WHERE id=?", (model_id,)).rowcount == 0:
                raise NotFound("That model is no longer in the database.")

    # ---- library ----------------------------------------------------------------------------
    def list_library(self, query=""):
        like = "%" + query.strip().lower() + "%"
        with self._conn() as c:
            rows = c.execute("SELECT id, name, category, description, tags, units, type, is_seed, updated FROM library "
                             "WHERE lower(name || ' ' || category || ' ' || description || ' ' || tags) LIKE ? "
                             "ORDER BY category, name", (like,)).fetchall()
        return [dict(r) for r in rows]

    def get_library(self, item_id):
        with self._conn() as c:
            row = c.execute("SELECT * FROM library WHERE id=?", (item_id,)).fetchone()
        if not row:
            raise NotFound("That library item is no longer in the database.")
        out = dict(row)
        out["item"] = json.loads(out["item"])
        return out

    def save_library(self, data, item_id=None):
        name = str(data.get("name") or "").strip()[:160]
        if not name:
            raise scene_mod.SceneError("Give the library item a name.")
        units = str(data.get("units") or "ft")
        if units not in scene_mod.UNITS:
            raise scene_mod.SceneError("Units must be ft, m or mm.")
        raw = dict(data.get("item") or {})
        raw["source"], raw["library_item"] = "library", name
        item = scene_mod.normalise_component(raw, units)
        category = data.get("category") if data.get("category") in scene_mod.LIBRARY_CATEGORIES else "Other"
        now = time.time()
        vals = (name, category, str(data.get("description") or "")[:600], str(data.get("tags") or "")[:200], units, item["type"],
                json.dumps(item), now)
        with self._conn() as c:
            if item_id is not None:
                cur = c.execute("UPDATE library SET name=?, category=?, description=?, tags=?, units=?, type=?, item=?, updated=?, "
                                "is_seed=0 WHERE id=?", vals + (item_id,))
                if cur.rowcount == 0:
                    raise NotFound("That library item is no longer in the database.")
                return item_id
            cur = c.execute("INSERT INTO library (name, category, description, tags, units, type, item, updated, created) "
                            "VALUES (?,?,?,?,?,?,?,?,?)", vals + (now,))
            return cur.lastrowid

    def delete_library(self, item_id):
        with self._conn() as c:
            if c.execute("DELETE FROM library WHERE id=?", (item_id,)).rowcount == 0:
                raise NotFound("That library item is no longer in the database.")

    def counts(self):
        with self._conn() as c:
            return {"models": c.execute("SELECT count(*) FROM models").fetchone()[0],
                    "library": c.execute("SELECT count(*) FROM library").fetchone()[0]}
