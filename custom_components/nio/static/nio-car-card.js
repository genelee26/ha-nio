/**
 * nio-car-card — Lovelace card bundled with the NIO integration.
 *
 * Zero external dependencies (no card_mod / browser_mod / streamline-card):
 * vanilla custom elements, own popup overlay, ha-form based visual editor.
 * Entities are resolved from the selected device via the entity registry
 * (matched by unique_id suffix), so renamed entity_ids keep working.
 */

const STATIC_BASE = "/nio_static";
const ASSET_VER = "9"; // bump when images under static/cars change (cache-buster)
const MANIFEST_URL = `${STATIC_BASE}/cars/cars_manifest.json?a=${ASSET_VER}`;

let _manifestPromise = null;
function fetchCarsManifest() {
  if (!_manifestPromise) {
    _manifestPromise = fetch(MANIFEST_URL).then((r) => {
      if (!r.ok) throw new Error(`cars_manifest.json HTTP ${r.status}`);
      return r.json();
    });
  }
  return _manifestPromise;
}

let _registryPromise = null;
function fetchEntityRegistry(hass) {
  if (!_registryPromise) {
    _registryPromise = hass.callWS({ type: "config/entity_registry/list" });
  }
  return _registryPromise;
}

/** unique_id is `<vehicle_id>_<key>`; match longest key first to avoid
 *  `remaining_range` swallowing `remaining_actual_range`. */
const ENTITY_KEYS = [
  "range_achievement_rate",
  "remaining_actual_range",
  "remaining_range",
  "battery",
  "driving",
  "sleeping",
  "door",
  "window",
  "lock",
  "refresh",
  "location",
];

async function resolveDeviceEntities(hass, deviceId) {
  const registry = await fetchEntityRegistry(hass);
  const mine = registry.filter((e) => e.device_id === deviceId && !e.disabled_by);
  const map = {};
  for (const entry of mine) {
    const uid = entry.unique_id || "";
    for (const key of ENTITY_KEYS) {
      if (!map[key] && uid.endsWith(`_${key}`)) {
        map[key] = entry.entity_id;
        break;
      }
    }
  }
  return map;
}

function fireEvent(node, type, detail) {
  node.dispatchEvent(
    new CustomEvent(type, { detail, bubbles: true, composed: true })
  );
}

function formatState(hass, entityId) {
  const st = hass.states[entityId];
  if (!st) return "—";
  if (typeof hass.formatEntityState === "function") {
    return hass.formatEntityState(st);
  }
  const unit = st.attributes.unit_of_measurement;
  return unit ? `${st.state} ${unit}` : st.state;
}

/* ---------------------------------------------------------------- card */

class NioCarCard extends HTMLElement {
  static getConfigElement() {
    return document.createElement("nio-car-card-editor");
  }

  static getStubConfig() {
    return { model: "ec6", color: "cloud_white" };
  }

  setConfig(config) {
    this._config = config || {};
    this._entities = null;
    this._resolving = false;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (this._config?.device_id && !this._entities && !this._resolving) {
      this._resolving = true;
      resolveDeviceEntities(hass, this._config.device_id)
        .then((map) => {
          this._entities = map;
          this._render();
        })
        .catch(() => {
          this._resolving = false;
        });
    }
    this._updateStates();
  }

  getCardSize() {
    return 4;
  }

  // "auto" lets the sections grid size the card to its real content height
  // instead of forcing a fixed row count (which created the gap below the car)
  getLayoutOptions() {
    return { grid_rows: "auto", grid_columns: "full", grid_min_rows: 3 };
  }

  _imageUrl() {
    if (this._config.image) return this._config.image; // manual override wins
    const model = this._config.model || "ec6";
    const color = this._config.color || "cloud_white";
    return `${STATIC_BASE}/cars/${model}_${color}.webp?a=${ASSET_VER}`;
  }

  _title() {
    if (this._config.name) return this._config.name;
    const model = (this._config.model || "EC6").toUpperCase();
    return `NIO ${model}`;
  }

  // bar title sits next to the brand logo, so drop a leading "NIO " to avoid
  // showing the marque twice (logo + word). Popup keeps the full _title().
  _nameOnly() {
    return this._title().replace(/^NIO\s+/i, "");
  }

  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const cfg = this._config || {};
    // Backdrop: chosen RGB (default neutral studio grey) × a black/white
    // luminosity gradient (light top-left → dark bottom-right + soft
    // highlight behind the car) — replicates the official studio look.
    const baseRgb = Array.isArray(cfg.bg_color) ? cfg.bg_color.join(",") : "228,229,231";
    const useGradient = cfg.bg_gradient !== false;
    let bgImage;
    if (cfg.bg_image) {
      bgImage = `background: url('${cfg.bg_image}') center / cover;`;
    } else if (useGradient) {
      bgImage =
        `background-color: rgb(${baseRgb});` +
        `background-image:` +
        ` linear-gradient(135deg, rgba(255,255,255,.55) 0%, rgba(255,255,255,0) 42%, rgba(0,0,0,.32) 100%),` +
        ` radial-gradient(ellipse 70% 45% at 50% 32%, rgba(255,255,255,.22), rgba(255,255,255,0) 70%);`;
    } else {
      bgImage = Array.isArray(cfg.bg_color)
        ? `background: rgb(${baseRgb});`
        : `background: var(--card-background-color);`;
    }
    const barRgb = Array.isArray(cfg.bar_color) ? cfg.bar_color : [0, 0, 0];
    const barOpacity = (cfg.bar_opacity ?? 40) / 100;
    // readable foreground on light vs dark bar colors
    const lum = 0.299 * barRgb[0] + 0.587 * barRgb[1] + 0.114 * barRgb[2];
    const barFg = lum > 150 ? "#1c1c1c" : "#ffffff";
    const showLabels = cfg.show_labels !== false;
    const iconItems = [
      { key: "battery" },
      { key: "driving" },
      { key: "sleeping" },
      { key: "door" },
      { key: "window" },
    ];
    this.shadowRoot.innerHTML = `
      <style>
        ha-card { overflow: hidden; position: relative; padding: 0; }
        /* backdrop lives on an inner div so themes / card-mod rules that
           force ha-card background (often !important) cannot override it.
           Height flows from content (car image + bar) — no fixed aspect
           ratio, so there is never letterbox gap above or below the car. */
        .canvas { display: flex; flex-direction: column; ${bgImage} }
        .img-wrap { width: 100%; cursor: pointer; font-size: 0; }
        .img-wrap img { width: 100%; height: auto; display: block;
                        box-sizing: border-box; padding: 3% 3%; }
        .bar { flex: 0 0 auto;
               display: flex; align-items: center; justify-content: space-between;
               padding: 8px 16px; box-sizing: border-box;
               background: rgba(${barRgb.join(",")}, ${barOpacity});
               backdrop-filter: blur(5px); -webkit-backdrop-filter: blur(5px);
               color: ${barFg}; cursor: pointer; }
        /* brand logo + name + range share one line, one weight, one size —
           a single baseline so nothing drifts. The logo is the map-marker
           glyph used as a mask, filled with the bar's foreground colour so it
           tracks light/dark bars automatically. */
        .title { display: flex; align-items: center; gap: 7px;
                 font-size: 16px; font-weight: 500; white-space: nowrap; }
        .brand { flex: none; width: 20px; height: 20px; background-color: currentColor;
                 -webkit-mask: url(${STATIC_BASE}/nio_brand.png?a=${ASSET_VER}) no-repeat center / contain;
                 mask: url(${STATIC_BASE}/nio_brand.png?a=${ASSET_VER}) no-repeat center / contain; }
        .title .range { margin-left: 5px; opacity: .92; }
        .icons { display: flex; gap: 14px; }
        .icon-item { display: flex; flex-direction: column; align-items: center; min-width: 34px; }
        .icon-item ha-icon { --mdc-icon-size: 22px; color: ${barFg}; }
        .icon-item.alert ha-icon { color: var(--error-color, #d83931); }
        .icon-item .lbl { font-size: 10px; margin-top: 1px; opacity: .9;
                          display: ${showLabels ? "block" : "none"}; }
        .hint { padding: 24px 16px; color: var(--secondary-text-color); }
      </style>
      <ha-card>
        <div class="canvas">
        <div class="img-wrap" id="img"><img src="${this._imageUrl()}" alt=""></div>
        <div class="bar" id="bar">
          <span class="title"><span class="brand"></span><span>${this._nameOnly()}</span><span class="range" id="range"></span></span>
          <div class="icons">
            ${iconItems
              .map(
                (it) =>
                  `<div class="icon-item" id="ic_${it.key}">
                     <ha-icon icon="mdi:help-circle-outline"></ha-icon>
                     <span class="lbl"></span>
                   </div>`
              )
              .join("")}
          </div>
        </div>
        </div>
        ${
          this._config.device_id
            ? ""
            : `<div class="hint">未选择车辆——编辑卡片，在「车辆」里选中你的 NIO 设备。</div>`
        }
      </ha-card>
    `;
    const open = () => this._openPopup();
    this.shadowRoot.getElementById("img").addEventListener("click", open);
    this.shadowRoot.getElementById("bar").addEventListener("click", open);
    this._updateStates();
  }

  /* The popup is mounted on document.body, NOT inside the card's shadow DOM:
   * themes that put transform/backdrop-filter on ha-card turn the card into
   * the containing block for position:fixed, clipping the dialog to the card. */
  _openPopup() {
    if (!this._entities || !this._hass) return;
    this._closePopup();
    const ov = document.createElement("div");
    ov.className = "nio-cc-overlay";
    ov.innerHTML = `
      <style>
        .nio-cc-overlay { position: fixed; inset: 0; z-index: 10000; display: flex;
                          align-items: center; justify-content: center;
                          background: rgba(0,0,0,.45); }
        .nio-cc-dialog { background: var(--card-background-color, #fff);
                         color: var(--primary-text-color, #1c1c1c);
                         border-radius: var(--ha-card-border-radius, 12px);
                         width: min(420px, 92vw); max-height: 86vh; overflow-y: auto;
                         box-shadow: 0 8px 32px rgba(0,0,0,.35);
                         font-family: var(--mdc-typography-font-family, Roboto, system-ui, sans-serif); }
        .nio-cc-head { display: flex; align-items: center; justify-content: space-between;
                       padding: 14px 18px 4px; font-size: 18px; font-weight: 500; }
        .nio-cc-head ha-icon { cursor: pointer; color: var(--secondary-text-color); }
        .nio-cc-body { padding: 6px 18px; }
        .nio-cc-body h3 { font-size: 17px; font-weight: 600; margin: 18px 0 6px;
                          color: var(--primary-text-color); }
        .nio-cc-body h3:first-child { margin-top: 6px; }
        .nio-cc-row { display: flex; justify-content: space-between; padding: 12px 0;
                      cursor: pointer; font-size: 14px; }
        .nio-cc-row .val { color: var(--secondary-text-color); }
        .nio-cc-foot { display: flex; justify-content: space-between; padding: 12px 18px 16px; }
        .nio-cc-foot button { background: none; border: none; cursor: pointer;
                              color: var(--primary-color, #03a9f4); font-size: 14px;
                              font-weight: 500; padding: 8px 12px; border-radius: 6px; }
      </style>
      <div class="nio-cc-dialog">
        <div class="nio-cc-head">
          <span>${this._title()} 车辆状态</span>
          <ha-icon icon="mdi:close" class="nio-cc-close"></ha-icon>
        </div>
        <div class="nio-cc-body"></div>
        <div class="nio-cc-foot">
          <button class="nio-cc-refresh">数据刷新</button>
          <button class="nio-cc-done">完成</button>
        </div>
      </div>
    `;
    ov.addEventListener("click", (e) => {
      if (e.target === ov) this._closePopup();
    });
    ov.querySelector(".nio-cc-close").addEventListener("click", () => this._closePopup());
    ov.querySelector(".nio-cc-done").addEventListener("click", () => this._closePopup());
    ov.querySelector(".nio-cc-refresh").addEventListener("click", () => {
      const ent = this._entities?.refresh;
      if (ent && this._hass) {
        this._hass.callService("button", "press", { entity_id: ent });
      }
    });
    document.body.appendChild(ov);
    this._overlay = ov;
    this._renderPopupBody();
  }

  _closePopup() {
    if (this._overlay) {
      this._overlay.remove();
      this._overlay = null;
    }
  }

  disconnectedCallback() {
    this._closePopup();
  }

  _renderPopupBody() {
    if (!this._hass || !this._entities || !this._overlay) return;
    const E = this._entities;
    const sections = [
      { title: "车辆状态", rows: [["驾驶状态", E.driving], ["睡眠状态", E.sleeping]] },
      {
        title: "能源与续航",
        rows: [
          ["电池电量", E.battery],
          ["续航(CLTC)", E.remaining_range],
          ["续航(实际)", E.remaining_actual_range],
          ["续航达成率", E.range_achievement_rate],
        ],
      },
      { title: "安防细节", rows: [["车门状态", E.door], ["车窗状态", E.window]] },
    ];
    const body = this._overlay.querySelector(".nio-cc-body");
    body.innerHTML = sections
      .map(
        (s) => `
        <h3>${s.title}</h3>
        ${s.rows
          .filter(([, ent]) => ent)
          .map(
            ([label, ent]) => `
            <div class="nio-cc-row" data-entity="${ent}">
              <span>${label}</span>
              <span class="val">${formatState(this._hass, ent)}</span>
            </div>`
          )
          .join("")}`
      )
      .join("");
    body.querySelectorAll(".nio-cc-row").forEach((row) => {
      row.addEventListener("click", () => {
        this._closePopup();
        fireEvent(this, "hass-more-info", { entityId: row.dataset.entity });
      });
    });
  }

  _updateStates() {
    if (!this.shadowRoot || !this._hass || !this._entities) return;
    const hass = this._hass;
    const E = this._entities;

    const rangeEl = this.shadowRoot.getElementById("range");
    if (rangeEl && E.remaining_range && hass.states[E.remaining_range]) {
      const v = hass.states[E.remaining_range].state;
      rangeEl.textContent = isNaN(parseFloat(v)) ? "" : `- ${Math.round(v)} km`;
    }

    const setIcon = (key, icon, label, alert = false) => {
      const el = this.shadowRoot.getElementById(`ic_${key}`);
      if (!el) return;
      el.querySelector("ha-icon").setAttribute("icon", icon);
      el.querySelector(".lbl").textContent = label;
      el.classList.toggle("alert", alert);
    };
    const stateOf = (ent) => (ent && hass.states[ent] ? hass.states[ent].state : null);

    const batt = stateOf(E.battery);
    if (batt !== null) {
      const lvl = Math.max(0, Math.min(100, Math.round(parseFloat(batt) / 10) * 10));
      const icon =
        lvl >= 100 ? "mdi:battery" : `mdi:battery-${lvl === 0 ? "outline" : lvl}`;
      setIcon("battery", icon, `${Math.round(parseFloat(batt))}%`, parseFloat(batt) < 20);
    }
    const driving = stateOf(E.driving);
    if (driving !== null) {
      setIcon("driving", driving === "on" ? "mdi:steering" : "mdi:car-off",
              driving === "on" ? "行驶" : "停放");
    }
    const sleeping = stateOf(E.sleeping);
    if (sleeping !== null) {
      setIcon("sleeping", sleeping === "on" ? "mdi:sleep" : "mdi:sleep-off",
              sleeping === "on" ? "休眠" : "唤醒");
    }
    const door = stateOf(E.door);
    if (door !== null) {
      setIcon("door", door === "on" ? "mdi:car-door" : "mdi:car-door-lock",
              door === "on" ? "未关" : "已关", door === "on");
    }
    const win = stateOf(E.window);
    if (win !== null) {
      setIcon("window", win === "on" ? "mdi:window-open-variant" : "mdi:window-closed-variant",
              win === "on" ? "未关" : "已关", win === "on");
    }
    // live-refresh popup values while it is open
    if (this._overlay && this._overlay.isConnected) this._renderPopupBody();
  }
}

/* -------------------------------------------------------------- editor */

class NioCarCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { ...config };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (this._form) this._form.hass = hass;
  }

  _schema() {
    return [
      {
        name: "device_id",
        selector: { device: { integration: "nio" } },
      },
      { name: "name", selector: { text: {} } },
      {
        name: "bar_opacity",
        selector: { number: { min: 0, max: 100, step: 5, mode: "slider", unit_of_measurement: "%" } },
      },
      { name: "show_labels", selector: { boolean: {} } },
      { name: "bg_gradient", selector: { boolean: {} } },
      { name: "bg_image", selector: { text: {} } },
    ];
  }

  async _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const manifest = await fetchCarsManifest().catch(() => ({}));
    this._manifest = manifest;
    const model = this._config.model || Object.keys(manifest)[0] || "ec6";
    const colors = manifest[model]?.colors || [];

    const toHex = (arr, fallback) =>
      Array.isArray(arr)
        ? "#" + arr.map((x) => Math.max(0, Math.min(255, x)).toString(16).padStart(2, "0")).join("")
        : fallback;
    const hexBg = toHex(this._config.bg_color, "#f0f0f0");
    const hexBar = toHex(this._config.bar_color, "#000000");

    this.shadowRoot.innerHTML = `
      <style>
        .grp { margin: 12px 0 4px; font-weight: 500; }
        .colorrow { display: flex; align-items: center; gap: 10px; margin: 6px 0; font-size: 14px; }
        .colorrow span { width: 80px; }
        .colorrow input[type=color] { width: 48px; height: 28px; border: 1px solid var(--divider-color);
                                      border-radius: 6px; padding: 1px; background: none; cursor: pointer; }
        .colorrow button { border: 1px solid var(--divider-color); background: none; cursor: pointer;
                           border-radius: 12px; padding: 3px 10px; font-size: 12px;
                           color: var(--secondary-text-color); }
        .models { display: flex; flex-wrap: wrap; gap: 6px; }
        .chip { padding: 6px 14px; border-radius: 16px; cursor: pointer;
                border: 1px solid var(--divider-color); font-size: 13px; }
        .chip.sel { background: var(--primary-color); color: var(--text-primary-color, #fff);
                    border-color: var(--primary-color); }
        .swatches { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 6px; }
        .sw { width: 64px; cursor: pointer; text-align: center; }
        .sw img { width: 64px; height: 40px; object-fit: cover; border-radius: 6px;
                  border: 2px solid transparent; display: block; background: #f3f3f3; }
        .sw.sel img { border-color: var(--primary-color); }
        .sw .nm { font-size: 10px; color: var(--secondary-text-color);
                  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      </style>
      <div id="form"></div>
      <div class="grp">颜色</div>
      <div class="colorrow"><span>背景颜色</span>
        <input type="color" id="bgc" value="${hexBg}"><button id="bgc_clr">恢复默认</button></div>
      <div class="colorrow"><span>底栏颜色</span>
        <input type="color" id="barc" value="${hexBar}"><button id="barc_clr">恢复默认</button></div>
      <div class="grp">车型</div>
      <div class="models">
        ${Object.entries(manifest)
          .map(
            ([slug, m]) =>
              `<div class="chip ${slug === model ? "sel" : ""}" data-model="${slug}">${m.name}</div>`
          )
          .join("")}
      </div>
      <div class="grp">车身颜色</div>
      <div class="swatches">
        ${colors
          .map((c) => {
            const img = (c.thumb ? `${STATIC_BASE}/cars/${c.thumb}` : `${STATIC_BASE}/cars/${c.file}`) + `?a=${ASSET_VER}`;
            const sel = c.slug === (this._config.color || "");
            return `<div class="sw ${sel ? "sel" : ""}" data-color="${c.slug}" title="${c.zh || c.slug}">
                      <img src="${img}" loading="lazy"><div class="nm">${c.zh || c.slug}</div>
                    </div>`;
          })
          .join("")}
      </div>
    `;

    const form = document.createElement("ha-form");
    form.hass = this._hass;
    form.data = { bar_opacity: 40, show_labels: true, bg_gradient: true, ...this._config };
    form.schema = this._schema();
    form.computeLabel = (s) =>
      ({
        device_id: "车辆（NIO 设备）",
        name: "显示名称（可选）",
        bg_color: "背景颜色",
        bar_color: "底栏颜色",
        bar_opacity: "底栏不透明度",
        show_labels: "图标下方显示状态文字",
        bg_gradient: "背景渐变质感（左上亮 → 右下暗）",
        bg_image: "背景图片 URL（可选，盖过背景颜色）",
      }[s.name] || s.name);
    form.addEventListener("value-changed", (ev) => {
      this._config = { ...this._config, ...ev.detail.value };
      this._emit();
    });
    this.shadowRoot.getElementById("form").appendChild(form);
    this._form = form;

    const hexToRgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
    const wireColor = (inputId, clearId, key) => {
      this.shadowRoot.getElementById(inputId).addEventListener("change", (ev) => {
        this._config = { ...this._config, [key]: hexToRgb(ev.target.value) };
        this._emit();
      });
      this.shadowRoot.getElementById(clearId).addEventListener("click", () => {
        const next = { ...this._config };
        delete next[key];
        this._config = next;
        this._emit();
        this._render();
      });
    };
    wireColor("bgc", "bgc_clr", "bg_color");
    wireColor("barc", "barc_clr", "bar_color");

    this.shadowRoot.querySelectorAll(".chip").forEach((el) =>
      el.addEventListener("click", () => {
        const m = el.dataset.model;
        const first = this._manifest[m]?.colors?.[0]?.slug || "cloud_white";
        this._config = { ...this._config, model: m, color: first };
        this._emit();
        this._render();
      })
    );
    this.shadowRoot.querySelectorAll(".sw").forEach((el) =>
      el.addEventListener("click", () => {
        this._config = { ...this._config, color: el.dataset.color };
        this._emit();
        this._render();
      })
    );
  }

  _emit() {
    const config = { type: "custom:nio-car-card", ...this._config };
    fireEvent(this, "config-changed", { config });
  }
}

// double-load safe: a second import (e.g. cache-buster URL change) must not
// throw "name already registered" — that rejection wedges HA's card picker
if (!customElements.get("nio-car-card")) {
  customElements.define("nio-car-card", NioCarCard);
}
if (!customElements.get("nio-car-card-editor")) {
  customElements.define("nio-car-card-editor", NioCarCardEditor);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "nio-car-card")) {
  window.customCards.push({
    type: "nio-car-card",
    name: "NIO Car Card",
    description: "蔚来车辆状态卡：官方渲染图 + 状态图标 + 详情弹窗（ha-nio 集成自带）",
    preview: true,
  });
}
