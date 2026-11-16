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
function renderHeader(active) {
  const links = [
    ["create", "/create.html", "Create"],
    ["showcase", "/showcase.html", "Showcase"],
    ["play", "/play.html", "Join"],
  ];
  const header = document.createElement("header");
  header.className = "top";
  header.innerHTML = `
    <a class="logo" href="/">Alle mod <span class="one">1</span></a>
    <nav>${links.map(([key, href, label]) =>
      `<a href="${href}" class="${key === active ? "active" : ""}">${label}</a>`).join("")}
    </nav>`;
  document.body.prepend(header);
}
