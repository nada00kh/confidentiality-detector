// Admin overview: totals, daily activity, most detected data types and the latest events.
// Every number comes from the same list of scans, so the cards, the chart and the logs always agree.
(function () {
  const api = window.WashqAPI;
  const $ = (s) => document.querySelector(s);
  const nf = new Intl.NumberFormat("en-US");
  const COLORS = { allow: "#14243B", block: "#B4500F" };

  if (api.isMock) $("#demoBadge").hidden = false;

  const range = $("#range");
  try { const saved = localStorage.getItem("washq_admin_range"); if (saved) range.value = saved; } catch (e) { /* optional */ }
  range.addEventListener("change", () => {
    try { localStorage.setItem("washq_admin_range", range.value); } catch (e) { /* optional */ }
    render();
  });

  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const pct = (n, d) => d ? Math.round((n / d) * 100) + "%" : "0%";
  const day = (iso) => new Date(iso + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });
  const logsUrl = (params) => "logs.html?" + new URLSearchParams(params).toString();
  function when(iso) {
    const d = new Date(iso);
    const today = new Date(); today.setHours(0, 0, 0, 0);
    return d >= today
      ? d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false })
      : d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  }

  function kpis(s) {
    const days = s.days;
    $("#kpis").innerHTML = `
      <a class="kpi" href="${logsUrl({ days })}"><small>Total scans</small><strong>${nf.format(s.total)}</strong></a>
      <a class="kpi s-allow" href="${logsUrl({ decision: "ALLOW", days })}"><small><i></i>Allowed · clean</small><strong>${nf.format(s.allowed)}</strong></a>
      <a class="kpi s-block" href="${logsUrl({ decision: "BLOCK", days })}"><small><i></i>Blocked · sensitive</small><strong>${nf.format(s.blocked)}</strong></a>`;
  }

  function niceStep(x) {
    const p = Math.pow(10, Math.floor(Math.log10(x)));
    const f = x / p;
    return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p;
  }

  function chart(daily) {
    const W = 760, H = 240, L = 40, R = 8, T = 22, BOT = 30;
    const pw = W - L - R, ph = H - T - BOT;
    const totals = daily.map((d) => d.allow + d.block);
    const step = niceStep(Math.max(4, Math.max(...totals)) / 4);
    const top = Math.max(step, Math.ceil(Math.max(...totals, 1) / step) * step);
    const y = (v) => T + ph - (v / top) * ph;
    const slot = pw / daily.length;
    const bw = Math.min(46, slot * 0.62);
    const labelEvery = Math.ceil(daily.length / 10);
    let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Scans per day, allowed and blocked">`;
    svg += `<defs><linearGradient id="g-allow" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2E4D7A"/><stop offset="1" stop-color="#14243B"/></linearGradient>` +
      `<linearGradient id="g-block" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#E07A2E"/><stop offset="1" stop-color="#B4500F"/></linearGradient></defs>`;
    for (let v = 0; v <= top; v += step) {
      svg += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="${v === 0 ? "#D9D3C7" : "#EFEBE3"}"/>`;
      svg += `<text x="${L - 8}" y="${y(v) + 4}" text-anchor="end" font-size="11" fill="#5F6878">${v}</text>`;
    }
    daily.forEach((d, i) => {
      const x = L + i * slot + (slot - bw) / 2;
      let base = 0;
      svg += `<g class="day"><title>${day(d.date)}: ${totals[i]} scans (${d.allow} allowed, ${d.block} blocked)</title>`;
      ["allow", "block"].forEach((k) => {
        if (!d[k]) return;
        svg += `<rect x="${x}" y="${y(base + d[k])}" width="${bw}" height="${y(base) - y(base + d[k])}" rx="3" fill="url(#g-${k})"/>`;
        base += d[k];
      });
      if (daily.length <= 14 && totals[i]) {
        svg += `<text x="${x + bw / 2}" y="${y(totals[i]) - 5}" text-anchor="middle" font-size="11" font-weight="500" fill="#14243B">${totals[i]}</text>`;
      }
      svg += `</g>`;
      if (i % labelEvery === 0 || i === daily.length - 1) {
        svg += `<text x="${x + bw / 2}" y="${H - 10}" text-anchor="middle" font-size="11" fill="#5F6878">${day(d.date)}</text>`;
      }
    });
    $("#chart").innerHTML = svg + "</svg>";
  }

  function types(list) {
    if (!list.length) { $("#types").innerHTML = '<p class="panel-msg">No sensitive data detected in this period.</p>'; return; }
    const max = list[0].count;
    $("#types").innerHTML = list.map((t) => `
      <div class="hb"><span>${esc(t.label)}</span><div class="t"><div class="f" style="width:${Math.max(2, Math.round((t.count / max) * 100))}%"></div></div><span class="n">${nf.format(t.count)}</span></div>`).join("");
  }

  function latest(list) {
    if (!list.length) { $("#latest").innerHTML = '<p class="panel-msg">No events yet.</p>'; return; }
    $("#latest").innerHTML = list.map((e) => {
      const what = e.detected.length ? e.detected.map((d) => d.label).join(", ") : "No sensitive data";
      const cls = e.decision === "BLOCK" ? "s-block" : "s-allow";
      const href = logsUrl({ days: 30, q: e.operation_id, open: e.operation_id });
      return `<a class="ev ${cls}" href="${href}"><span class="muted">${when(e.time)}</span><span>${esc(what)}</span><span class="st">${e.decision}</span></a>`;
    }).join("");
  }

  async function render() {
    try {
      const s = await api.stats(+range.value);
      kpis(s);
      chart(s.daily);
      types(s.top_types);
      latest(s.latest);
    } catch (e) {
      $("#kpis").innerHTML = "";
      $("#chart").innerHTML = `<p class="panel-msg err">Couldn’t load the dashboard. ${esc(e.message)}</p>`;
      $("#types").innerHTML = "";
      $("#latest").innerHTML = "";
    }
  }

  render();
})();
