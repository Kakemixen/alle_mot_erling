// Shared helpers for all pages.

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.error || `Request failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return data;
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

// Format a number for display. Years and other 4-digit numbers are shown
// without thousands separators ("2000", not "2,000").
function fmt(v) {
  return Number(v).toLocaleString("en", {
    maximumFractionDigits: 2,
    useGrouping: Math.abs(v) >= 10000,
  });
}

function fmtUnit(v, unit) {
  return unit ? `${fmt(v)} ${unit}` : fmt(v);
}

// Accept both "1.5" and the Danish "1,5".
function parseNumber(s) {
  const v = Number(String(s).trim().replace(",", "."));
  return String(s).trim() !== "" && Number.isFinite(v) ? v : null;
}

const qrSrc = (url) => `/api/qr.svg?data=${encodeURIComponent(url)}`;

// Inject the shared header and highlight the current page.
// { nav: false } shows just the logo (for players' phones).
function renderHeader(active, { nav = true } = {}) {
  const links = [
    ["create", "/create.html", "Create"],
    ["showcase", "/showcase.html", "Showcase"],
    ["play", "/play.html", "Join"],
  ];
  const header = document.createElement("header");
  header.className = "top";
  header.innerHTML = `
    <a class="logo" href="/">Alle mod <span class="one">1</span></a>
    ${nav ? `<nav>${links.map(([key, href, label]) =>
      `<a href="${href}" class="${key === active ? "active" : ""}">${label}</a>`).join("")}
    </nav>` : ""}`;
  document.body.prepend(header);
}

// Call `refresh` whenever the server says something changed, instead of
// polling. Uses Server-Sent Events: one long-lived connection on which the
// server sends a tiny message per change; the browser reconnects by itself.
//   scope:       "game" = only game steps (phones), "all" = also joins/answers
//   minInterval: at most one refresh per this many ms (bursts of answers)
// A slow fallback refresh and a refresh when the tab becomes visible again
// (e.g. a phone waking up) cover any missed messages.
function subscribe(scope, refresh, { minInterval = 0, fallbackMs = 30000 } = {}) {
  let timer = null, last = 0;
  const trigger = () => {
    if (timer) return; // a refresh is already scheduled and will see the change
    const wait = Math.max(0, last + minInterval - Date.now());
    timer = setTimeout(() => {
      timer = null;
      last = Date.now();
      refresh();
    }, wait);
  };
  if (window.EventSource) {
    new EventSource(`/api/events?scope=${scope}`).onmessage = trigger;
  } else {
    fallbackMs = Math.min(fallbackMs, 2000); // very old browser: plain polling
  }
  setInterval(trigger, fallbackMs);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) trigger(); });
  trigger();
}
