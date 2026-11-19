"""Alle mot Erling – a small "everyone against one" quiz platform,
inspired by the Danish TV show "Alle mod 1".

Run locally:     python app.py   (then open http://localhost:5000)
Run on a server: gunicorn -c gunicorn.conf.py app:app   (see README.md)

Configuration (environment variables):
    QUIZ_DB        path of the SQLite database        (default: quiz.db next to app.py)
    PUBLIC_URL     address players use, for QR codes  (e.g. https://quiz.example.com)
    HOST_USER      host login user name               (default: gamemaster)
    HOST_PASSWORD  host login password                (default: honestmistake)
    PORT, DEBUG    only for `python app.py`           (default: 5000, off)

The game is driven by the host from the showcase page. A game moves through
these phases (stored on the game row):

    lobby_one  – showcase shows the QR code for Erling
    lobby      – showcase shows the QR code for teams and who has joined
    question   – question q_index is open; Erling and the teams answer on their phones
    reveal     – answers are locked; reveal_step 1 = correct answer,
                 2 = Erling's answer + range to beat, 3 = teams' average + point
    final      – total score

Each question gives one point to whoever is closest to the correct answer:
Erling, or the average of all team answers.

Erling is always the one playing against everyone (SOLO_NAME). In the code
that player is called "one".
"""
import io
import json
import math
import os
import secrets
import socket
import sqlite3
import threading
from urllib.parse import urlsplit

import qrcode
import qrcode.image.svg
from flask import Flask, Response, abort, g, jsonify, request, send_from_directory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("QUIZ_DB", os.path.join(BASE_DIR, "quiz.db"))
# The address players reach the site on. QR codes use it when set; otherwise
# they are built from the address the host's browser used (see public_base_url).
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").strip().rstrip("/")

app = Flask(__name__, static_folder="static", static_url_path="")

SCHEMA_VERSION = 2
SCHEMA = """
CREATE TABLE IF NOT EXISTS questions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    text       TEXT    NOT NULL,
    answer     REAL    NOT NULL,
    unit       TEXT    NOT NULL DEFAULT '',
    position   INTEGER NOT NULL DEFAULT 0,      -- order in the quiz (lowest first)
    created_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS games (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    one_name     TEXT    NOT NULL,              -- the one playing against everyone (Erling)
    one_token    TEXT    NOT NULL,              -- secret for their private page
    one_joined   INTEGER NOT NULL DEFAULT 0,
    phase        TEXT    NOT NULL DEFAULT 'lobby_one',
    q_index      INTEGER NOT NULL DEFAULT 0,
    reveal_step  INTEGER NOT NULL DEFAULT 0,
    question_ids TEXT    NOT NULL DEFAULT '[]', -- JSON, snapshot taken when the quiz starts
    created_at   TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS teams (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id    INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    name       TEXT    NOT NULL,
    token      TEXT    NOT NULL UNIQUE,
    created_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (game_id, name COLLATE NOCASE)
);
CREATE TABLE IF NOT EXISTS answers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id     INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    player      TEXT    NOT NULL,               -- 'one' or 'team:<id>'
    value       REAL    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (game_id, question_id, player)
);
-- Optional picture per question. Kept apart from the questions so loading
-- questions (on every state fetch) doesn't read the image data.
CREATE TABLE IF NOT EXISTS question_images (
    question_id INTEGER PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
    mime        TEXT    NOT NULL,
    data        BLOB    NOT NULL,
    version     TEXT    NOT NULL                -- changes with the picture, for caching
);
"""

SEED_QUESTIONS = [
    ("Hvor høy er Galdhøpiggen, Norges høyeste fjell?", 2469, "moh."),
    ("Hvilket år ble Oslo lufthavn Gardermoen åpnet?", 1998, ""),
    ("Hvor lang er Lærdalstunnelen, verdens lengste veitunnel?", 24.5, "km"),
]

PHASES = ("lobby_one", "lobby", "question", "reveal", "final")
SOLO_NAME = "Erling"  # the one playing against everyone, in every game

# Keeps curious players out of the host pages. Not real security: the default
# is in the source code, and without HTTPS it is sent unencrypted.
HOST_USER = os.environ.get("HOST_USER", "gamemaster")
HOST_PASSWORD = os.environ.get("HOST_PASSWORD", "honestmistake")
HOST_PAGES = {"/create.html", "/showcase.html"}
HOST_API = {"/api/game", "/api/game/next", "/api/links"}  # plus /api/questions… and /api/image/…
LAST_REVEAL_STEP = 3
QUESTION_ORDER = "position, id"  # SQL ORDER BY for the saved questions (the order they are played in)

# Pictures for questions. No SVG: it can contain scripts.
IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024
app.config["MAX_CONTENT_LENGTH"] = MAX_IMAGE_BYTES + 64 * 1024


# ------------------------------------------------------------------ host password
def is_host():
    auth = request.authorization
    return bool(auth and auth.username is not None and auth.password is not None
                and secrets.compare_digest(auth.username, HOST_USER)
                and secrets.compare_digest(auth.password, HOST_PASSWORD))


def ask_for_host_password():
    return Response("Denne siden krever vertspassordet.", 401,
                    {"WWW-Authenticate": 'Basic realm="Alle mot Erling host", charset="UTF-8"'})


@app.before_request
def require_host_password():
    """Ask for the host login (browser's built-in login prompt) on the host
    pages and on the API calls only they use."""
    path = request.path
    if not (path in HOST_PAGES or path in HOST_API
            or path.startswith("/api/questions") or path.startswith("/api/image/")):
        return None
    return None if is_host() else ask_for_host_password()


# ------------------------------------------------------------------ live updates
class Notifier:
    """Wakes up clients waiting on /api/events when something changes.

    Two counters: "game" changes when the game moves to another step (all
    phones care), "all" changes on anything – also joins and answers (only
    the showcase cares, for its live counters).

    Lives in this process, so run the app as a single process.
    """

    def __init__(self):
        self.cond = threading.Condition()
        self.versions = {"game": 0, "all": 0}

    def bump(self, game=False):
        with self.cond:
            self.versions["all"] += 1
            if game:
                self.versions["game"] += 1
            self.cond.notify_all()

    def wait(self, scope, seen, timeout):
        with self.cond:
            self.cond.wait_for(lambda: self.versions[scope] != seen, timeout)
            return self.versions[scope]


notifier = Notifier()


# --------------------------------------------------------------------------- db
def get_db():
    if "db" not in g:
        # timeout: wait up to 10 s for another thread's write instead of failing.
        g.db = sqlite3.connect(DB_PATH, timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def new_token():
    return secrets.token_urlsafe(12)


def init_db():
    with sqlite3.connect(DB_PATH) as db:
        # WAL: readers don't block the writer, so many simultaneous answers
        # and state fetches work well. The setting is stored in the file.
        db.execute("PRAGMA journal_mode = WAL")
        if db.execute("PRAGMA user_version").fetchone()[0] < SCHEMA_VERSION:
            # Version 1 used multiple-choice questions. Keep that data around
            # as *_v1 tables instead of deleting it, and start fresh.
            existing = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in ("answers", "games", "questions"):
                if table in existing:
                    db.execute(f"ALTER TABLE {table} RENAME TO {table}_v1")
            db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        db.executescript(SCHEMA)
        columns = {r[1] for r in db.execute("PRAGMA table_info(questions)")}
        if "position" not in columns:
            # Added after version 2: questions get an order the host can change.
            # Existing questions keep their old order (by id).
            db.execute("ALTER TABLE questions ADD COLUMN position INTEGER NOT NULL DEFAULT 0")
            db.execute("UPDATE questions SET position = id")
        if db.execute("SELECT COUNT(*) FROM questions").fetchone()[0] == 0:
            db.executemany("INSERT INTO questions (text, answer, unit, position) VALUES (?, ?, ?, ?)",
                           [(*q, i) for i, q in enumerate(SEED_QUESTIONS, 1)])
        if db.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 0:
            db.execute("INSERT INTO games (one_name, one_token) VALUES (?, ?)", (SOLO_NAME, new_token()))


def current_game():
    return get_db().execute("SELECT * FROM games ORDER BY id DESC LIMIT 1").fetchone()


def game_questions(game):
    """The questions of a running game, in the order fixed when it started."""
    ids = json.loads(game["question_ids"])
    if not ids:
        return []
    rows = get_db().execute(
        f"SELECT * FROM questions WHERE id IN ({','.join('?' * len(ids))})", ids
    ).fetchall()
    by_id = {r["id"]: r for r in rows}
    return [by_id[i] for i in ids if i in by_id]


def parse_number(raw):
    try:
        value = float("".join(str(raw).split()).replace(",", "."))
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def check_one_token(game, token):
    return token is not None and secrets.compare_digest(str(token), game["one_token"])


def team_by_token(game, token):
    if not token:
        return None
    return get_db().execute(
        "SELECT * FROM teams WHERE token = ? AND game_id = ?", (str(token), game["id"])
    ).fetchone()


def question_result(game, q):
    rows = get_db().execute(
        "SELECT player, value FROM answers WHERE game_id = ? AND question_id = ?",
        (game["id"], q["id"]),
    ).fetchall()
    one = next((r["value"] for r in rows if r["player"] == "one"), None)
    team_values = [r["value"] for r in rows if r["player"] != "one"]
    avg = sum(team_values) / len(team_values) if team_values else None
    correct = q["answer"]
    d_one = abs(one - correct) if one is not None else None
    d_crowd = abs(avg - correct) if avg is not None else None
    if d_one is None and d_crowd is None:
        winner = None
    elif d_crowd is None:
        winner = "one"
    elif d_one is None:
        winner = "crowd"
    elif math.isclose(d_one, d_crowd, rel_tol=1e-9, abs_tol=1e-9):
        winner = "draw"
    else:
        winner = "one" if d_one < d_crowd else "crowd"
    return {
        "text": q["text"], "unit": q["unit"], "correct": correct,
        "one": one, "oneDistance": d_one,
        "average": avg, "averageDistance": d_crowd, "teamAnswers": len(team_values),
        "teamValues": sorted(team_values),  # anonymous: values only, no team names
        "winner": winner,
    }


# ------------------------------------------------------------------- questions
def image_url(question_id):
    """URL of a question's picture, or None if it has none. The version in
    the URL changes with the picture, so browsers may cache it."""
    row = get_db().execute("SELECT version FROM question_images WHERE question_id = ?",
                           (question_id,)).fetchone()
    return f"/api/image/{question_id}?v={row['version']}" if row else None


def question_dict(row):
    return {"id": row["id"], "text": row["text"], "answer": row["answer"], "unit": row["unit"],
            "image": image_url(row["id"])}


@app.get("/api/questions")
def list_questions():
    rows = get_db().execute(f"SELECT * FROM questions ORDER BY {QUESTION_ORDER}").fetchall()
    return jsonify([question_dict(r) for r in rows])


@app.put("/api/questions/order")
def reorder_questions():
    """Set the order of the questions. The body is the list of all question
    ids, in the new order."""
    ids = request.get_json(silent=True)
    if not isinstance(ids, list) or not all(type(i) is int for i in ids):
        abort(400, "Forventet en liste med spørsmåls-id-er")
    db = get_db()
    existing = {r["id"] for r in db.execute("SELECT id FROM questions")}
    if len(ids) != len(set(ids)) or set(ids) != existing:
        abort(409, "Spørsmålene er endret i mellomtiden – last siden på nytt")
    db.executemany("UPDATE questions SET position = ? WHERE id = ?",
                   [(pos, qid) for pos, qid in enumerate(ids, 1)])
    db.commit()
    notifier.bump()
    return "", 204


@app.post("/api/questions")
def create_question():
    data = request.get_json(silent=True) or {}
    text = str(data.get("text", "")).strip()
    unit = str(data.get("unit", "")).strip()[:20]
    answer = parse_number(data.get("answer", ""))
    if not text:
        abort(400, "Spørsmålet mangler tekst")
    if answer is None:
        abort(400, "Svaret må være et tall")
    db = get_db()
    cur = db.execute(
        "INSERT INTO questions (text, answer, unit, position) "
        "VALUES (?, ?, ?, (SELECT COALESCE(MAX(position), 0) + 1 FROM questions))",
        (text, answer, unit),
    )
    db.commit()
    notifier.bump()
    row = db.execute("SELECT * FROM questions WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(question_dict(row)), 201


@app.delete("/api/questions/<int:qid>")
def delete_question(qid):
    db = get_db()
    db.execute("DELETE FROM questions WHERE id = ?", (qid,))
    db.commit()
    notifier.bump()
    return "", 204


@app.put("/api/questions/<int:qid>/image")
def set_question_image(qid):
    """Add or replace a question's picture. The body is the image file itself,
    with its type as Content-Type."""
    mime = (request.mimetype or "").lower()
    if mime not in IMAGE_TYPES:
        abort(400, "Bildet må være JPEG, PNG, GIF eller WebP")
    data = request.get_data()
    if not data:
        abort(400, "Bildefilen er tom")
    if len(data) > MAX_IMAGE_BYTES:
        abort(413)
    db = get_db()
    if db.execute("SELECT 1 FROM questions WHERE id = ?", (qid,)).fetchone() is None:
        abort(404)
    db.execute(
        """INSERT INTO question_images (question_id, mime, data, version) VALUES (?, ?, ?, ?)
           ON CONFLICT (question_id) DO UPDATE
           SET mime = excluded.mime, data = excluded.data, version = excluded.version""",
        (qid, mime, data, secrets.token_hex(4)),
    )
    db.commit()
    notifier.bump()
    row = db.execute("SELECT * FROM questions WHERE id = ?", (qid,)).fetchone()
    return jsonify(question_dict(row))


@app.delete("/api/questions/<int:qid>/image")
def delete_question_image(qid):
    db = get_db()
    db.execute("DELETE FROM question_images WHERE question_id = ?", (qid,))
    db.commit()
    notifier.bump()
    return "", 204


@app.get("/api/image/<int:qid>")
def question_image(qid):
    """A question's picture. Only shown on the big screen, so host only."""
    row = get_db().execute("SELECT mime, data FROM question_images WHERE question_id = ?",
                           (qid,)).fetchone()
    if row is None:
        abort(404)
    return Response(row["data"], mimetype=row["mime"], headers={
        "Cache-Control": "private, max-age=86400",  # the URL changes with the picture
        "X-Content-Type-Options": "nosniff",
    })


# ---------------------------------------------------------------- game control
@app.post("/api/game")
def new_game():
    db = get_db()
    db.execute("INSERT INTO games (one_name, one_token) VALUES (?, ?)", (SOLO_NAME, new_token()))
    db.commit()
    notifier.bump(game=True)
    return state()


@app.post("/api/game/next")
def next_step():
    """Advance the game one step. The client sends the state it is looking at
    (`from`), so a double click can't skip a step."""
    data = request.get_json(silent=True) or {}
    seen = data.get("from") or {}
    game = current_game()
    if (seen.get("phase"), seen.get("qIndex"), seen.get("revealStep")) != (
        game["phase"], game["q_index"], game["reveal_step"]
    ):
        return state()  # someone else already advanced – just return the fresh state

    db = get_db()
    phase, idx, step = game["phase"], game["q_index"], game["reveal_step"]
    question_ids = game["question_ids"]
    if phase == "lobby_one":
        phase = "lobby"
    elif phase == "lobby":
        ids = [r["id"] for r in db.execute(f"SELECT id FROM questions ORDER BY {QUESTION_ORDER}")]
        if not ids:
            abort(400, "Lag noen spørsmål først")
        phase, idx, step, question_ids = "question", 0, 0, json.dumps(ids)
    elif phase == "question":
        phase, step = "reveal", 1
    elif phase == "reveal" and step < LAST_REVEAL_STEP:
        step += 1
    elif phase == "reveal":
        if idx + 1 < len(game_questions(game)):
            phase, idx, step = "question", idx + 1, 0
        else:
            phase, step = "final", 0
    db.execute(
        "UPDATE games SET phase = ?, q_index = ?, reveal_step = ?, question_ids = ? WHERE id = ?",
        (phase, idx, step, question_ids, game["id"]),
    )
    db.commit()
    notifier.bump(game=True)
    return state()


# ---------------------------------------------------------------- joining
@app.post("/api/one/join")
def one_join():
    data = request.get_json(silent=True) or {}
    game = current_game()
    if not check_one_token(game, data.get("token")):
        abort(403, f"Denne lenken for {game['one_name']} gjelder ikke for dette spillet")
    db = get_db()
    db.execute("UPDATE games SET one_joined = 1 WHERE id = ?", (game["id"],))
    db.commit()
    notifier.bump()
    return jsonify({"ok": True, "oneName": game["one_name"]})


@app.post("/api/teams")
def join_team():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()[:30]
    game = current_game()
    if not name:
        abort(400, "Lagnavn mangler")
    if game["phase"] == "final":
        abort(409, "Dette spillet er over – vent til verten starter et nytt")
    if name.casefold() == game["one_name"].casefold():
        abort(400, f"{game['one_name']} spiller mot alle – velg et annet lagnavn")
    token = new_token()
    db = get_db()
    try:
        db.execute("INSERT INTO teams (game_id, name, token) VALUES (?, ?, ?)", (game["id"], name, token))
        db.commit()
    except sqlite3.IntegrityError:
        abort(409, "Det lagnavnet er allerede tatt")
    notifier.bump()
    return jsonify({"name": name, "token": token}), 201


@app.post("/api/answer")
def submit_answer():
    data = request.get_json(silent=True) or {}
    game = current_game()
    if game["phase"] != "question" or data.get("qIndex") != game["q_index"]:
        abort(409, "Svarene på dette spørsmålet er låst")
    value = parse_number(data.get("value", ""))
    if value is None:
        abort(400, "Skriv inn et tall")
    if data.get("oneToken") is not None:
        if not check_one_token(game, data["oneToken"]):
            abort(403, f"Denne lenken for {game['one_name']} gjelder ikke for dette spillet")
        player = "one"
    else:
        team = team_by_token(game, data.get("teamToken"))
        if team is None:
            abort(403, "Ukjent lag – bli med på nytt")
        player = f"team:{team['id']}"
    questions = game_questions(game)
    if game["q_index"] >= len(questions):
        abort(409, "Dette spørsmålet finnes ikke lenger")
    db = get_db()
    db.execute(
        """INSERT INTO answers (game_id, question_id, player, value) VALUES (?, ?, ?, ?)
           ON CONFLICT (game_id, question_id, player) DO UPDATE SET value = excluded.value""",
        (game["id"], questions[game["q_index"]]["id"], player, value),
    )
    db.commit()
    notifier.bump()
    return jsonify({"ok": True, "value": value})


# ---------------------------------------------------------------- state
@app.get("/api/state")
def state():
    """Everything the showcase and the phones need. Hidden information (the
    correct answer, Erling's answer, the average) is only included once the
    host has revealed it."""
    db = get_db()
    game = current_game()
    phase, idx, step = game["phase"], game["q_index"], game["reveal_step"]
    questions = game_questions(game)
    total = len(questions) if phase not in ("lobby_one", "lobby") else \
        db.execute("SELECT COUNT(*) FROM questions").fetchone()[0]

    teams = db.execute("SELECT * FROM teams WHERE game_id = ? ORDER BY id", (game["id"],)).fetchall()
    current_q = questions[idx] if phase in ("question", "reveal") and idx < len(questions) else None
    answered = set()
    one_answer = None
    if current_q is not None:
        for r in db.execute("SELECT player, value FROM answers WHERE game_id = ? AND question_id = ?",
                            (game["id"], current_q["id"])):
            answered.add(r["player"])
            if r["player"] == "one":
                one_answer = r["value"]

    # The score is only shown at the very end, so it is only sent then.
    results = score = None
    if phase == "final":
        results = [question_result(game, q) for q in questions]
        score = {
            "one": sum(r["winner"] == "one" for r in results),
            "crowd": sum(r["winner"] == "crowd" for r in results),
        }

    current = None
    if current_q is not None:
        current = {
            "text": current_q["text"], "unit": current_q["unit"], "image": image_url(current_q["id"]),
            "oneAnswered": "one" in answered,
            "teamsAnswered": sum(f"team:{t['id']}" in answered for t in teams),
        }
        if phase == "reveal":
            res = question_result(game, current_q)
            current["correct"] = res["correct"]
            if step >= 2:
                current.update(one=res["one"], oneDistance=res["oneDistance"])
            if step >= 3:
                current.update(average=res["average"], averageDistance=res["averageDistance"],
                               teamAnswers=res["teamAnswers"], teamValues=res["teamValues"],
                               winner=res["winner"])

    # Who is asking? (phones pass their token so they can see their own answer)
    me = None
    one_valid = None
    my_player = None
    if request.args.get("one") is not None:
        one_valid = check_one_token(game, request.args["one"])
        if one_valid:
            me, my_player = {"name": game["one_name"]}, "one"
    else:
        team = team_by_token(game, request.args.get("team"))
        if team is not None:
            me, my_player = {"name": team["name"]}, f"team:{team['id']}"
    if me is not None and current_q is not None:
        row = db.execute("SELECT value FROM answers WHERE game_id = ? AND question_id = ? AND player = ?",
                         (game["id"], current_q["id"], my_player)).fetchone()
        me["answer"] = row["value"] if row else None

    return jsonify({
        "game": {
            "id": game["id"], "oneName": game["one_name"], "oneJoined": bool(game["one_joined"]),
            "phase": phase, "qIndex": idx, "revealStep": step, "totalQuestions": total,
        },
        "teams": [{"name": t["name"], "answered": f"team:{t['id']}" in answered} for t in teams],
        "current": current,
        "score": score,
        "results": results,
        "me": me,
        "oneValid": one_valid,
    })


@app.get("/api/events")
def events():
    """Server-Sent Events: a long-lived response that gets a short message
    whenever something changes, so clients only fetch /api/state when needed.
    ?scope=game  – only game steps (phones);  default – everything (showcase)."""
    scope = "game" if request.args.get("scope") == "game" else "all"

    def stream():
        seen = notifier.versions[scope]
        # Tell the client to reconnect after 2 s if the connection drops, and
        # send one message right away so it fetches the state after (re)connecting.
        yield f"retry: 2000\ndata: {seen}\n\n"
        while True:
            version = notifier.wait(scope, seen, timeout=15)
            if version == seen:
                yield ": keep-alive\n\n"  # comment line; also detects closed connections
            else:
                seen = version
                yield f"data: {version}\n\n"

    return Response(stream(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache"})


# ---------------------------------------------------------------- links / QR
def public_base_url():
    """Base URL that phones can reach: PUBLIC_URL if set. Otherwise the
    address the host's browser used – and if that is localhost, this
    machine's LAN IP, so QR codes work for other devices on the network."""
    if PUBLIC_URL:
        return PUBLIC_URL
    parts = urlsplit(request.host_url)
    host = parts.hostname or "localhost"
    if host in ("localhost", "127.0.0.1", "::1"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("10.255.255.255", 1))  # no packets are sent
                host = s.getsockname()[0]
        except OSError:
            pass
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{host}{port}"


@app.get("/api/links")
def links():
    """Join URLs for the teams and (secret) for Erling. Used by the showcase page."""
    game = current_game()
    base = public_base_url()
    return jsonify({
        "crowd": f"{base}/play.html",
        "one": f"{base}/erling.html?token={game['one_token']}",
    })


@app.get("/api/qr.svg")
def qr_svg():
    data = request.args.get("data", "")
    if not data or len(data) > 500:
        abort(400, "data is required")
    img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return Response(buf.getvalue(), mimetype="image/svg+xml")


# ---------------------------------------------------------------- misc
@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(409)
def client_error(err):
    return jsonify({"error": err.description}), err.code


@app.errorhandler(413)
def too_large(_err):
    # Also raised by Flask itself for bodies over MAX_CONTENT_LENGTH.
    return jsonify({"error": f"Bildet er for stort (maks {MAX_IMAGE_BYTES // 2**20} MB)"}), 413


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


init_db()

if __name__ == "__main__":
    # Built-in development server, for running locally. On a real server use
    # gunicorn instead (see gunicorn.conf.py).
    # threaded: each open /api/events connection needs its own thread.
    # Debug mode (auto-reload + in-browser debugger) is opt-in with DEBUG=1:
    # the debugger lets anyone who can reach the page run code on this machine.
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)),
            debug=os.environ.get("DEBUG") == "1", threaded=True)
