"""Alle mod 1 – a small "everyone against one" quiz platform.

Run with:  python app.py   (then open http://localhost:5000)
"""
import io
import json
import os
import secrets
import socket
import sqlite3
from urllib.parse import urlsplit

import qrcode
import qrcode.image.svg
from flask import Flask, Response, abort, g, jsonify, request, send_from_directory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("QUIZ_DB", os.path.join(BASE_DIR, "quiz.db"))

app = Flask(__name__, static_folder="static", static_url_path="")

SCHEMA = """
CREATE TABLE IF NOT EXISTS questions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    text          TEXT    NOT NULL,
    options       TEXT    NOT NULL,          -- JSON array of strings
    correct_index INTEGER NOT NULL,
    created_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS games (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    one_name   TEXT NOT NULL,                -- the "1" playing against everyone
    one_token  TEXT,                         -- secret for the 1's private page
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS answers (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id      INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    question_id  INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    player_name  TEXT    NOT NULL,
    is_one       INTEGER NOT NULL DEFAULT 0,
    choice_index INTEGER NOT NULL,
    created_at   TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (game_id, question_id, player_name)
);
"""

SEED_QUESTIONS = [
    ("What is the highest natural point in Denmark?",
     ["Himmelbjerget", "Yding Skovhøj", "Møllehøj", "Ejer Bavnehøj"], 2),
    ("How many players per team are on the court in a handball match?",
     ["5", "6", "7", "11"], 2),
    ("Which planet has the most known moons?",
     ["Jupiter", "Saturn", "Uranus", "Neptune"], 1),
]


# --------------------------------------------------------------------------- db
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    with sqlite3.connect(DB_PATH) as db:
        db.executescript(SCHEMA)
        cols = {r[1] for r in db.execute("PRAGMA table_info(games)")}
        if "one_token" not in cols:  # migrate databases from before one_token existed
            db.execute("ALTER TABLE games ADD COLUMN one_token TEXT")
        for (gid,) in db.execute("SELECT id FROM games WHERE one_token IS NULL").fetchall():
            db.execute("UPDATE games SET one_token = ? WHERE id = ?", (new_token(), gid))
        if db.execute("SELECT COUNT(*) FROM questions").fetchone()[0] == 0:
            db.executemany(
                "INSERT INTO questions (text, options, correct_index) VALUES (?, ?, ?)",
                [(t, json.dumps(o, ensure_ascii=False), c) for t, o, c in SEED_QUESTIONS],
            )
        if db.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 0:
            db.execute("INSERT INTO games (one_name, one_token) VALUES (?, ?)",
                       ("Erling", new_token()))


def new_token():
    return secrets.token_urlsafe(12)


def question_dict(row, include_answer=True):
    q = {"id": row["id"], "text": row["text"], "options": json.loads(row["options"])}
    if include_answer:
        q["correctIndex"] = row["correct_index"]
    return q


def current_game():
    return get_db().execute("SELECT * FROM games ORDER BY id DESC LIMIT 1").fetchone()


def game_dict(row):
    # Never include one_token here – this is served to everybody.
    return {"id": row["id"], "oneName": row["one_name"], "createdAt": row["created_at"]}


def public_base_url():
    """Base URL that phones can reach. If the host browses via localhost,
    swap in this machine's LAN IP so QR codes work for other devices."""
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


# ------------------------------------------------------------------- questions
@app.get("/api/questions")
def list_questions():
    rows = get_db().execute("SELECT * FROM questions ORDER BY id").fetchall()
    return jsonify([question_dict(r) for r in rows])


@app.post("/api/questions")
def create_question():
    data = request.get_json(silent=True) or {}
    text = str(data.get("text", "")).strip()
    options = [str(o).strip() for o in data.get("options", []) if str(o).strip()]
    correct = data.get("correctIndex")
    if not text:
        abort(400, "Question text is required")
    if not 2 <= len(options) <= 6:
        abort(400, "Provide between 2 and 6 options")
    if not isinstance(correct, int) or not 0 <= correct < len(options):
        abort(400, "correctIndex must point at one of the options")
    db = get_db()
    cur = db.execute(
        "INSERT INTO questions (text, options, correct_index) VALUES (?, ?, ?)",
        (text, json.dumps(options, ensure_ascii=False), correct),
    )
    db.commit()
    row = db.execute("SELECT * FROM questions WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(question_dict(row)), 201


@app.delete("/api/questions/<int:qid>")
def delete_question(qid):
    db = get_db()
    db.execute("DELETE FROM questions WHERE id = ?", (qid,))
    db.commit()
    return "", 204


# ------------------------------------------------------------------------ game
@app.get("/api/game")
def get_game():
    return jsonify(game_dict(current_game()))


@app.post("/api/game")
def new_game():
    data = request.get_json(silent=True) or {}
    name = str(data.get("oneName", "")).strip()
    if not name:
        abort(400, "Name of the 1 is required")
    db = get_db()
    db.execute("INSERT INTO games (one_name, one_token) VALUES (?, ?)", (name, new_token()))
    db.commit()
    return jsonify(game_dict(current_game())), 201


@app.get("/api/links")
def links():
    """Join URLs for the crowd and (secret) for the 1. Used by the results page."""
    game = current_game()
    base = public_base_url()
    return jsonify({
        "crowd": f"{base}/play.html",
        "one": f"{base}/one.html?token={game['one_token']}",
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


@app.get("/api/play")
def play_info():
    """Questions for players – without the correct answers.
    With ?token=… it also verifies the link for the 1."""
    game = current_game()
    token = request.args.get("token")
    if token is not None and not secrets.compare_digest(token, game["one_token"]):
        abort(403, "This link for the 1 is not valid for the current game")
    rows = get_db().execute("SELECT * FROM questions ORDER BY id").fetchall()
    return jsonify({
        "game": game_dict(game),
        "questions": [question_dict(r, include_answer=False) for r in rows],
    })


@app.post("/api/answers")
def submit_answers():
    data = request.get_json(silent=True) or {}
    name = str(data.get("playerName", "")).strip()
    game_id = data.get("gameId")
    token = data.get("oneToken")
    answers = data.get("answers", [])
    db = get_db()
    game = db.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
    if game is None:
        abort(400, "Unknown game")
    if game["id"] != current_game()["id"]:
        abort(409, "This game is over – reload the page to join the new one")
    if token is not None:
        # The 1's private page: only the secret token makes you the 1.
        if not secrets.compare_digest(str(token), game["one_token"]):
            abort(403, "Invalid link for the 1")
        is_one, name = 1, game["one_name"]
    else:
        if not name:
            abort(400, "Player name is required")
        if name.casefold() == game["one_name"].casefold():
            abort(400, f"{game['one_name']} is the 1 – please pick another name")
        is_one = 0
    questions = {r["id"]: r for r in db.execute("SELECT * FROM questions").fetchall()}
    for a in answers:
        q = questions.get(a.get("questionId"))
        choice = a.get("choice")
        if q is None or not isinstance(choice, int):
            continue
        if not 0 <= choice < len(json.loads(q["options"])):
            continue
        db.execute(
            """INSERT INTO answers (game_id, question_id, player_name, is_one, choice_index)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT (game_id, question_id, player_name)
               DO UPDATE SET choice_index = excluded.choice_index""",
            (game["id"], q["id"], name, is_one, choice),
        )
    db.commit()
    return jsonify({"ok": True, "isOne": bool(is_one)})


# --------------------------------------------------------------------- results
@app.get("/api/results")
def results():
    db = get_db()
    game = current_game()
    questions = db.execute("SELECT * FROM questions ORDER BY id").fetchall()
    rows = db.execute(
        "SELECT * FROM answers WHERE game_id = ?", (game["id"],)
    ).fetchall()

    crowd_players = sorted({r["player_name"] for r in rows if not r["is_one"]})
    one_correct = 0
    crowd_correct_sum = 0.0
    out_questions = []
    for q in questions:
        qa = [r for r in rows if r["question_id"] == q["id"]]
        options = json.loads(q["options"])
        counts = [0] * len(options)
        one_choice = None
        for r in qa:
            if r["is_one"]:
                one_choice = r["choice_index"]
            elif 0 <= r["choice_index"] < len(counts):
                counts[r["choice_index"]] += 1
        crowd_total = sum(counts)
        crowd_pct = (counts[q["correct_index"]] / crowd_total * 100) if crowd_total else None
        one_right = one_choice == q["correct_index"]
        one_correct += int(one_right)
        crowd_correct_sum += (crowd_pct or 0) / 100
        out_questions.append({
            **question_dict(q),
            "counts": counts,
            "crowdTotal": crowd_total,
            "crowdCorrectPct": crowd_pct,
            "oneChoice": one_choice,
            "oneCorrect": one_right if one_choice is not None else None,
        })

    return jsonify({
        "game": game_dict(game),
        "crowdPlayers": crowd_players,
        "oneHasAnswered": any(r["is_one"] for r in rows),
        "questions": out_questions,
        "score": {
            "one": one_correct,
            # average number of correct answers per crowd player
            "crowd": round(crowd_correct_sum, 2),
            "total": len(questions),
        },
    })


@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(409)
def bad_request(err):
    return jsonify({"error": err.description}), err.code


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
