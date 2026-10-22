/*
 * Smart TRV card. Served and loaded by the smart_trv integration itself.
 *
 *   type: custom:smart-trv-card
 *   entity: climate.stue_varme_test
 *   name: Stue          # optional
 *   show_graph: true    # optional, 24 h room temperature vs target
 *
 * Finds the room's diagnostic sensors and night temperature through the device registry,
 * so only the climate entity has to be given.
 */

const CARD_VERSION = "0.3.1";

const TEXT = {
  da: {
    target: "Mål",
    trvSetpoint: "TRV-setpunkt",
    trvTemp: "TRV måler",
    learned: "Lært offset",
    error: "Afvigelse",
    night: "Nattemperatur",
    nightActive: "aktiv nu",
    graph: "Sidste 24 timer",
    room: "Rum",
    off: "Slukket",
    turnOn: "Tænd",
    turnOff: "Sluk",
    missing: "Entiteten findes ikke",
    choose: "Vælg en Smart TRV i kortets indstillinger.",
    status: {
      heating: "Varmer",
      idle: "Ventil lukket",
      window_open: "Vindue åbent",
      off: "Slukket",
      no_sensor: "Ingen rummåling",
    },
  },
  en: {
    target: "Target",
    trvSetpoint: "TRV setpoint",
    trvTemp: "TRV reads",
    learned: "Learned offset",
    error: "Error",
    night: "Night temperature",
    nightActive: "active now",
    graph: "Last 24 hours",
    room: "Room",
    off: "Off",
    turnOn: "Turn on",
    turnOff: "Turn off",
    missing: "Entity not found",
    choose: "Choose a Smart TRV in the card settings.",
    status: {
      heating: "Heating",
      idle: "Valve closed",
      window_open: "Window open",
      off: "Off",
      no_sensor: "No room reading",
    },
  },
};

const STATUS_COLOR = {
  heating: "var(--state-climate-heat-color, #ff8100)",
  idle: "var(--secondary-text-color, #727272)",
  window_open: "var(--info-color, #039be5)",
  off: "var(--disabled-text-color, #9e9e9e)",
  no_sensor: "var(--warning-color, #ffa600)",
};

const STATUS_ICON = { heating: "🔥", idle: "⏸", window_open: "🪟", off: "⭘", no_sensor: "⚠" };

const SUFFIXES = {
  status: "_status",
  trvSetpoint: "_trv_setpoint",
  trvTemp: "_trv_temperature",
  error: "_error",
  integral: "_integral",
};

const STEP = 0.5;
const DEBOUNCE_MS = 900;
const HISTORY_REFRESH_MS = 10 * 60 * 1000;

class SmartTrvCard extends HTMLElement {
  // HA's own form editor (no custom editor element to break).
  static getConfigForm() {
    return {
      schema: [
        {
          name: "entity",
          required: true,
          selector: { entity: { filter: { integration: "smart_trv", domain: "climate" } } },
        },
        { name: "name", selector: { text: {} } },
        { name: "show_graph", selector: { boolean: {} } },
      ],
      computeLabel: (schema) => {
        const da = (document.documentElement.lang || "").toLowerCase().startsWith("da");
        if (schema.name === "show_graph") return da ? "Vis graf (24 timer)" : "Show graph (24 h)";
        return undefined; // HA's own label for entity/name
      },
    };
  }

  // The card picker awaits this before it draws the preview: it must never throw.
  static getStubConfig(hass) {
    let entity = "";
    try {
      const reg = (hass && hass.entities) || {};
      entity =
        Object.keys((hass && hass.states) || {}).find(
          (id) => id.startsWith("climate.") && reg[id] && reg[id].platform === "smart_trv",
        ) || "";
    } catch (err) {
      console.warn("smart-trv-card: getStubConfig", err);
    }
    return { entity, show_graph: true };
  }

  setConfig(config) {
    if (config && config.entity && !String(config.entity).startsWith("climate.")) {
      throw new Error("Choose a Smart TRV climate entity (entity: climate.xxx)");
    }
    this._config = { show_graph: true, ...(config || {}) };
    this._signature = undefined;
    this._history = undefined;
    this._historyAt = 0;
    if (this._hass) this._render();
  }

  set hass(hass) {
    this._hass = hass;
    const sig = this._computeSignature();
    if (sig !== this._signature) {
      this._signature = sig;
      this._render();
    }
    this._maybeFetchHistory();
  }

  connectedCallback() {
    this._maybeFetchHistory();
  }

  getCardSize() {
    return this._config && this._config.show_graph ? 7 : 5;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }

  // ---------------------------------------------------------------- data

  get _t() {
    const lang = (this._hass && (this._hass.locale?.language || this._hass.language)) || "en";
    return TEXT[lang.split("-")[0]] || TEXT.en;
  }

  _related() {
    const hass = this._hass;
    const reg = hass.entities || {};
    const deviceId = reg[this._config.entity]?.device_id;
    const out = {};
    if (!deviceId) return out;
    for (const e of Object.values(reg)) {
      if (e.device_id !== deviceId) continue;
      const id = e.entity_id;
      if (id.startsWith("number.") && id.endsWith("_night_temperature")) out.night = id;
      if (!id.startsWith("sensor.")) continue;
      for (const [key, suffix] of Object.entries(SUFFIXES)) {
        if (id.endsWith(suffix)) out[key] = id;
      }
    }
    return out;
  }

  _computeSignature() {
    if (!this._config || !this._hass) return "";
    const ids = [this._config.entity, ...Object.values(this._related())];
    return ids
      .map((id) => {
        const s = this._hass.states[id];
        return s ? `${id}=${s.state}|${s.last_updated}` : `${id}=-`;
      })
      .join(";") + `;${this._pendingTarget};${this._pendingNight};${this._hass.locale?.language}`;
  }

  _num(id) {
    const s = id && this._hass.states[id];
    if (!s) return undefined;
    const v = parseFloat(s.state);
    return Number.isFinite(v) ? v : undefined;
  }

  _fmt(value, digits = 1) {
    if (value === undefined || value === null || Number.isNaN(value)) return "–";
    const lang = this._hass.locale?.language || this._hass.language || "en";
    const v = Math.abs(value) < 0.05 ? 0 : Number(value); // no "-0,0"
    return v.toLocaleString(lang, {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
  }

  async _maybeFetchHistory() {
    if (!this._config?.show_graph || !this._hass?.callWS) return;
    if (this._historyLoading || Date.now() - this._historyAt < HISTORY_REFRESH_MS) return;
    this._historyLoading = true;
    this._historyAt = Date.now();
    try {
      const start = new Date(Date.now() - 24 * 3600 * 1000).toISOString();
      const res = await this._hass.callWS({
        type: "history/history_during_period",
        start_time: start,
        entity_ids: [this._config.entity],
        minimal_response: false,
        no_attributes: false,
        significant_changes_only: false,
      });
      const rows = res[this._config.entity] || [];
      let attrs = {};
      this._history = rows
        .map((r) => {
          attrs = r.a || attrs;
          return {
            t: (r.lu || r.lc) * 1000,
            room: attrs.current_temperature,
            target: attrs.temperature,
          };
        })
        .filter((p) => Number.isFinite(p.t));
    } catch (err) {
      this._history = undefined; // graph is optional; the rest of the card still works
    } finally {
      this._historyLoading = false;
      this._signature = undefined;
      if (this._hass) this.hass = this._hass;
    }
  }

  // ------------------------------------------------------------- actions

  _changeTarget(delta) {
    const climate = this._hass.states[this._config.entity];
    const base = this._pendingTarget ?? climate.attributes.temperature;
    const min = climate.attributes.min_temp ?? 5;
    const max = climate.attributes.max_temp ?? 30;
    this._pendingTarget = Math.min(max, Math.max(min, Math.round((base + delta) / STEP) * STEP));
    this._renderNow();
    clearTimeout(this._targetTimer);
    this._targetTimer = setTimeout(async () => {
      const temperature = this._pendingTarget;
      try {
        await this._hass.callService("climate", "set_temperature", {
          entity_id: this._config.entity,
          temperature,
        });
      } finally {
        this._pendingTarget = undefined;
        this._renderNow();
      }
    }, DEBOUNCE_MS);
  }

  _changeNight(delta, id) {
    const base = this._pendingNight ?? this._num(id) ?? 19;
    this._pendingNight = Math.min(30, Math.max(5, Math.round((base + delta) / STEP) * STEP));
    this._renderNow();
    clearTimeout(this._nightTimer);
    this._nightTimer = setTimeout(async () => {
      const value = this._pendingNight;
      try {
        await this._hass.callService("number", "set_value", { entity_id: id, value });
      } finally {
        this._pendingNight = undefined;
        this._renderNow();
      }
    }, DEBOUNCE_MS);
  }

  _togglePower() {
    const climate = this._hass.states[this._config.entity];
    this._hass.callService("climate", "set_hvac_mode", {
      entity_id: this._config.entity,
      hvac_mode: climate.state === "off" ? "heat" : "off",
    });
  }

  _moreInfo(entityId) {
    const ev = new Event("hass-more-info", { bubbles: true, composed: true });
    ev.detail = { entityId };
    this.dispatchEvent(ev);
  }

  // ------------------------------------------------------------- render

  _renderNow() {
    this._signature = undefined;
    this.hass = this._hass;
  }

  _render() {
    if (!this._config || !this._hass) return;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const t = this._t;
    if (!this._config.entity) {
      this.shadowRoot.innerHTML = `${STYLE}<ha-card><div class="hint">🌡️ ${t.choose}</div></ha-card>`;
      return;
    }
    const climate = this._hass.states[this._config.entity];
    if (!climate) {
      this.shadowRoot.innerHTML = `${STYLE}<ha-card><div class="missing">${t.missing}: ${esc(
        this._config.entity,
      )}</div></ha-card>`;
      return;
    }

    const rel = this._related();
    const a = climate.attributes;
    const statusState = rel.status && this._hass.states[rel.status];
    const status = statusState ? statusState.state : climate.state === "off" ? "off" : "idle";
    const statusLabel =
      (statusState && this._hass.formatEntityState?.(statusState)) || t.status[status] || status;
    const explanation = statusState?.attributes.explanation || "";
    const [mainText, ...warnings] = explanation.split(" ⚠️ ");
    const target = this._pendingTarget ?? a.temperature;
    const isOff = climate.state === "off";
    const nightActive = a.night_active === true;
    const nightValue = this._pendingNight ?? this._num(rel.night);
    const name = this._config.name || a.friendly_name || this._config.entity;
    const color = STATUS_COLOR[status] || STATUS_COLOR.idle;

    const stats = [
      [t.trvSetpoint, this._num(rel.trvSetpoint), rel.trvSetpoint, "°"],
      [t.trvTemp, this._num(rel.trvTemp), rel.trvTemp, "°"],
      [t.learned, this._num(rel.integral), rel.integral, "°", true],
      [t.error, this._num(rel.error), rel.error, "°", true],
    ].filter((s) => s[2]);

    this.shadowRoot.innerHTML = `
      ${STYLE}
      <ha-card style="--status-color: ${color}">
        <div class="header">
          <div class="name">${esc(name)}</div>
          <button class="chip" data-more="${esc(rel.status || this._config.entity)}">
            <span>${nightActive ? "🌙 " : ""}${STATUS_ICON[status] || ""}</span>
            <span>${esc(statusLabel)}</span>
          </button>
          <button class="icon power ${isOff ? "" : "on"}" data-action="power"
                  title="${isOff ? t.turnOn : t.turnOff}" aria-label="${isOff ? t.turnOn : t.turnOff}">
            ${POWER_SVG}
          </button>
        </div>

        <div class="main ${isOff ? "dim" : ""}">
          <div class="current" data-more="${esc(this._config.entity)}">
            <span class="value">${this._fmt(a.current_temperature)}</span><span class="unit">°C</span>
            <div class="label">${t.room}</div>
          </div>
          <div class="target">
            <button class="icon" data-action="target-down" aria-label="−">${MINUS_SVG}</button>
            <div class="target-value ${this._pendingTarget !== undefined ? "pending" : ""}">
              <div class="label">${nightActive ? "🌙 " : ""}${t.target}</div>
              <div class="big">${this._fmt(target)}°</div>
            </div>
            <button class="icon" data-action="target-up" aria-label="+">${PLUS_SVG}</button>
          </div>
        </div>

        ${this._config.show_graph ? this._graph(a) : ""}

        ${
          stats.length
            ? `<div class="stats">${stats
                .map(
                  ([label, v, id, unit, signed]) => `
              <button class="stat" data-more="${esc(id)}">
                <div class="stat-value">${signed && v >= 0.05 ? "+" : ""}${this._fmt(v)}${unit}</div>
                <div class="label">${label}</div>
              </button>`,
                )
                .join("")}</div>`
            : ""
        }

        ${mainText ? `<div class="explanation">${esc(mainText)}</div>` : ""}
        ${warnings.map((w) => `<div class="warning">⚠️ ${esc(w)}</div>`).join("")}

        ${
          rel.night
            ? `<div class="night ${nightActive ? "active" : ""}">
            <div class="night-label">🌙 ${t.night}${
              nightActive ? ` <span class="badge">${t.nightActive}</span>` : ""
            }</div>
            <div class="night-ctrl">
              <button class="icon small" data-action="night-down" aria-label="−">${MINUS_SVG}</button>
              <span class="night-value ${this._pendingNight !== undefined ? "pending" : ""}">${this._fmt(
                nightValue,
              )}°</span>
              <button class="icon small" data-action="night-up" aria-label="+">${PLUS_SVG}</button>
            </div>
          </div>`
            : ""
        }
      </ha-card>`;

    const root = this.shadowRoot;
    root.querySelector('[data-action="power"]').onclick = () => this._togglePower();
    root.querySelector('[data-action="target-down"]').onclick = () => this._changeTarget(-STEP);
    root.querySelector('[data-action="target-up"]').onclick = () => this._changeTarget(STEP);
    if (rel.night) {
      root.querySelector('[data-action="night-down"]').onclick = () => this._changeNight(-STEP, rel.night);
      root.querySelector('[data-action="night-up"]').onclick = () => this._changeNight(STEP, rel.night);
    }
    root.querySelectorAll("[data-more]").forEach((el) => {
      el.onclick = () => this._moreInfo(el.dataset.more);
    });
  }

  _graph(a) {
    const pts = (this._history || []).slice();
    const now = Date.now();
    if (a.current_temperature !== undefined) {
      pts.push({ t: now, room: a.current_temperature, target: a.temperature });
    }
    const room = pts.filter((p) => Number.isFinite(p.room));
    if (room.length < 2) return `<div class="graph empty"></div>`;

    const W = 300;
    const H = 70;
    const t0 = now - 24 * 3600 * 1000;
    const values = pts.flatMap((p) => [p.room, p.target]).filter(Number.isFinite);
    let lo = Math.min(...values);
    let hi = Math.max(...values);
    if (hi - lo < 1) {
      const mid = (hi + lo) / 2;
      lo = mid - 0.5;
      hi = mid + 0.5;
    }
    lo -= 0.2;
    hi += 0.2;
    const x = (t) => (((Math.max(t, t0) - t0) / (now - t0)) * W).toFixed(1);
    const y = (v) => (H - ((v - lo) / (hi - lo)) * H).toFixed(1);

    const roomPath = room.map((p, i) => `${i ? "L" : "M"}${x(p.t)},${y(p.room)}`).join("");
    let targetPath = "";
    let prev;
    for (const p of pts.filter((q) => Number.isFinite(q.target))) {
      targetPath += prev === undefined ? `M${x(p.t)},${y(p.target)}` : `H${x(p.t)}V${y(p.target)}`;
      prev = p.target;
    }
    if (prev !== undefined) targetPath += `H${W}`;
    const area = `${roomPath}L${x(room[room.length - 1].t)},${H}L${x(room[0].t)},${H}Z`;
    const t = this._t;

    return `
      <div class="graph" title="${t.graph}">
        <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-label="${t.graph}">
          <path class="area" d="${area}"></path>
          <path class="target-line" d="${targetPath}" vector-effect="non-scaling-stroke"></path>
          <path class="room-line" d="${roomPath}" vector-effect="non-scaling-stroke"></path>
        </svg>
        <div class="graph-legend">
          <span><i class="dot room"></i>${t.room}</span>
          <span><i class="dot tgt"></i>${t.target}</span>
          <span class="range">${this._fmt(lo + 0.2)}–${this._fmt(hi - 0.2)}° · ${t.graph}</span>
        </div>
      </div>`;
  }
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

const MINUS_SVG = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 11h14v2H5z"/></svg>`;
const PLUS_SVG = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M11 5h2v6h6v2h-6v6h-2v-6H5v-2h6z"/></svg>`;
const POWER_SVG = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M13 3h-2v10h2V3zm4.83 2.17-1.42 1.42A6.92 6.92 0 0 1 19 12a7 7 0 1 1-11.41-5.41L6.17 5.17A8.93 8.93 0 0 0 3 12a9 9 0 0 0 18 0c0-2.74-1.23-5.18-3.17-6.83z"/></svg>`;

const STYLE = `<style>
  :host { display: block; }
  ha-card { padding: 16px; display: flex; flex-direction: column; gap: 14px; overflow: hidden; }
  button { font: inherit; color: inherit; background: none; border: 0; padding: 0; cursor: pointer; }
  .missing { color: var(--error-color, #db4437); }
  .hint { color: var(--secondary-text-color); }
  .header { display: flex; align-items: center; gap: 8px; }
  .name { flex: 1; font-size: 1.1rem; font-weight: 500; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .chip { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 999px;
          font-size: .85rem; font-weight: 500; color: var(--status-color);
          background: color-mix(in srgb, var(--status-color) 14%, transparent); white-space: nowrap; }
  .icon { width: 40px; height: 40px; border-radius: 50%; display: grid; place-items: center; flex: none;
          background: var(--secondary-background-color, rgba(127,127,127,.1)); }
  .icon:hover { background: color-mix(in srgb, var(--primary-text-color) 12%, transparent); }
  .icon:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
  .icon svg { width: 22px; height: 22px; fill: currentColor; }
  .icon.small { width: 32px; height: 32px; }
  .icon.small svg { width: 18px; height: 18px; }
  .power { color: var(--disabled-text-color, #9e9e9e); }
  .power.on { color: var(--status-color); }
  .main { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
  .main.dim { opacity: .5; }
  .current { cursor: pointer; }
  .current .value { font-size: 3rem; font-weight: 400; line-height: 1; letter-spacing: -.02em;
                    font-variant-numeric: tabular-nums; }
  .current .unit { font-size: 1.1rem; color: var(--secondary-text-color); margin-left: 2px; vertical-align: top; }
  .label { font-size: .75rem; color: var(--secondary-text-color); }
  .target { display: flex; align-items: center; gap: 10px; }
  .target-value { text-align: center; min-width: 64px; }
  .target-value .big { font-size: 1.6rem; font-weight: 500; color: var(--status-color); font-variant-numeric: tabular-nums; }
  .pending { opacity: .6; }
  .graph svg { width: 100%; height: 70px; display: block; }
  .graph.empty { height: 0; }
  .area { fill: color-mix(in srgb, var(--status-color) 12%, transparent); }
  .room-line { fill: none; stroke: var(--primary-color, #03a9f4); stroke-width: 2; }
  .target-line { fill: none; stroke: var(--status-color); stroke-width: 1.5; stroke-dasharray: 4 3; }
  .graph-legend { display: flex; gap: 12px; font-size: .72rem; color: var(--secondary-text-color); margin-top: 4px; }
  .graph-legend .range { margin-left: auto; }
  .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 4px; vertical-align: middle; }
  .dot.room { background: var(--primary-color, #03a9f4); }
  .dot.tgt { background: var(--status-color); }
  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(70px, 1fr)); gap: 8px; }
  .stat { text-align: left; padding: 8px 10px; border-radius: 10px;
          background: var(--secondary-background-color, rgba(127,127,127,.08)); }
  .stat-value { font-size: 1rem; font-weight: 500; font-variant-numeric: tabular-nums; }
  .explanation { font-size: .85rem; line-height: 1.45; color: var(--secondary-text-color); }
  .warning { font-size: .85rem; line-height: 1.45; padding: 8px 10px; border-radius: 10px;
             color: var(--primary-text-color);
             background: color-mix(in srgb, var(--warning-color, #ffa600) 18%, transparent); }
  .night { display: flex; align-items: center; justify-content: space-between; gap: 8px;
           border-top: 1px solid var(--divider-color, rgba(127,127,127,.2)); padding-top: 12px; }
  .night.active .night-label { color: var(--primary-text-color); font-weight: 500; }
  .night-label { font-size: .9rem; color: var(--secondary-text-color); }
  .badge { font-size: .7rem; padding: 2px 6px; border-radius: 999px; margin-left: 4px;
           background: color-mix(in srgb, var(--primary-color, #03a9f4) 18%, transparent); }
  .night-ctrl { display: flex; align-items: center; gap: 8px; }
  .night-value { min-width: 48px; text-align: center; font-weight: 500; font-variant-numeric: tabular-nums; }
</style>`;

if (!customElements.get("smart-trv-card")) {
  customElements.define("smart-trv-card", SmartTrvCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "smart-trv-card",
    name: "Smart TRV",
    description: "Room temperature, target, what the controller is doing and the night temperature.",
    preview: true,
    documentationURL: "https://github.com/Tntdruid/ha-smart-trv",
  });
  console.info(`%c SMART-TRV-CARD %c ${CARD_VERSION} `, "background:#ff8100;color:#fff", "");
}
