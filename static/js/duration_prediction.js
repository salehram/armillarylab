/* Plan Duration Prediction card (templates/_duration_prediction.html). */
(function () {
  "use strict";

  const SCENARIO_DESC = {
    baseline: "Every night clear. Limited only by darkness, minimum altitude, pack-up time and your nightly cap.",
    moon: "Moon-sensitive filters are only scheduled while the moon is down, or dim and far enough away (per-filter limits). Dark time goes to the most sensitive filters first.",
    weather: "Cloud, wind gusts and seeing from the forecast for the first nights, then monthly historical usable-night rates.",
    combined: "Moon limits and weather together — the most realistic estimate.",
  };

  const FILTER_COLORS = {
    H: "#e74c3c", S: "#f1c40f", O: "#1abc9c", L: "#bdc3c7",
    R: "#c0392b", G: "#27ae60", B: "#2980b9",
  };
  const FALLBACK_COLORS = ["#9b59b6", "#e67e22", "#16a085", "#d35400", "#7f8c8d", "#8e44ad", "#2c3e50"];
  const MOON_SHADE = "rgba(140, 160, 255, 0.22)";
  const MOON_LEGEND_LABEL = "Skipped (moon)";

  // Paints a full-height band behind each night skipped because of the moon.
  const moonShadePlugin = {
    id: "dpMoonShade",
    beforeDatasetsDraw(chart, args, opts) {
      const nights = (opts && opts.nights) || [];
      const legendIdx = chart.data.datasets.findIndex((d) => d.label === MOON_LEGEND_LABEL);
      if (legendIdx < 0 || !chart.isDatasetVisible(legendIdx)) return;
      const x = chart.scales.x;
      const area = chart.chartArea;
      const step = nights.length > 1 ? Math.abs(x.getPixelForValue(1) - x.getPixelForValue(0)) : area.right - area.left;
      const ctx = chart.ctx;
      ctx.save();
      ctx.fillStyle = MOON_SHADE;
      nights.forEach((n, i) => {
        if (n.status !== "moon") return;
        const cx = x.getPixelForValue(i);
        ctx.fillRect(cx - step / 2, area.top, step, area.bottom - area.top);
      });
      ctx.restore();
    },
  };

  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function fmtMin(minutes) {
    if (minutes == null || isNaN(minutes)) return "–";
    const total = Math.round(minutes);
    const h = Math.floor(total / 60);
    const m = total % 60;
    return h ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m`;
  }

  function fmtDate(iso) {
    if (!iso) return "–";
    const d = new Date(iso + "T12:00:00");
    return d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric", year: "numeric" });
  }

  function init(card) {
    const apiUrl = card.dataset.apiUrl;
    const saveUrl = card.dataset.saveUrl;
    const basisEl = card.querySelector(".dp-basis");
    const hoursEl = card.querySelector(".dp-hours");
    const effEl = card.querySelector(".dp-efficiency");
    const statusEl = card.querySelector(".dp-status");
    const contentEl = card.querySelector(".dp-content");
    const saveBtn = card.querySelector(".dp-save");
    const saveStatus = card.querySelector(".dp-save-status");
    let data = null;
    let scenario = "baseline";
    let chart = null;
    let firstLoad = true;
    let debounce = null;
    let requestSeq = 0;

    function buildUrl() {
      const url = new URL(apiUrl, window.location.origin);
      url.searchParams.set("basis", basisEl.value);
      if (!firstLoad) {
        const hours = parseFloat(hoursEl.value);
        url.searchParams.set("minutes_per_night", hours > 0 ? String(Math.round(hours * 60)) : "");
        if (effEl.value) url.searchParams.set("efficiency_pct", effEl.value);
      }
      return url.toString();
    }

    function load() {
      const seq = ++requestSeq;
      statusEl.classList.remove("d-none", "text-danger");
      statusEl.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status"></span>Calculating prediction&hellip;';
      fetch(buildUrl())
        .then((r) => r.json().then((body) => ({ ok: r.ok, body })))
        .then(({ ok, body }) => {
          if (seq !== requestSeq) return;
          if (!ok || body.error) throw new Error(body.error || "Request failed");
          data = body;
          if (firstLoad) {
            const mpn = body.inputs && body.inputs.minutes_per_night;
            hoursEl.value = mpn ? +(mpn / 60).toFixed(2) : "";
            effEl.value = body.inputs ? body.inputs.efficiency_pct : "";
            firstLoad = false;
          }
          render();
        })
        .catch((err) => {
          if (seq !== requestSeq) return;
          statusEl.classList.add("text-danger");
          statusEl.textContent = "Prediction unavailable: " + err.message;
          contentEl.classList.add("d-none");
        });
    }

    function scheduleLoad() {
      clearTimeout(debounce);
      debounce = setTimeout(load, 600);
    }

    function render() {
      if (!data.deps_available) {
        statusEl.textContent = data.note || "Astropy/astroplan not installed.";
        contentEl.classList.add("d-none");
        return;
      }
      if (!data.has_plan) {
        statusEl.textContent = "No plan channels to predict yet.";
        contentEl.classList.add("d-none");
        return;
      }
      statusEl.classList.add("d-none");
      contentEl.classList.remove("d-none");
      renderSources();
      renderVisibility();
      renderChannels();
      renderScenario();
    }

    function renderSources() {
      const s = data.sources || {};
      const parts = [];
      if (s.forecast === "none") parts.push("Forecast: offline");
      else parts.push(`Forecast${s.forecast === "cache" ? " (cached)" : ""} until ${s.forecast_until || "–"}`);
      if (s.seeing_until) parts.push(`seeing until ${s.seeing_until}`);
      if (s.climatology === "default") parts.push(`then ${s.default_usable_night_pct}% usable nights (default)`);
      else parts.push(`then historical climate${s.climatology === "stale_cache" ? " (cached)" : ""}`);
      card.querySelector(".dp-sources").textContent = parts.join(" · ");
    }

    function renderVisibility() {
      const rs = data.rise_set || {};
      const panels = data.panels || [];
      const tonight = data.tonight || [];
      const minAlt = panels.length ? panels[0].min_alt_deg : null;
      let html = '<table class="table table-sm table-dark mb-0"><tbody>';
      html += `<tr><th class="fw-normal opacity-75">Rises / Sets</th><td>${esc(rs.rise_local || "always up / never rises")} → ${esc(rs.set_local || "–")}</td></tr>`;
      html += `<tr><th class="fw-normal opacity-75">Above ${esc(minAlt)}°</th><td>${esc(rs.rise_min_alt_local || "–")} → ${esc(rs.set_min_alt_local || "–")}</td></tr>`;
      html += `<tr><th class="fw-normal opacity-75">Transit</th><td>${esc(rs.transit_local || "–")}</td></tr>`;
      tonight.forEach((t, i) => {
        const label = tonight.length > 1 ? `Window ${esc(panels[i] ? panels[i].name : "")}` : "Tonight's window";
        const span = t.start_local ? `${esc(t.start_local.slice(11))} → ${esc(t.end_local.slice(11))}` : "No usable window";
        html += `<tr><th class="fw-normal opacity-75">${label}</th><td>${span} <span class="opacity-75">(${fmtMin(t.window_minutes)})</span></td></tr>`;
      });
      if (tonight.length) {
        html += `<tr><th class="fw-normal opacity-75">Moon tonight</th><td>${esc(tonight[0].moon_illum_pct)}% illuminated</td></tr>`;
      }
      html += "</tbody></table>";
      card.querySelector(".dp-visibility").innerHTML = html;
    }

    function allChannels() {
      const rows = [];
      (data.panels || []).forEach((p) => p.channels.forEach((ch) => rows.push(Object.assign({ panel: p.name }, ch))));
      return rows;
    }

    function renderChannels() {
      const multi = (data.panels || []).length > 1;
      const rows = allChannels();
      let html = "<thead><tr>" + (multi ? "<th>Panel</th>" : "") +
        "<th>Channel</th><th>Filter</th><th>Planned</th><th>Done</th><th>To schedule</th><th>Frames</th><th title=\"Max moon illumination / min separation\">Moon limit</th></tr></thead><tbody>";
      let total = 0;
      rows.forEach((ch) => {
        total += ch.minutes;
        const frames = ch.sub_exposure_seconds ? Math.ceil((ch.minutes * 60) / ch.sub_exposure_seconds) : "–";
        html += "<tr>" + (multi ? `<td>${esc(ch.panel)}</td>` : "") +
          `<td>${esc(ch.label)} <span class="opacity-75">(${esc(ch.name)})</span></td>` +
          `<td>${esc(ch.filter_code)}</td>` +
          `<td>${fmtMin(ch.planned_minutes)}</td>` +
          `<td>${fmtMin(ch.done_minutes)}</td>` +
          `<td class="fw-semibold">${fmtMin(ch.minutes)}</td>` +
          `<td>${frames}${ch.sub_exposure_seconds ? ` × ${esc(ch.sub_exposure_seconds)}s` : ""}</td>` +
          `<td>≤${esc(ch.moon_max_illumination_pct)}% / ≥${esc(ch.moon_min_separation_deg)}°</td></tr>`;
      });
      html += `</tbody><tfoot><tr class="fw-semibold"><td colspan="${multi ? 5 : 4}">Total to schedule</td><td>${fmtMin(total)}</td><td colspan="2"></td></tr></tfoot>`;
      card.querySelector(".dp-channels").innerHTML = html;
    }

    function tile(label, value, sub) {
      return `<div class="col-6 col-md-3"><div class="p-2 rounded bg-dark h-100">
        <div class="small opacity-75">${label}</div>
        <div class="fs-5 fw-bold">${value}</div>
        ${sub ? `<div class="small opacity-75">${sub}</div>` : ""}</div></div>`;
    }

    function renderScenario() {
      card.querySelectorAll(".dp-tabs .nav-link").forEach((btn) => {
        btn.classList.toggle("active", btn.dataset.scenario === scenario);
      });
      const r = data.scenarios[scenario];
      card.querySelector(".dp-scenario-desc").textContent = SCENARIO_DESC[scenario];

      let tiles = "";
      if (r.total_minutes <= 0) {
        tiles = '<div class="col-12"><div class="alert alert-success py-2 mb-0">Nothing left to schedule — plan complete.</div></div>';
      } else {
        tiles += tile("Imaging nights", r.imaging_nights,
          r.completed ? `over ${r.calendar_nights} calendar night(s)` : `${r.completion_pct}% scheduled in ${data.horizon_nights} nights`);
        tiles += tile("Estimated finish", r.completed ? esc(fmtDate(r.finish_date)) : "Not within a year",
          `starting ${esc(fmtDate(r.start_date))}`);
        tiles += tile("Avg per imaging night", fmtMin(r.avg_session_minutes),
          `${fmtMin(r.avg_minutes_per_imaging_night)} of subs · max ${fmtMin(r.max_session_minutes)}`);
        const lost = [];
        if (r.nights_without_window) lost.push(`${r.nights_without_window} no window`);
        if (r.nights_lost_weather) lost.push(`${r.nights_lost_weather} weather`);
        if (r.nights_lost_moon) lost.push(`${r.nights_lost_moon} moon`);
        tiles += tile("Nights lost", r.nights_without_window + r.nights_lost_weather + r.nights_lost_moon,
          lost.join(" · ") || "none");
        if (!r.completed) {
          tiles += `<div class="col-12"><div class="alert alert-warning py-2 mb-0 small">
            ${fmtMin(r.remaining_minutes)} cannot be scheduled within ${data.horizon_nights} nights (target out of season or limits too strict).</div></div>`;
        }
      }
      card.querySelector(".dp-tiles").innerHTML = tiles;

      const multi = (data.panels || []).length > 1;
      let html = "<thead><tr><th>Channel</th><th>Integration</th><th>Nights</th><th>Finishes</th></tr></thead><tbody>";
      r.channels.forEach((ch) => {
        const label = multi ? `${esc(ch.key)}` : `${esc(ch.label)}`;
        const finish = ch.minutes <= 0 ? "done" : (ch.finish_date ? esc(fmtDate(ch.finish_date)) :
          `<span class="text-warning">${fmtMin(ch.remaining_minutes)} left</span>`);
        html += `<tr><td>${label}</td><td>${fmtMin(ch.minutes)}</td><td>${ch.nights_used}</td><td>${finish}</td></tr>`;
      });
      html += "</tbody>";
      card.querySelector(".dp-scenario-channels").innerHTML = html;
      renderChart(r);
    }

    function channelColor(ch, idx) {
      return FILTER_COLORS[ch.filter_code] || FALLBACK_COLORS[idx % FALLBACK_COLORS.length];
    }

    function renderChart(r) {
      const canvas = card.querySelector(".dp-chart");
      if (chart) { chart.destroy(); chart = null; }
      if (typeof Chart === "undefined" || !r.nights.length) return;
      const labels = r.nights.map((n) => n.date.slice(5));
      const datasets = r.channels.map((ch, i) => ({
        type: "bar",
        label: ch.key === ch.name ? ch.label : ch.key,
        data: r.nights.map((n) => (n.by_channel[ch.key] || 0)),
        backgroundColor: channelColor(ch, i),
        stack: "subs",
      }));
      datasets.push({
        type: "line",
        label: "Usable window",
        data: r.nights.map((n) => n.window_minutes),
        borderColor: "rgba(255,255,255,0.6)",
        borderWidth: 1,
        pointRadius: 0,
        fill: false,
      });
      if (r.nights.some((n) => n.status === "moon")) {
        // Legend-only entry; clicking it toggles the moon shading.
        datasets.push({
          type: "bar",
          label: MOON_LEGEND_LABEL,
          data: [],
          backgroundColor: MOON_SHADE,
          borderColor: "rgba(140, 160, 255, 0.8)",
          borderWidth: 1,
          stack: "moon",
        });
      }
      chart = new Chart(canvas.getContext("2d"), {
        data: { labels, datasets },
        plugins: [moonShadePlugin],
        options: {
          responsive: true,
          animation: false,
          plugins: {
            dpMoonShade: { nights: r.nights },
            legend: { labels: { color: "#ddd", boxWidth: 12 } },
            tooltip: {
              mode: "index",
              intersect: false,
              filter: (item) => item.raw > 0 || item.dataset.type === "line",
              callbacks: {
                title: (items) => {
                  const n = r.nights[items[0].dataIndex];
                  return `${n.date} — ${n.status.replace("_", " ")}`;
                },
                label: (item) => `${item.dataset.label}: ${fmtMin(item.raw)}`,
              },
            },
          },
          scales: {
            x: { stacked: true, ticks: { color: "#bbb", maxTicksLimit: 16 } },
            y: { stacked: true, beginAtZero: true, ticks: { color: "#bbb", callback: (v) => fmtMin(v) },
                 title: { display: true, text: "minutes", color: "#bbb" } },
          },
        },
      });
    }

    card.querySelectorAll(".dp-tabs .nav-link").forEach((btn) => {
      btn.addEventListener("click", () => {
        scenario = btn.dataset.scenario;
        if (data && data.scenarios) renderScenario();
      });
    });
    basisEl.addEventListener("change", load);
    hoursEl.addEventListener("input", scheduleLoad);
    effEl.addEventListener("input", scheduleLoad);
    card.querySelector(".dp-recalc").addEventListener("click", load);

    if (saveBtn && saveUrl) {
      saveBtn.addEventListener("click", () => {
        const hours = parseFloat(hoursEl.value);
        saveStatus.className = "small align-self-center dp-save-status";
        saveStatus.textContent = "Saving…";
        fetch(saveUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            minutes_per_night: hours > 0 ? Math.round(hours * 60) : 0,
            efficiency_pct: effEl.value || "",
          }),
        })
          .then((r) => r.json())
          .then((body) => {
            if (!body.ok) throw new Error(body.error || "Save failed");
            saveStatus.classList.add("text-success");
            saveStatus.textContent = "Saved";
          })
          .catch((err) => {
            saveStatus.classList.add("text-danger");
            saveStatus.textContent = err.message;
          });
      });
    }

    load();
  }

  document.addEventListener("DOMContentLoaded", () => {
    const card = document.getElementById("duration-prediction");
    if (card) init(card);
  });
})();
