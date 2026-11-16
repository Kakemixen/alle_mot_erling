# Alle mod 1

A small "everyone against one" quiz platform, inspired by the Danish TV show *Alle mod 1*.
One player (the **1**) answers the same questions as everybody else; the 1's score is
compared with the crowd's average score.

## Pages

| Page | URL | Purpose |
|------|-----|---------|
| Create  | `/create.html`  | Write questions, pick the correct option, delete questions |
| Play    | `/play.html`    | The crowd enters their name and answers the quiz (the 1's name is refused here) |
| The 1   | `/one.html?token=…` | Private page for the 1, reachable only via a secret link that changes every game |
| Results | `/results.html` | Big-screen view: QR code for the crowd, live answer counts, "Reveal answers", scoreboard and winner, "New game" |

The results page always shows a QR code for joining the crowd. Click **Link for the 1** to show the
1's secret link and QR code (hide it again before the crowd sees the screen). QR codes use this
machine's LAN IP when the page is opened via `localhost`, so phones can reach the server.

Note: the secret link keeps players from accidentally (or cheekily) playing as the 1, but it is not
real security: anyone who knows to call `/api/links` can fetch it.

## Running

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

Open <http://localhost:5000>. Players on the same network can join via `http://<your-ip>:5000/play.html`.

Data is stored in SQLite (`quiz.db`, created on first run and seeded with 3 example questions
and a game where *Erling* is the 1). Set `QUIZ_DB` to use another file, `PORT` for another port.
