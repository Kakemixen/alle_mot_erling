// Phone view, shared by play.html (teams) and erling.html (Erling).
// Polls the game state and shows whatever fits the current phase:
// join → wait → answer the current question → "look at the screen" → …

function startPlayer({ mode, oneToken }) {
  const root = document.getElementById("app");
  let state = null, viewKey = null, editing = false;
  let team = null; // { name, token } – teams only

  // sessionStorage is per tab, so several tabs in one browser can be different teams
  // (handy for testing), while a page refresh keeps the team.
  try { team = JSON.parse(sessionStorage.getItem("team")); } catch {}

  async function poll() {
    try {
      const query = mode === "one" ? `one=${encodeURIComponent(oneToken)}`
                  : team ? `team=${encodeURIComponent(team.token)}` : "";
      state = await api(`/api/state?${query}`);
      render();
    } catch (err) {
      console.error(err);
    }
  }

  function render() {
    const g = state.game, me = state.me;
    let key;
    if (mode === "one" && !state.oneValid) key = "invalid";
    else if (mode === "team" && !me) key = g.phase === "final" ? "over" : "join";
    else if (g.phase === "lobby_one" || g.phase === "lobby") key = "wait";
    else if (g.phase === "question") key = `q${g.qIndex}:${me.answer === null || editing ? "input" : `answered:${me.answer}`}`;
    else if (g.phase === "reveal") key = `r${g.qIndex}`;
    else key = "final";
    key = `${g.id}:${key}`;
    if (key === viewKey) return;
    viewKey = key;
    views[key.split(":")[1].replace(/\d+$/, "")]();
  }

  const header = () => mode === "one"
    ? `<p class="kicker"><span class="accent">${esc(state.game.oneName)}</span> against everyone</p>`
    : `<p class="kicker">Team ${esc(state.me.name)}</p>`;

  const views = {
    invalid() {
      root.innerHTML = `<h1>Hmm…</h1>
        <p class="error">This link for ${esc(state.game.oneName)} isn't valid for the current game. Ask the host for the new QR code.</p>`;
    },
    over() {
      root.innerHTML = `<h1>Game over</h1><p class="lead">Wait for the host to start a new game, then reload this page.</p>`;
    },
    join() {
      const g = state.game;
      root.innerHTML = `
        <h1>Join as a team</h1>
        <p class="lead">Tonight it's everyone against <strong class="accent">${esc(g.oneName)}</strong>.</p>
        <form id="join-form" class="card">
          <label for="name">Team name</label>
          <input type="text" id="name" maxlength="30" autocomplete="off" required>
          <div style="margin-top:14px"><button type="submit">Join</button></div>
          <p class="error" id="err"></p>
        </form>`;
      document.getElementById("join-form").onsubmit = async (e) => {
        e.preventDefault();
        const name = document.getElementById("name").value.trim();
        if (!name) return;
        try {
          team = await api("/api/teams", { method: "POST", body: { name } });
          try { sessionStorage.setItem("team", JSON.stringify(team)); } catch {}
          viewKey = null;
          poll();
        } catch (err) {
          document.getElementById("err").textContent = err.message;
        }
      };
    },
    wait() {
      root.innerHTML = `${header()}
        <h1>You're in! 🎉</h1>
        <p class="lead">${mode === "one"
          ? `Get ready, ${esc(state.game.oneName)} — it's you against everyone.`
          : `Get ready to take on ${esc(state.game.oneName)}.`}
          The questions will appear here when the host starts.</p>`;
    },
    q() {
      const g = state.game, c = state.current, me = state.me;
      const head = `${header()}<p class="muted">Question ${g.qIndex + 1} of ${g.totalQuestions}</p>
        <p class="question-text">${esc(c.text)}</p>`;
      if (me.answer !== null && !editing) {
        root.innerHTML = `${head}
          <div class="card answer-card">
            <p class="muted">Your answer</p>
            <p class="answer-big">${esc(fmtUnit(me.answer, c.unit))}</p>
            <button class="secondary" id="change">Change answer</button>
          </div>
          <p class="muted">You can change it until the host locks the answers.</p>`;
        document.getElementById("change").onclick = () => { editing = true; viewKey = null; render(); };
        return;
      }
      root.innerHTML = `${head}
        <form id="answer-form" class="card">
          <label for="value">Your answer${c.unit ? ` (${esc(c.unit)})` : ""}</label>
          <div class="row">
            <input type="text" id="value" inputmode="decimal" autocomplete="off" required
                   value="${me.answer !== null ? esc(fmt(me.answer).replace(/,/g, "")) : ""}">
            ${c.unit ? `<span class="muted">${esc(c.unit)}</span>` : ""}
          </div>
          <div style="margin-top:14px"><button type="submit">Submit answer</button></div>
          <p class="error" id="err"></p>
        </form>`;
      const input = document.getElementById("value");
      input.focus();
      document.getElementById("answer-form").onsubmit = async (e) => {
        e.preventDefault();
        const value = parseNumber(input.value);
        if (value === null) {
          document.getElementById("err").textContent = "Please enter a number.";
          return;
        }
        try {
          await api("/api/answer", {
            method: "POST",
            body: { qIndex: g.qIndex, value, ...(mode === "one" ? { oneToken } : { teamToken: team.token }) },
          });
          editing = false;
          viewKey = null;
          poll();
        } catch (err) {
          document.getElementById("err").textContent = err.message;
          if (err.status === 409) setTimeout(poll, 1000);
        }
      };
    },
    r() {
      const c = state.current, me = state.me;
      editing = false;
      root.innerHTML = `${header()}
        <h1>Answers locked 🔒</h1>
        <p class="lead">${me.answer === null ? "You didn't answer this one."
          : `You answered <strong>${esc(fmtUnit(me.answer, c.unit))}</strong>.`}</p>
        <p class="lead">Eyes on the big screen! 📺</p>`;
    },
    final() {
      root.innerHTML = `${header()}
        <h1>That's a wrap!</h1>
        <p class="lead">See the final score on the big screen. 🏆</p>`;
    },
  };

  if (mode === "one" && oneToken) {
    api("/api/one/join", { method: "POST", body: { token: oneToken } }).catch(() => {});
  }
  // Phones only need to hear about game steps; their own answers come back
  // in the response when they submit.
  subscribe("game", poll);
}
