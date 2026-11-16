// An animated number line. Call update() with the markers to show; markers,
// ticks and the highlighted range keep their DOM elements between updates so
// they glide to their new position when the scale changes.
//
//   line.update(
//     [{ key, value, label (HTML), cls, side: "top"|"bottom", row: 0|1 }],
//     { from, to } | null,     // highlighted range
//     [values]                 // optional small unlabeled dots (e.g. each team's answer)
//   )
//
// Markers and the range are always visible. The first marker is the target
// (the correct answer); the area target ± (distance to the furthest other
// marker) must cover at least MIN_SHARE of the line. Dots may widen the line
// only that far; dots further out are shown as arrows at the edge (up to
// MAX_ARROWS stacked, then "+N").

class NumberLine {
  static PAD = 0.18;            // empty space on each side, as a share of the data span
  static MIN_SHARE = 0.3;       // target ± worst marker distance never gets smaller than this
  static MAX_ARROWS = 5;

  constructor(el) {
    this.el = el;
    el.classList.add("nl");
    el.innerHTML = `<div class="nl-band"></div><div class="nl-axis"></div>
      <div class="nl-overflow left"></div><div class="nl-overflow right"></div>`;
    this.band = el.querySelector(".nl-band");
    this.overflow = { left: el.querySelector(".nl-overflow.left"), right: el.querySelector(".nl-overflow.right") };
    this.markers = new Map();
    this.ticks = new Map();
    this.dots = [];
  }

  /**
   * Work out the visible range. Pure function, so it can be tested without a DOM.
   * Returns { lo, hi, visible: [dots on the line], left: n, right: n }.
   */
  static domain(values, band, dots) {
    const required = band ? values.concat([band.from, band.to]) : values.slice();
    if (!required.length) return null;
    let lo = Math.min(...required), hi = Math.max(...required);

    // How wide the data span may get: target ± the worst marker distance (e.g.
    // the 1 or the average, whichever is further off) must stay >= MIN_SHARE
    // of the visible (padded) line. If every marker is spot on, fall back to
    // 40% of the target's size.
    const target = values[0];
    const worst = Math.max(...values.map((v) => Math.abs(v - target)));
    const ref = worst > 1e-9 ? 2 * worst : 2 * Math.max(Math.abs(target) * 0.2, 1);
    const scale = 1 / NumberLine.MIN_SHARE / (1 + 2 * NumberLine.PAD);
    const maxSpan = Math.max(hi - lo, ref * scale);

    // Include dots outside the required range, nearest first, while they fit.
    const dist = (v) => (v < lo ? lo - v : v > hi ? v - hi : 0);
    for (const v of dots.filter((v) => dist(v) > 0).sort((a, b) => dist(a) - dist(b))) {
      const nlo = Math.min(lo, v), nhi = Math.max(hi, v);
      if (nhi - nlo <= maxSpan) { lo = nlo; hi = nhi; }
    }
    const visible = dots.filter((v) => v >= lo && v <= hi);
    const left = dots.filter((v) => v < lo).length;
    const right = dots.filter((v) => v > hi).length;

    // Padding so labels don't hit the edges.
    if (hi - lo < 1e-9) {
      const pad = Math.max(Math.abs(lo) * 0.2, 1);
      lo -= pad; hi += pad;
    } else {
      const pad = (hi - lo) * NumberLine.PAD;
      lo -= pad; hi += pad;
    }
    return { lo, hi, visible, left, right };
  }

  update(markers, band, dots = []) {
    const d = NumberLine.domain(markers.map((m) => m.value), band, dots);
    if (!d) return;
    const { lo, hi } = d;
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
    const sorted = [...d.visible].sort((a, b) => a - b);
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

    // Arrows for dots beyond the edges.
    for (const [side, count] of [["left", d.left], ["right", d.right]]) {
      const el = this.overflow[side];
      if (el.dataset.count === String(count)) continue;
      el.dataset.count = count;
      const arrows = Math.min(count, NumberLine.MAX_ARROWS);
      let html = "";
      for (let i = 0; i < arrows; i++) html += `<span class="nl-arrow" style="--s:${i}">${side === "left" ? "◀" : "▶"}</span>`;
      if (count > arrows) html += `<span class="nl-more" style="--s:${arrows}">+${count - arrows}</span>`;
      el.innerHTML = html;
      el.title = `${count} answer${count === 1 ? "" : "s"} further ${side === "left" ? "below" : "above"}`;
      el.classList.toggle("shown", count > 0);
    }
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
