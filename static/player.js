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
    ? `<p class="kicker"><span class="accent">${esc(state.game.oneName)}</span> mot alle</p>`
    : `<p class="kicker">Lag ${esc(state.me.name)}</p>`;
  // Erling is "du" (you), a team is "dere" (you, plural).
  const You = mode === "one" ? "Du" : "Dere";
  const your = mode === "one" ? "ditt" : "deres";

  const views = {
    invalid() {
      root.innerHTML = `<h1>Hmm…</h1>
        <p class="error">Denne lenken for ${esc(state.game.oneName)} gjelder ikke for dette spillet. Be verten om den nye QR-koden.</p>`;
    },
    over() {
      root.innerHTML = `<h1>Spillet er over</h1><p class="lead">Vent til verten starter et nytt spill, og last inn siden på nytt.</p>`;
    },
    join() {
      const g = state.game;
      root.innerHTML = `
        <h1>Bli med som lag</h1>
        <p class="lead">I kveld er det alle mot <strong class="accent">${esc(g.oneName)}</strong>.</p>
        <form id="join-form" class="card">
          <label for="name">Lagnavn</label>
          <input type="text" id="name" maxlength="30" autocomplete="off" required>
          <div style="margin-top:14px"><button type="submit">Bli med</button></div>
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
        <h1>${You} er med! 🎉</h1>
        <p class="lead">${mode === "one"
          ? `Gjør deg klar, ${esc(state.game.oneName)} — det er deg mot alle.`
          : `Gjør dere klare til å ta opp kampen mot ${esc(state.game.oneName)}.`}
          Spørsmålene dukker opp her når verten starter.</p>`;
    },
    q() {
      const g = state.game, c = state.current, me = state.me;
      const head = `${header()}<p class="muted">Spørsmål ${g.qIndex + 1} av ${g.totalQuestions}</p>
        <p class="question-text">${esc(c.text)}</p>`;
      if (me.answer !== null && !editing) {
        root.innerHTML = `${head}
          <div class="card answer-card">
            <p class="muted">Svaret ${your}</p>
            <p class="answer-big">${esc(fmtUnit(me.answer, c.unit))}</p>
            <button class="secondary" id="change">Endre svar</button>
          </div>
          <p class="muted">${You} kan endre det til verten låser svarene.</p>`;
        document.getElementById("change").onclick = () => { editing = true; viewKey = null; render(); };
        return;
      }
      root.innerHTML = `${head}
        <form id="answer-form" class="card">
          <label for="value">Svaret ${your}${c.unit ? ` (${esc(c.unit)})` : ""}</label>
          <div class="row">
            <input type="text" id="value" inputmode="decimal" autocomplete="off" required
                   value="${me.answer !== null ? esc(String(me.answer).replace(".", ",")) : ""}">
            ${c.unit ? `<span class="muted">${esc(c.unit)}</span>` : ""}
          </div>
          <div style="margin-top:14px"><button type="submit">Send svar</button></div>
          <p class="error" id="err"></p>
        </form>`;
      const input = document.getElementById("value");
      input.focus();
      document.getElementById("answer-form").onsubmit = async (e) => {
        e.preventDefault();
        const value = parseNumber(input.value);
        if (value === null) {
          document.getElementById("err").textContent = "Skriv inn et tall.";
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
        <h1>Svarene er låst 🔒</h1>
        <p class="lead">${me.answer === null ? `${You} svarte ikke på dette.`
          : `${You} svarte <strong>${esc(fmtUnit(me.answer, c.unit))}</strong>.`}</p>
        <p class="lead">Følg med på storskjermen! 📺</p>`;
    },
    final() {
      root.innerHTML = `${header()}
        <h1>Det var det!</h1>
        <p class="lead">Se sluttresultatet på storskjermen. 🏆</p>`;
    },
  };

  if (mode === "one" && oneToken) {
    api("/api/one/join", { method: "POST", body: { token: oneToken } }).catch(() => {});
  }
  // Phones only need to hear about game steps; their own answers come back
  // in the response when they submit.
  subscribe("game", poll);
}
