/**
 * Lovelace-Karte für die Integration "Lokale Wetterprognose".
 *
 * Version 0.4.3 - vollständige Neufassung nach dem offiziell dokumentierten
 * Kartenmuster von Home Assistant, um die Ursache des Ladekreises strukturell
 * auszuschließen:
 *
 *  - customElements.define läuft ALS ERSTES und ist gegen Doppelregistrierung
 *    geschützt. Wird die Datei doppelt geladen (Ressource + Cache), warf der
 *    zweite define-Aufruf früher einen Fehler, der die Registrierung des
 *    ganzen Moduls abbrach - der Browser wartete dann ewig auf ein Element,
 *    das nie fertig definiert wurde. Genau das erzeugt den drehenden Kreis.
 *  - Light DOM statt Shadow DOM. Die HA-Elemente ha-card und ha-icon erben so
 *    Stile und Ladeverhalten der Umgebung; im Shadow DOM war ha-icon zeitweise
 *    undefiniert.
 *  - Gerendert wird über ein einmal erzeugtes Grundgerüst, dessen Inhalt bei
 *    Aktualisierung ersetzt wird - nicht durch komplettes Neuschreiben bei
 *    jeder Zustandsänderung.
 *
 * Gestaltungsgedanke unverändert: das Zambretti-Verfahren stammt vom
 * Barografen von Negretti & Zambra. Herzstück ist der Druckverlauf, aus dem
 * die Prognose entsteht - die durchgezogene Kurve der echte Verlauf, die
 * gestrichelte Gerade die Tendenz, mit der gerechnet wird. Farben durchgängig
 * aus den CSS-Variablen von Home Assistant.
 */

const CARD_VERSION = "0.4.3";

// Doppelregistrierung abfangen, BEVOR irgendetwas anderes passiert. Das ist
// der wichtigste Unterschied zu den Vorversionen.
if (!customElements.get("local-forecast-card")) {

const STRINGS = {
  noEntity:
    "Keine Entität angegeben. Bitte in der Kartenkonfiguration eine Entität der Domäne weather auswählen.",
  notFound: (id) => `Entität ${id} existiert nicht.`,
  wrongDomain: "Diese Karte erwartet eine Entität aus der Domäne weather.",
  warmup:
    "Noch keine Prognose. Die Druckhistorie ist zu kurz - das legt sich nach wenigen Messungen.",
  noHistory:
    "Kein Druckverlauf verfügbar. Der Recorder zeichnet diesen Sensor nicht auf, oder es liegen noch keine Daten vor.",
  chartLabel: "Barograf",
  loading: "wird geladen …",
  now: "jetzt",
  covered: (p) => `${p} % bedeckt`,
  outlook: "Ausblick",
  until: (time) => `bis ${time} Uhr`,
  unchanged: "durchgehend gleiche Erwartung",
  noForecast: "Noch keine Prognose abrufbar.",
  rising: "steigend",
  falling: "fallend",
  steady: "gleichbleibend",
};

const TREND_THRESHOLD = 0.1;
const SMOOTHING_WINDOW = 6;
const POURING_ICON = "mdi:weather-pouring";

const CONDITION_ICONS = {
  "clear-night": "mdi:weather-night",
  cloudy: "mdi:weather-cloudy",
  exceptional: "mdi:alert-circle-outline",
  fog: "mdi:weather-fog",
  hail: "mdi:weather-hail",
  lightning: "mdi:weather-lightning",
  "lightning-rainy": "mdi:weather-lightning-rainy",
  partlycloudy: "mdi:weather-partly-cloudy",
  pouring: POURING_ICON,
  rainy: "mdi:weather-rainy",
  snowy: "mdi:weather-snowy",
  "snowy-rainy": "mdi:weather-snowy-rainy",
  sunny: "mdi:weather-sunny",
  windy: "mdi:weather-windy",
  "windy-variant": "mdi:weather-windy-variant",
};

const MINUS_SIGN = "\u2212";

const numberFormat = (value, digits) =>
  new Intl.NumberFormat("de-DE", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
    .format(value)
    .replace(/^-/, MINUS_SIGN);

const timeFormat = (date) =>
  new Intl.DateTimeFormat("de-DE", { hour: "2-digit", minute: "2-digit" }).format(
    date
  );

const escapeHtml = (value) =>
  String(value).replace(
    /[&<>"']/g,
    (ch) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch])
  );

/**
 * Gleitender Median über die Druckwerte - nur für die Darstellung. Der Sensor
 * löst feiner auf, als das Wetter sich ändert; der Median entfernt das Zappeln,
 * ohne echte Sprünge abzurunden. Fensterbreite bewusst gerade (siehe README).
 */
const smoothed = (points, window) => {
  if (points.length < window || window < 3) return points;
  const half = Math.floor(window / 2);
  return points.map((point, i) => {
    const from = Math.min(Math.max(0, i - half), points.length - window);
    const slice = points.slice(from, from + window);
    const values = slice.map((p) => p[1]).sort((a, b) => a - b);
    const middle = Math.floor(values.length / 2);
    const median =
      values.length % 2
        ? values[middle]
        : (values[middle - 1] + values[middle]) / 2;
    return [point[0], median];
  });
};

class LocalForecastCard extends HTMLElement {
  constructor() {
    super();
    this._history = null;
    this._historyFetchedAt = 0;
    this._historyPending = false;
    this._forecast = null;
    this._configError = null;
    this._rootBuilt = false;
  }

  // --- Konfiguration ----------------------------------------------------

  setConfig(config) {
    if (!config) {
      throw new Error(STRINGS.noEntity);
    }
    // Bewusst KEINE Ausnahme bei fehlender/falscher Entität: die Kartenauswahl
    // ruft setConfig mit einem leeren Stub auf. Eine Ausnahme hier ließe die
    // Vorschau im Ladekreis hängen. Der Mangel wird vermerkt und angezeigt.
    this._configError = null;
    if (!config.entity) {
      this._configError = STRINGS.noEntity;
    } else if (!config.entity.startsWith("weather.")) {
      this._configError = STRINGS.wrongDomain;
    }
    this._config = {
      show_chart: true,
      smooth: true,
      show_forecast: true,
      forecast_style: "band",
      hours: null,
      ...config,
    };
    this._history = null;
    this._historyFetchedAt = 0;
    this._forecast = null;
    if (this._rootBuilt) this._update();
  }

  getCardSize() {
    let size = 2;
    if (this._config && this._config.show_chart) size += 2;
    if (this._config && this._config.show_forecast) size += 1;
    return size;
  }

  static getStubConfig(hass) {
    let entity = "";
    if (hass && hass.states) {
      entity = Object.keys(hass.states).find((id) => id.startsWith("weather.")) || "";
    }
    return { type: "custom:local-forecast-card", entity };
  }

  // --- Lebenszyklus -----------------------------------------------------

  set hass(hass) {
    this._hass = hass;
    this._maybeFetchHistory();
    this._maybeSubscribeForecast();
    if (this._config && this._config.show_forecast) this._ensureIconElement();
    this._update();
  }

  connectedCallback() {
    this._update();
  }

  disconnectedCallback() {
    if (this._unsubForecast) {
      this._unsubForecast();
      this._unsubForecast = null;
    }
  }

  // --- Grundgerüst ------------------------------------------------------

  _buildRoot() {
    if (this._rootBuilt) return;
    const style = document.createElement("style");
    style.textContent = CARD_STYLE;
    this._card = document.createElement("ha-card");
    this._body = document.createElement("div");
    this._body.className = "lf-body";
    this._card.appendChild(this._body);
    this.appendChild(style);
    this.appendChild(this._card);
    this._rootBuilt = true;
  }

  _setBody(html) {
    this._buildRoot();
    if (this._lastHtml === html) return;
    this._lastHtml = html;
    this._body.innerHTML = html;
  }

  // --- Prognose ---------------------------------------------------------

  async _ensureIconElement() {
    if (this._iconReady || typeof customElements === "undefined") return;
    if (customElements.get("ha-icon")) {
      this._iconReady = true;
      return;
    }
    try {
      const helpers = window.loadCardHelpers
        ? await window.loadCardHelpers()
        : null;
      if (helpers && this._config) {
        const card = await helpers.createCardElement({
          type: "weather-forecast",
          entity: this._config.entity,
        });
        if (card && card.constructor && card.constructor.getConfigElement) {
          card.constructor.getConfigElement();
        }
      }
      await customElements.whenDefined("ha-icon");
    } catch (err) {
      // Zur Not ohne vorgeladenes Icon weiter.
    }
    this._iconReady = true;
    this._lastHtml = null;
    this._update();
  }

  async _maybeSubscribeForecast() {
    if (!this._config || !this._config.show_forecast) return;
    if (this._unsubForecast || this._subscribing) return;
    if (!this._hass || !this._hass.connection) return;
    if (this._configError) return;
    if (!this._hass.states[this._config.entity]) return;

    this._subscribing = true;
    try {
      this._unsubForecast = await this._hass.connection.subscribeMessage(
        (event) => {
          this._forecast = (event && event.forecast) || [];
          this._lastHtml = null;
          this._update();
        },
        {
          type: "weather/subscribe_forecast",
          entity_id: this._config.entity,
          forecast_type: "hourly",
        }
      );
    } catch (err) {
      this._forecast = [];
    } finally {
      this._subscribing = false;
    }
  }

  _forecastSection() {
    if (!this._config.show_forecast || !this._forecast) return "";
    if (!this._forecast.length) {
      return `<div class="lf-section"><div class="lf-hint">${STRINGS.noForecast}</div></div>`;
    }
    const entries = this._forecast
      .map((item) => ({
        when: new Date(item.datetime),
        icon: CONDITION_ICONS[item.condition] || "mdi:help-circle-outline",
        condition: item.condition,
      }))
      .filter((item) => !isNaN(item.when.getTime()));
    if (!entries.length) return "";

    if (this._config.forecast_style === "hourly") {
      const columns = entries
        .map(
          (item) => `
            <div class="lf-hour">
              <div class="lf-hour-time">${timeFormat(item.when)}</div>
              <ha-icon icon="${item.icon}"></ha-icon>
            </div>`
        )
        .join("");
      return `<div class="lf-section"><div class="lf-label">${STRINGS.outlook}</div><div class="lf-hours">${columns}</div></div>`;
    }

    const last = entries[entries.length - 1];
    const uniform = entries.every((item) => item.condition === entries[0].condition);
    return `
      <div class="lf-section">
        <div class="lf-label">${STRINGS.outlook}</div>
        <div class="lf-band">
          <ha-icon class="lf-band-icon" icon="${entries[0].icon}"></ha-icon>
          <div>
            <div class="lf-band-main">${STRINGS.until(timeFormat(last.when))}</div>
            ${uniform ? `<div class="lf-band-sub">${STRINGS.unchanged}</div>` : ""}
          </div>
        </div>
      </div>`;
  }

  // --- Druckverlauf -----------------------------------------------------

  _trendHours(stateObj) {
    if (this._config.hours) return Number(this._config.hours);
    const hours = stateObj.attributes.trend_hours;
    return hours ? Number(hours) : 3;
  }

  async _maybeFetchHistory() {
    if (!this._config || !this._config.show_chart || this._historyPending) return;
    if (this._configError || !this._hass) return;
    const stateObj = this._hass.states[this._config.entity];
    if (!stateObj) return;
    const pressureEntity = stateObj.attributes.pressure_entity_id;
    if (!pressureEntity) return;
    if (Date.now() - this._historyFetchedAt < 120000) return;

    this._historyPending = true;
    try {
      const end = new Date();
      const start = new Date(end.getTime() - this._trendHours(stateObj) * 3600 * 1000);
      const result = await this._hass.callWS({
        type: "history/history_during_period",
        start_time: start.toISOString(),
        end_time: end.toISOString(),
        entity_ids: [pressureEntity],
        minimal_response: true,
        no_attributes: true,
        significant_changes_only: false,
      });
      const raw = (result && result[pressureEntity]) || [];
      const points = [];
      for (const item of raw) {
        const value = parseFloat(item.s !== undefined ? item.s : item.state);
        const stamp = item.lu !== undefined ? item.lu : item.lc;
        const time =
          stamp !== undefined ? stamp * 1000 : new Date(item.last_updated).getTime();
        if (!isNaN(value) && !isNaN(time)) points.push([time, value]);
      }
      points.sort((a, b) => a[0] - b[0]);
      this._history = points;
      this._historyFetchedAt = Date.now();
      this._lastHtml = null;
      this._update();
    } catch (err) {
      this._history = [];
      this._historyFetchedAt = Date.now();
    } finally {
      this._historyPending = false;
    }
  }

  _chartSection(stateObj) {
    const raw = this._history;
    if (!raw)
      return `<div class="lf-hint">${STRINGS.chartLabel} ${STRINGS.loading}</div>`;
    if (raw.length < 2) return `<div class="lf-hint">${STRINGS.noHistory}</div>`;

    const points = this._config.smooth ? smoothed(raw, SMOOTHING_WINDOW) : raw;
    const W = 320,
      H = 88,
      padLeft = 4,
      padRight = 40,
      padTop = 10,
      padBottom = 16;

    const times = points.map((p) => p[0]);
    const values = points.map((p) => p[1]);
    const tMin = Math.min(...times),
      tMax = Math.max(...times);
    let vMin = Math.min(...values),
      vMax = Math.max(...values);
    const span = Math.max(vMax - vMin, 2);
    const mid = (vMax + vMin) / 2;
    vMin = mid - span / 2 - 0.2;
    vMax = mid + span / 2 + 0.2;

    const x = (t) =>
      padLeft + ((t - tMin) / Math.max(tMax - tMin, 1)) * (W - padLeft - padRight);
    const y = (v) => padTop + ((vMax - v) / (vMax - vMin)) * (H - padTop - padBottom);

    const step = vMax - vMin > 8 ? 2 : 1;
    const rules = [];
    for (let v = Math.ceil(vMin / step) * step; v <= vMax; v += step) {
      rules.push(
        `<line class="lf-rule" x1="${padLeft}" y1="${y(v).toFixed(1)}" x2="${(
          W - padRight
        ).toFixed(1)}" y2="${y(v).toFixed(1)}"/>` +
          `<text class="lf-rule-label" x="${(W - padRight + 5).toFixed(1)}" y="${(
            y(v) + 3
          ).toFixed(1)}">${numberFormat(v, 0)}</text>`
      );
    }

    const trace = points
      .map(
        (p, i) => `${i === 0 ? "M" : "L"}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`
      )
      .join(" ");

    const trend = Number(stateObj.attributes.pressure_trend);
    let trendLine = "";
    if (!isNaN(trend)) {
      const hoursSpan = (tMax - tMin) / 3600000;
      const vEnd = points[points.length - 1][1];
      const vStart = vEnd - trend * hoursSpan;
      trendLine = `<line class="lf-trend" x1="${x(tMin).toFixed(1)}" y1="${y(
        vStart
      ).toFixed(1)}" x2="${x(tMax).toFixed(1)}" y2="${y(vEnd).toFixed(1)}"/>`;
    }

    const hours = this._trendHours(stateObj);
    return `
      <svg viewBox="0 0 ${W} ${H}" role="img"
           aria-label="${STRINGS.chartLabel}: Luftdruckverlauf der letzten ${hours} Stunden">
        ${rules.join("")}
        ${trendLine}
        <path class="lf-trace" d="${trace}"/>
        <circle class="lf-pen" cx="${x(tMax).toFixed(1)}" cy="${y(
      points[points.length - 1][1]
    ).toFixed(1)}" r="2.6"/>
      </svg>
      <div class="lf-axis"><span>${MINUS_SIGN}${hours} h</span><span>${STRINGS.now}</span></div>`;
  }

  // --- Zusammensetzen ---------------------------------------------------

  _update() {
    if (!this._config) return;
    this._buildRoot();

    if (this._configError) {
      this._setBody(`<div class="lf-hint">${escapeHtml(this._configError)}</div>`);
      return;
    }
    if (!this._hass) {
      this._setBody(`<div class="lf-hint">${STRINGS.chartLabel} ${STRINGS.loading}</div>`);
      return;
    }

    const stateObj = this._hass.states[this._config.entity];
    if (!stateObj) {
      this._setBody(
        `<div class="lf-hint">${escapeHtml(STRINGS.notFound(this._config.entity))}</div>`
      );
      return;
    }

    const attrs = stateObj.attributes;
    const code = attrs.zambretti_code;
    const text = attrs.zambretti_text;
    const trend = Number(attrs.pressure_trend);
    const pressure = Number(attrs.sea_level_pressure);

    if (!code) {
      this._setBody(`<div class="lf-hint">${STRINGS.warmup}</div>`);
      return;
    }

    let arrow = "\u2192",
      trendWord = STRINGS.steady;
    if (trend >= TREND_THRESHOLD) {
      arrow = "\u2197";
      trendWord = STRINGS.rising;
    } else if (trend <= -TREND_THRESHOLD) {
      arrow = "\u2198";
      trendWord = STRINGS.falling;
    }

    const coverage =
      attrs.cloud_coverage !== undefined && attrs.cloud_coverage !== null
        ? " · " + STRINGS.covered(Math.round(Number(attrs.cloud_coverage)))
        : "";
    const temperature =
      attrs.temperature !== undefined && attrs.temperature !== null
        ? `${numberFormat(Number(attrs.temperature), 1)} ${attrs.temperature_unit || "°C"}`
        : "";
    const stateLabel = this._hass.formatEntityState
      ? this._hass.formatEntityState(stateObj)
      : stateObj.state;

    const chart = this._config.show_chart ? this._chartSection(stateObj) : "";

    this._setBody(`
      <div class="lf-head">
        <div class="lf-plate" title="Zambretti-Code ${escapeHtml(code)}">${escapeHtml(
      code
    )}</div>
        <div class="lf-headline">
          <div class="lf-text">${escapeHtml(text)}</div>
          <div class="lf-sub">${escapeHtml(stateLabel)}${
      temperature ? " · " + escapeHtml(temperature) : ""
    }${escapeHtml(coverage)}</div>
        </div>
      </div>
      ${chart}
      ${this._forecastSection()}
      <div class="lf-foot">
        <span class="lf-value">${numberFormat(pressure, 1)} hPa</span>
        <span>${arrow} ${trendWord}, ${numberFormat(trend, 2)} hPa/h</span>
      </div>
    `);
  }
}

const CARD_STYLE = `
  ha-card { padding: 16px; }
  .lf-head { display: flex; align-items: center; gap: 14px; }
  .lf-plate {
    flex: 0 0 auto; width: 46px; height: 46px;
    display: flex; align-items: center; justify-content: center;
    border: 1px solid var(--divider-color, #e0e0e0); border-radius: 4px;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 26px; font-weight: 500; color: var(--primary-text-color);
  }
  .lf-headline { min-width: 0; }
  .lf-text { font-size: 20px; line-height: 1.25; color: var(--primary-text-color); }
  .lf-sub { margin-top: 2px; font-size: 13px; color: var(--secondary-text-color); }
  .lf-body svg { display: block; width: 100%; height: auto; margin-top: 16px; overflow: visible; }
  .lf-rule { stroke: var(--divider-color, #e0e0e0); stroke-width: 1; }
  .lf-rule-label { fill: var(--secondary-text-color); font-size: 9px;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
  .lf-trace { fill: none; stroke: var(--primary-text-color); stroke-width: 1.8;
    stroke-linejoin: round; stroke-linecap: round; }
  .lf-trend { stroke: var(--primary-color, #03a9f4); stroke-width: 1.4; stroke-dasharray: 4 3; }
  .lf-pen { fill: var(--primary-color, #03a9f4); }
  .lf-axis { display: flex; justify-content: space-between; margin-top: 2px;
    font-size: 11px; color: var(--secondary-text-color); }
  .lf-section { margin-top: 14px; padding-top: 12px;
    border-top: 1px solid var(--divider-color, #e0e0e0); }
  .lf-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em;
    color: var(--secondary-text-color); margin-bottom: 8px; }
  .lf-band { display: flex; align-items: center; gap: 12px; }
  .lf-band-icon { --mdc-icon-size: 32px; color: var(--state-icon-color, var(--primary-text-color)); }
  .lf-band-main { font-size: 15px; color: var(--primary-text-color); }
  .lf-band-sub { font-size: 12px; color: var(--secondary-text-color); }
  .lf-hours { display: flex; justify-content: space-between; gap: 4px; }
  .lf-hour { display: flex; flex-direction: column; align-items: center; gap: 4px;
    flex: 1 1 0; min-width: 0; }
  .lf-hour-time { font-size: 11px; color: var(--secondary-text-color);
    font-variant-numeric: tabular-nums; }
  .lf-hour ha-icon { --mdc-icon-size: 24px; color: var(--state-icon-color, var(--primary-text-color)); }
  .lf-foot { display: flex; justify-content: space-between; align-items: baseline;
    gap: 8px; margin-top: 14px; padding-top: 12px;
    border-top: 1px solid var(--divider-color, #e0e0e0);
    font-size: 13px; color: var(--secondary-text-color); }
  .lf-value { font-variant-numeric: tabular-nums; font-size: 15px; color: var(--primary-text-color); }
  .lf-hint { font-size: 14px; line-height: 1.4; color: var(--secondary-text-color); margin-top: 12px; }
  @media (max-width: 380px) {
    .lf-text { font-size: 17px; }
    .lf-plate { width: 40px; height: 40px; font-size: 22px; }
  }
`;

customElements.define("local-forecast-card", LocalForecastCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "local-forecast-card",
  name: "Lokale Wetterprognose",
  description:
    "Zeigt die Zambretti-Prognose mit dem Druckverlauf, aus dem sie berechnet wurde.",
  preview: true,
  documentationURL: "https://github.com/Meine-smarte-Welt/local_forecast",
});

console.info(
  `%c LOCAL-FORECAST-CARD %c ${CARD_VERSION} `,
  "color:white;background:#03a9f4;font-weight:700",
  "color:#03a9f4;background:white;font-weight:700"
);

} // Ende Doppelregistrierungs-Schutz
