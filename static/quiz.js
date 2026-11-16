// Shared quiz flow used by play.html (the crowd) and one.html (the 1).
//
// Expects these elements in the page:
//   #quiz (section), #progress-bar, #q-counter, #q-text, #choices, #prev, #next, #quiz-error
// runQuiz(questions, submit) shows one question at a time and calls
// `submit(answers)` when the last one is answered. If submit throws, the
// error is shown and the player can try again.

function runQuiz(questions, submit) {
  const $ = (id) => document.getElementById(id);
  const picks = {}; // questionId -> choice index
  let idx = 0;

  function show() {
    const q = questions[idx];
    $("progress-bar").style.width = `${(idx / questions.length) * 100}%`;
    $("q-counter").textContent = `Question ${idx + 1} of ${questions.length}`;
    $("q-text").textContent = q.text;
    $("choices").innerHTML = q.options.map((o, i) =>
      `<button class="choice ${picks[q.id] === i ? "selected" : ""}" data-i="${i}">
         <strong>${"ABCDEF"[i]}.</strong> ${esc(o)}</button>`).join("");
    $("choices").querySelectorAll(".choice").forEach((b) => {
      b.onclick = () => { picks[q.id] = Number(b.dataset.i); show(); };
    });
    $("prev").style.visibility = idx === 0 ? "hidden" : "visible";
    $("next").disabled = picks[q.id] === undefined;
    $("next").textContent = idx === questions.length - 1 ? "Submit answers ✓" : "Next →";
  }

  $("prev").onclick = () => { if (idx > 0) { idx--; show(); } };

  $("next").onclick = async () => {
    if (idx < questions.length - 1) { idx++; show(); return; }
    $("next").disabled = true;
    $("quiz-error").textContent = "";
    try {
      await submit(Object.entries(picks).map(([questionId, choice]) =>
        ({ questionId: Number(questionId), choice })));
    } catch (err) {
      $("quiz-error").textContent = err.message;
      $("next").disabled = false;
    }
  };

  $("quiz").hidden = false;
  show();
}
