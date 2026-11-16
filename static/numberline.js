// An animated number line. Call update() with the markers to show; markers,
// ticks and the highlighted range keep their DOM elements between updates so
// they glide to their new position when the scale changes.
//
//   line.update(
//     [{ key, value, label (HTML), cls, side: "top"|"bottom", row: 0|1 }],
//     { from, to } | null,     // highlighted range
//     [values]                 // optional small unlabeled dots (e.g. each team's answer)
//   )

class NumberLine {
  constructor(el) {
    this.el = el;
    el.classList.add("nl");
    el.innerHTML = `<div class="nl-band"></div><div class="nl-axis"></div>`;
    this.band = el.querySelector(".nl-band");
    this.markers = new Map();
    this.ticks = new Map();
    this.dots = [];
  }

  update(markers, band, dots = []) {
    const values = markers.map((m) => m.value).concat(dots);
    if (band) values.push(band.from, band.to);
    if (!values.length) return;

    // Domain with some padding so labels don't hit the edges.
    let lo = Math.min(...values), hi = Math.max(...values);
    if (hi - lo < 1e-9) {
      const pad = Math.max(Math.abs(lo) * 0.2, 1);
      lo -= pad; hi += pad;
    } else {
      const pad = (hi - lo) * 0.18;
      lo -= pad; hi += pad;
    }
    const pos = (v) => `${((v - lo) / (hi - lo)) * 100}%`;

    // Ticks
    const step = NumberLine.niceStep((hi - lo) / 6);
    const wanted = new Set();
    for (let t = Math.ceil(lo / step) * step; t <= hi; t += step) {
      const v = Number(t.toPrecision(12));
      const key = String(v);
      wanted.add(key);
      let el = this.ticks.get(key);
      if (!el) {
        el = this.appendFaded("nl-tick", fmt(v), pos(v));
        this.ticks.set(key, el);
      } else {
        el.style.left = pos(v);
      }
    }
    for (const [key, el] of this.ticks) {
      if (!wanted.has(key)) { el.remove(); this.ticks.delete(key); }
    }

    // Highlighted range
    if (band) {
      this.band.style.left = pos(Math.min(band.from, band.to));
      this.band.style.width = `calc(${pos(Math.max(band.from, band.to))} - ${pos(Math.min(band.from, band.to))})`;
      this.band.classList.add("shown");
    } else {
      this.band.classList.remove("shown");
    }

    // Markers
    const keys = new Set(markers.map((m) => m.key));
    for (const m of markers) {
      let el = this.markers.get(m.key);
      const html = `<div class="stem"></div><div class="dot"></div><div class="label">${m.label}</div>`;
      if (!el) {
        el = this.appendFaded(`nl-marker ${m.side || "top"} row${m.row || 0} ${m.cls || ""}`, html, pos(m.value));
        this.markers.set(m.key, el);
      } else {
        el.style.left = pos(m.value);
        if (el.dataset.html !== html) el.innerHTML = html;
      }
      el.dataset.html = html;
    }
    for (const [key, el] of this.markers) {
      if (!keys.has(key)) { el.remove(); this.markers.delete(key); }
    }

    // Dots: sorted, and stacked upwards when they would overlap.
    const sorted = [...dots].sort((a, b) => a - b);
    const width = this.el.clientWidth || 800;
    const minGap = 14 / width; // ~ one dot width, as a fraction of the line
    let groupStart = -Infinity, stack = 0;
    sorted.forEach((v, i) => {
      const x = (v - lo) / (hi - lo);
      if (x - groupStart < minGap) stack++;
      else { groupStart = x; stack = 0; }
      let el = this.dots[i];
      if (!el) {
        el = this.appendFaded("nl-dot", "", pos(v));
        this.dots[i] = el;
      } else {
        el.style.left = pos(v);
      }
      el.style.setProperty("--s", stack);
    });
    this.dots.splice(sorted.length).forEach((el) => el.remove());
  }

  appendFaded(cls, html, left) {
    const el = document.createElement("div");
    el.className = cls;
    el.innerHTML = html;
    el.style.left = left;
    this.el.appendChild(el);
    requestAnimationFrame(() => requestAnimationFrame(() => el.classList.add("shown")));
    return el;
  }

  static niceStep(raw) {
    const pow = 10 ** Math.floor(Math.log10(raw));
    const n = raw / pow;
    return (n < 1.5 ? 1 : n < 3 ? 2 : n < 7 ? 5 : 10) * pow;
  }
}
