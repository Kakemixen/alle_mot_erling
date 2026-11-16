// Shared helpers for all pages.

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

// Inject the shared header and highlight the current page.
function renderHeader(active) {
  const links = [
    ["create", "/create.html", "Create"],
    ["play", "/play.html", "Play"],
    ["results", "/results.html", "Results"],
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
