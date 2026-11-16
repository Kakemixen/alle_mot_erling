# Alle mot Erling

A small "everyone against one" quiz platform, inspired by the Danish TV show *Alle mod 1*.
One player (**Erling**) takes on all the teams. Every answer is a number, and each question
gives one point to whoever is closest to the correct answer: Erling, or the **average** of
all team answers.

## Pages

| Page | URL | Purpose |
|------|-----|---------|
| Create   | `/create.html`      | Write questions with a numeric answer (and optional unit) |
| Showcase | `/showcase.html`    | The big screen – the host runs the whole game from here |
| Join     | `/play.html`        | Phone page for teams (reached via the QR code on the showcase) |
| Erling   | `/erling.html?token=…` | Phone page for Erling, only reachable via a secret link that changes every game |

## Game flow

The host presses **Next** on the showcase (or →/Page Down, so a presenter clicker works):

1. **Erling** – QR code/link for Erling, shows when Erling has opened it.
2. **Teams** – QR code for teams and the list of teams that have joined. **Start quiz**.
3. For each question:
   1. Only the question is shown; Erling and the teams answer on their phones (they can change
      their answer until the host locks it).
   2. The answers are revealed step by step on a number line:
      the correct answer → Erling's answer and the range everyone's average must land in to beat
      Erling → everyone's average and who gets the point.
4. **Final score** with a summary of every question. **New game** starts over (Erling plays every game).

## Running locally

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

Open <http://localhost:5000/showcase.html> on the big screen. QR codes use this machine's LAN IP
when the page is opened via `localhost`, so phones on the same network can reach it.
`DEBUG=1 .venv/bin/python app.py` turns on auto-reload and Flask's in-browser debugger – only do
that on a network you trust, since the debugger lets visitors run code on your machine.

## Running on a server

Use gunicorn instead of `python app.py` (the built-in server is only meant for development):

```sh
.venv/bin/gunicorn -c gunicorn.conf.py app:app      # listens on 127.0.0.1:8000
```

`gunicorn.conf.py` runs **one process with 64 threads**: every open page holds one live-update
connection (and thread), and the change notifications live in that one process – don't raise
`workers`. That's plenty for ~30 teams; raise `THREADS` if you expect more than ~50 players/screens.

Recommended setup on a Linux server (examples in `deploy/`):

* **nginx in front** with HTTPS (`deploy/nginx.conf`). It passes the live updates through
  unbuffered, encrypts the host login, and with HTTP/2 there's no per-browser connection limit.
* **systemd** to start it on boot and restart on crashes (`deploy/alle-mot-erling.service`).
* **Set `PUBLIC_URL`** to the address players use, e.g. `PUBLIC_URL=https://quiz.example.com`
  (in the systemd file), so the QR codes point to the right place – see below.

### QR codes and links

The showcase shows two QR codes, each with its link printed underneath:

* **Teams:** `<base>/play.html`
* **Erling:** `<base>/erling.html?token=…` – the token is a secret that changes with every
  New game, so an Erling QR code or link from an earlier game stops working.

The `<base>` address is chosen in this order (`public_base_url()` in `app.py`):

1. **`PUBLIC_URL`**, if set – used exactly as given. On the server, set it in the
   `Environment=PUBLIC_URL=…` line of `deploy/alle-mot-erling.service`, then
   `sudo systemctl daemon-reload && sudo systemctl restart alle-mot-erling`.
2. Otherwise **the address the showcase was opened with**. So the address you type for the
   showcase decides where every phone goes: opening it via `http://192.168.1.20:5000` gives QR
   codes for `http://192.168.1.20:5000/…`.
3. If that address is `localhost`/`127.0.0.1`, **this machine's LAN IP** with the same port
   instead – phones can't reach "localhost" (on a phone that means the phone itself).

Behind nginx, step 2 would see the internal `127.0.0.1:8000` and step 3 would turn that into
the server's IP with port 8000 over `http://` – not reachable for players. That's why
`PUBLIC_URL` should be set on a server.

**Check before players arrive:** open the showcase and read the link under the QR code – it's
exactly what the phones will open. Scanning it with your own phone is the quickest test.

### Configuration

All optional, as environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `PUBLIC_URL` | – | Address players reach the site on; used for the QR codes |
| `QUIZ_DB` | `quiz.db` next to `app.py` | SQLite database file (keep it outside the code folder on a server) |
| `HOST_USER` / `HOST_PASSWORD` | `gamemaster` / `honestmistake` | Host login |
| `BIND`, `THREADS` | `127.0.0.1:8000`, `64` | gunicorn only |
| `PORT`, `DEBUG` | `5000`, off | `python app.py` only |

### Data

Data is stored in SQLite (created on first run and seeded with 3 example questions and a game
where Erling plays against everyone), in WAL mode so many simultaneous answers work well. Back it up with
`sqlite3 quiz.db ".backup backup.db"` – copying the file alone can miss the `quiz.db-wal` part.
Databases from the first (multiple-choice) version are kept as `*_v1` tables and a fresh schema is created.

### Host password

Create and Showcase (and the API calls only they use: managing questions, Next, New game and the
Erling's secret link) ask for a login via the browser's login prompt: user name `gamemaster`,
password `honestmistake` (or `HOST_USER` / `HOST_PASSWORD`). This only keeps curious players out:
the default is in the source code, and without HTTPS it travels unencrypted.

## Live updates

Clients don't poll. Each page keeps one Server-Sent Events connection (`/api/events`) open, and
the server sends a tiny message when something changes; the page then fetches `/api/state` once.
Phones only listen for game steps (Next / New game), so each phone makes about one request per
step. The showcase also listens for joins and answers (for its live counters) and refreshes at
most twice a second. A refresh every 30 s and when a tab becomes visible again covers anything missed.

Things to know:

* Run the app as **one process** (as `python app.py` and `gunicorn.conf.py` do) – the change
  notifications live in memory.
* Every open page holds one connection and one thread (see *Running on a server*).
* Without HTTPS/HTTP/2, browsers allow only ~6 open connections per host name. When testing many
  teams as tabs in **one** browser, tabs beyond that hang. Spread them over host names
  (`localhost`, `127.0.0.1`, your LAN IP) or browsers. Real phones are not affected.
