# Alle mod 1

A small "everyone against one" quiz platform, inspired by the Danish TV show *Alle mod 1*.
One player (the **1**) takes on all the teams. Every answer is a number, and each question
gives one point to whoever is closest to the correct answer: the 1, or the **average** of
all team answers.

## Pages

| Page | URL | Purpose |
|------|-----|---------|
| Create   | `/create.html`      | Write questions with a numeric answer (and optional unit) |
| Showcase | `/showcase.html`    | The big screen – the host runs the whole game from here |
| Join     | `/play.html`        | Phone page for teams (reached via the QR code on the showcase) |
| The 1    | `/one.html?token=…` | Phone page for the 1, only reachable via a secret link that changes every game |

## Game flow

The host presses **Next** on the showcase (or →/Page Down, so a presenter clicker works):

1. **The 1** – QR code/link for the 1, shows when the 1 has opened it.
2. **Teams** – QR code for teams and the list of teams that have joined. **Start quiz**.
3. For each question:
   1. Only the question is shown; the 1 and the teams answer on their phones (they can change
      their answer until the host locks it).
   2. The answers are revealed step by step on a number line:
      the correct answer → the 1's answer and the range everyone's average must land in to beat
      the 1 → everyone's average and who gets the point.
4. **Final score** with a summary of every question. **New game** starts over with a new 1.

## Running

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

Open <http://localhost:5000/showcase.html> on the big screen. QR codes use this machine's LAN IP
when the page is opened via `localhost`, so phones on the same network can reach the server.

Data is stored in SQLite (`quiz.db`, created on first run and seeded with 3 example questions
and a game where *Erling* is the 1). Set `QUIZ_DB` to use another file, `PORT` for another port.
Databases from the first (multiple-choice) version are kept as `*_v1` tables and a fresh schema is created.

### Host password

Create and Showcase (and the API calls only they use: managing questions, Next, New game and the
1's secret link) ask for a login via the browser's login prompt: user name `gamemaster`,
password `honestmistake` (`HOST_USER` / `HOST_PASSWORD` in `app.py`). This only keeps curious players out –
it's hard-coded and travels unencrypted over plain HTTP, so it's not real security.

## Live updates

Clients don't poll. Each page keeps one Server-Sent Events connection (`/api/events`) open, and
the server sends a tiny message when something changes; the page then fetches `/api/state` once.
Phones only listen for game steps (Next / New game), so each phone makes about one request per
step. The showcase also listens for joins and answers (for its live counters) and refreshes at
most twice a second. A refresh every 30 s and when a tab becomes visible again covers anything missed.

Things to know:

* Run the app as **one process** (as `python app.py` does) – the change notifications live in memory.
* Every open page holds one connection and, with the built-in server, one thread. That's fine for
  a few hundred players.
* Browsers allow only ~6 open connections per host name. When testing many teams as tabs in
  **one** browser, tabs beyond that hang. Spread them over host names
  (`localhost`, `127.0.0.1`, your LAN IP) or browsers. Real phones are not affected.
