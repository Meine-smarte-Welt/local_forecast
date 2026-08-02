/**
 * Lovelace-Karte für die Integration "Lokale Wetterprognose".
 *
 * Gestaltungsgedanke: das Zambretti-Verfahren stammt von einem Instrument -
 * dem Barografen von Negretti & Zambra, der mit einer Tintenfeder eine Kurve
 * auf liniertes Papier zeichnete. Genau das ist das Herzstück dieser Karte:
 * der echte Druckverlauf über das Trendfenster, darüber gestrichelt die
 * Gerade, mit der das Verfahren tatsächlich rechnet. Damit sieht man nicht nur
 * das Ergebnis, sondern seine Eingabe - das kann keine mitgelieferte Karte.
 *
 * Farben kommen bewusst durchgängig aus den CSS-Variablen von Home Assistant.
 * Eine eigene Palette würde in einem dunklen Motiv oder einem eigenen Theme
 * sofort falsch aussehen; eine Karte hat sich in ihre Umgebung einzufügen.
 */

const CARD_VERSION = "0.4.0";

const STRINGS = {
  noEntity: "Keine Entität angegeben. Bitte in der Kartenkonfiguration eine Entität der Domäne weather auswählen.",
  notFound: (id) => `Entität ${id} existiert nicht.`,
  wrongDomain: "Diese Karte erwartet eine Entität aus der Domäne weather.",
  warmup: "Noch keine Prognose. Die Druckhistorie ist zu kurz - das legt sich nach wenigen Messungen.",
  noHistory: "Kein Druckverlauf verfügbar. Der Recorder zeichnet diesen Sensor nicht auf, oder es liegen noch keine Daten vor.",
  chartLabel: "Barograf",
  now: "jetzt",
  samples: (n) => `${n} Messwerte`,
  covered: (p) => `${p} % bedeckt`,
  outlook: "Ausblick",
  until: (time) => `bis ${time} Uhr`,
  unchanged: "durchgehend gleiche Erwartung",
  noForecast: "Noch keine Prognose abrufbar.",
  rising: "steigend",
  falling: "fallend",
  steady: "gleichbleibend",
};

/** Ab dieser Tendenz gilt der Druck als steigend bzw. fallend (wie im Backend). */
const TREND_THRESHOLD = 0.1;

/**
 * Fensterbreite des gleitenden Medians. Bewusst GERADE.
 *
 * Bei ungerader Breite wählt der Median schlicht den Mehrheitswert - ein
 * gleichmäßiges Hin-und-Her zwischen zwei Werten, genau das typische
 * Sensorzappeln, wandert dann unverändert mit. Bei gerader Breite wird
 * zwischen den beiden mittleren Werten gemittelt, und das Zappeln
 * verschwindet. Ein Testfall in tests/test_card.js hält das fest.
 */
const SMOOTHING_WINDOW = 6;

/** Zustand -> Symbol. Dieselben Symbole, die Home Assistant selbst verwendet. */
const CONDITION_ICONS = {
  "clear-night": "mdi:weather-night",
  cloudy: "mdi:weather-cloudy",
  exceptional: "mdi:alert-circle-outline",
  fog: "mdi:weather-fog",
  hail: "mdi:weather-hail",
  lightning: "mdi:weather-lightning",
  "lightning-rainy": "mdi:weather-lightning-rainy",
  partlycloudy: "mdi:weather-partly-cloudy",
  pouring: "mdi:weather-pouring",
  rainy: "mdi:weather-rainy",
  snowy: "mdi:weather-snowy",
  "snowy-rainy": "mdi:weather-snowy-rainy",
  sunny: "mdi:weather-sunny",
  windy: "mdi:weather-windy",
  "windy-variant": "mdi:weather-windy-variant",
};

const timeFormat = (date) =>
  new Intl.DateTimeFormat("de-DE", { hour: "2-digit", minute: "2-digit" }).format(
    date
  );

// Intl liefert einen Bindestrich; die Zeitachse verwendet ein echtes
// Minuszeichen. Beides nebeneinander sieht nach Versehen aus.
const MINUS_SIGN = "\u2212";

const numberFormat = (value, digits) =>
  new Intl.NumberFormat("de-DE", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
    .format(value)
    .replace(/^-/, MINUS_SIGN);

/**
 * Gleitender Median über die Druckwerte - nur für die DARSTELLUNG.
 *
 * Der Sensor löst feiner auf, als das Wetter sich ändert: über drei Stunden
 * schwankt der Messwert um wenige Hundertstel hPa hin und her, was die Kurve
 * zu einem Seismogramm macht, obwohl sich meteorologisch nichts tut. Der
 * Median entfernt genau dieses Zappeln, ohne echte Sprünge abzurunden - anders
 * als ein Mittelwert, der einen echten Drucksturz verschleifen würde.
 *
 * Die BERECHNUNG der Prognose läuft weiterhin auf den Rohdaten. Geglättet wird
 * ausschließlich das Bild.
 */
const smoothed = (points, window) => {
  if (points.length < window || window < 3) return points;
  const half = Math.floor(window / 2);
  return points.map((point, i) => {
    // An den Rändern wird das Fenster verschoben statt beschnitten. Sonst
    // enthielte es dort weniger - und womöglich ungerade viele - Werte, und
    // genau am Anfang und Ende der Kurve bliebe das Zappeln stehen.
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
    this.attachShadow({ mode: "open" });
    this._history = null;
    this._historyPending = false;
    this._historyFetchedAt = 0;
    this._lastRenderKey = null;
  }

  setConfig(config) {
    if (!config || !config.entity) {
      throw new Error(STRINGS.noEntity);
    }
    if (!config.entity.startsWith("weather.")) {
      throw new Error(STRINGS.wrongDomain);
    }
    this._config = {
      show_chart: true,
      smooth: true,
      show_forecast: true,
      // "band"   - eine Aussage mit ihrem Gültigkeitszeitraum (Vorgabe)
      // "hourly" - eine Spalte je Stunde, wie in der mitgelieferten Karte
      forecast_style: "band",
      hours: null, // null = Trendfenster der Integration übernehmen
      ...config,
    };
    this._history = null;
    this._historyFetchedAt = 0;
  }

  set hass(hass) {
    this._hass = hass;
    this._maybeFetchHistory();
    this._maybeSubscribeForecast();
    this._render();
  }

  disconnectedCallback() {
    if (this._unsubForecast) {
      this._unsubForecast();
      this._unsubForecast = null;
    }
  }

  getCardSize() {
    let size = 2;
    if (this._config && this._config.show_chart) size += 2;
    if (this._config && this._config.show_forecast) size += 1;
    return size;
  }

  static getStubConfig(hass) {
    const entity = Object.keys(hass.states).find((id) =>
      id.startsWith("weather.")
    );
    return { type: "custom:local-forecast-card", entity: entity || "" };
  }

  // ----------------------------------------------------------------------
  // Prognose
  // ----------------------------------------------------------------------

  async _maybeSubscribeForecast() {
    if (!this._config.show_forecast || this._unsubForecast || this._subscribing) {
      return;
    }
    if (!this._hass || !this._hass.connection) return;
    if (!this._hass.states[this._config.entity]) return;

    this._subscribing = true;
    try {
      // Die Prognose steht bewusst NICHT in den Attributen der Entität -
      // Home Assistant liefert sie über ein Abo aus. Genau das wird hier
      // genutzt, statt sie aus dem Zambretti-Text nachzubauen: so zeigt die
      // Karte exakt das, was auch die mitgelieferte Wetterkarte bekäme,
      // inklusive der stündlichen Tag/Nacht-Korrektur aus dem Backend.
      this._unsubForecast = await this._hass.connection.subscribeMessage(
        (event) => {
          this._forecast = (event && event.forecast) || [];
          this._lastRenderKey = null;
          this._render();
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

  _renderForecast() {
    if (!this._config.show_forecast) return "";
    if (!this._forecast) return "";
    if (!this._forecast.length) {
      return `<div class="section"><div class="hint">${STRINGS.noForecast}</div></div>`;
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
            <div class="hour">
              <div class="hour-time">${timeFormat(item.when)}</div>
              <ha-icon icon="${item.icon}"></ha-icon>
            </div>`
        )
        .join("");
      return `<div class="section"><div class="label">${STRINGS.outlook}</div><div class="hours">${columns}</div></div>`;
    }

    // Vorgabe: EINE Aussage mit ihrem Gültigkeitszeitraum. Das Verfahren
    // liefert nicht sechs Stundenwerte, sondern einen Ausblick - sechs
    // gleiche Symbole nebeneinander würden eine Auflösung vortäuschen,
    // die es nicht gibt.
    const last = entries[entries.length - 1];
    const uniform = entries.every((item) => item.condition === entries[0].condition);
    return `
      <div class="section">
        <div class="label">${STRINGS.outlook}</div>
        <div class="band">
          <ha-icon class="band-icon" icon="${entries[0].icon}"></ha-icon>
          <div class="band-text">
            <div class="band-main">${STRINGS.until(timeFormat(last.when))}</div>
            ${uniform ? `<div class="band-sub">${STRINGS.unchanged}</div>` : ""}
          </div>
        </div>
      </div>`;
  }

  // ----------------------------------------------------------------------
  // Druckverlauf
  // ----------------------------------------------------------------------

  _trendHours(stateObj) {
    if (this._config.hours) return Number(this._config.hours);
    const hours = stateObj.attributes.trend_hours;
    return hours ? Number(hours) : 3;
  }

  async _maybeFetchHistory() {
    if (!this._config || !this._config.show_chart || this._historyPending) return;

    const stateObj = this._hass.states[this._config.entity];
    if (!stateObj) return;

    const pressureEntity = stateObj.attributes.pressure_entity_id;
    if (!pressureEntity) return;

    // Der Verlauf ändert sich langsam; häufiger als alle zwei Minuten nachzuladen
    // erzeugt nur Last auf der Datenbank.
    if (Date.now() - this._historyFetchedAt < 120000) return;

    this._historyPending = true;
    try {
      const end = new Date();
      const start = new Date(
        end.getTime() - this._trendHours(stateObj) * 3600 * 1000
      );
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
        // Home Assistant liefert Verlaufsdaten in Kurzform: s = Zustand,
        // lu = last_updated, lc = last_changed. Der erste Eintrag kann noch
        // die ausgeschriebenen Feldnamen tragen.
        const value = parseFloat(item.s !== undefined ? item.s : item.state);
        const stamp = item.lu !== undefined ? item.lu : item.lc;
        const time =
          stamp !== undefined
            ? stamp * 1000
            : new Date(item.last_updated).getTime();
        if (!isNaN(value) && !isNaN(time)) {
          points.push([time, value]);
        }
      }
      points.sort((a, b) => a[0] - b[0]);
      this._history = points;
      this._historyFetchedAt = Date.now();
      this._lastRenderKey = null;
      this._render();
    } catch (err) {
      this._history = [];
      this._historyFetchedAt = Date.now();
    } finally {
      this._historyPending = false;
    }
  }

  // ----------------------------------------------------------------------
  // Barograf
  // ----------------------------------------------------------------------

  _renderChart(stateObj) {
    const raw = this._history;
    if (!raw) return `<div class="hint">${STRINGS.chartLabel} wird geladen …</div>`;
    if (raw.length < 2) return `<div class="hint">${STRINGS.noHistory}</div>`;

    const points = this._config.smooth ? smoothed(raw, SMOOTHING_WINDOW) : raw;

    const W = 320;
    const H = 88;
    const padLeft = 4;
    const padRight = 40;
    const padTop = 10;
    const padBottom = 16;

    const times = points.map((p) => p[0]);
    const values = points.map((p) => p[1]);
    const tMin = Math.min(...times);
    const tMax = Math.max(...times);
    let vMin = Math.min(...values);
    let vMax = Math.max(...values);

    // Mindestens 2 hPa Höhe, damit ein ruhiger Verlauf nicht als
    // dramatische Zickzacklinie erscheint. Ehrlichkeit vor Dramatik.
    const span = Math.max(vMax - vMin, 2);
    const mid = (vMax + vMin) / 2;
    vMin = mid - span / 2 - 0.2;
    vMax = mid + span / 2 + 0.2;

    const x = (t) =>
      padLeft + ((t - tMin) / Math.max(tMax - tMin, 1)) * (W - padLeft - padRight);
    const y = (v) =>
      padTop + ((vMax - v) / (vMax - vMin)) * (H - padTop - padBottom);

    // Linierung des Papiers: ganze hPa, solange das nicht zu dicht wird.
    const step = vMax - vMin > 8 ? 2 : 1;
    const rules = [];
    for (let v = Math.ceil(vMin / step) * step; v <= vMax; v += step) {
      rules.push(
        `<line class="rule" x1="${padLeft}" y1="${y(v).toFixed(1)}" x2="${(W - padRight).toFixed(1)}" y2="${y(v).toFixed(1)}"/>` +
          `<text class="rule-label" x="${(W - padRight + 5).toFixed(1)}" y="${(y(v) + 3).toFixed(1)}">${numberFormat(v, 0)}</text>`
      );
    }

    const trace = points
      .map((p, i) => `${i === 0 ? "M" : "L"}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`)
      .join(" ");

    // Die gestrichelte Gerade ist genau die Tendenz, mit der das Verfahren
    // rechnet: verankert am letzten Messwert, Steigung aus dem Attribut.
    const trend = Number(stateObj.attributes.pressure_trend);
    let trendLine = "";
    if (!isNaN(trend)) {
      const hoursSpan = (tMax - tMin) / 3600000;
      const vEnd = points[points.length - 1][1];
      const vStart = vEnd - trend * hoursSpan;
      trendLine = `<line class="trend" x1="${x(tMin).toFixed(1)}" y1="${y(vStart).toFixed(1)}" x2="${x(tMax).toFixed(1)}" y2="${y(vEnd).toFixed(1)}"/>`;
    }

    const hours = this._trendHours(stateObj);

    return `
      <svg viewBox="0 0 ${W} ${H}" role="img"
           aria-label="${STRINGS.chartLabel}: Luftdruckverlauf der letzten ${hours} Stunden">
        ${rules.join("")}
        ${trendLine}
        <path class="trace" d="${trace}"/>
        <circle class="pen" cx="${x(tMax).toFixed(1)}" cy="${y(points[points.length - 1][1]).toFixed(1)}" r="2.6"/>
      </svg>
      <div class="axis">
        <span>−${hours} h</span>
        <span>${STRINGS.now}</span>
      </div>`;
  }

  // ----------------------------------------------------------------------
  // Darstellung
  // ----------------------------------------------------------------------

  _render() {
    if (!this._config || !this._hass) return;

    const stateObj = this._hass.states[this._config.entity];
    if (!stateObj) {
      this._paint(`<div class="error">${STRINGS.notFound(this._config.entity)}</div>`);
      return;
    }

    const attrs = stateObj.attributes;
    const code = attrs.zambretti_code;
    const text = attrs.zambretti_text;
    const trend = Number(attrs.pressure_trend);
    const pressure = Number(attrs.sea_level_pressure);

    if (!code) {
      this._paint(`<div class="hint">${STRINGS.warmup}</div>`);
      return;
    }

    let arrow = "→";
    let trendWord = STRINGS.steady;
    if (trend >= TREND_THRESHOLD) {
      arrow = "↗";
      trendWord = STRINGS.rising;
    } else if (trend <= -TREND_THRESHOLD) {
      arrow = "↘";
      trendWord = STRINGS.falling;
    }

    // Der Trübungsgrad steht nur da, wenn er auch gemessen wurde - nachts
    // fehlt er, und ein erfundener Wert wäre schlimmer als keiner.
    const coverage =
      attrs.cloud_coverage !== undefined && attrs.cloud_coverage !== null
        ? " · " + STRINGS.covered(Math.round(Number(attrs.cloud_coverage)))
        : "";

    const temperature =
      attrs.temperature !== undefined && attrs.temperature !== null
        ? `${numberFormat(Number(attrs.temperature), 1)} ${attrs.temperature_unit || "°C"}`
        : "";

    const chart = this._config.show_chart ? this._renderChart(stateObj) : "";

    this._paint(`
      <div class="head">
        <div class="plate" title="Zambretti-Code ${code}">${code}</div>
        <div class="headline">
          <div class="text">${text}</div>
          <div class="sub">${this._hass.formatEntityState(stateObj)}${temperature ? " · " + temperature : ""}${coverage}</div>
        </div>
      </div>
      ${chart}
      ${this._renderForecast()}
      <div class="foot">
        <span class="value">${numberFormat(pressure, 1)} hPa</span>
        <span class="trend-word">${arrow} ${trendWord}, ${numberFormat(trend, 2)} hPa/h</span>
      </div>
    `);
  }

  _paint(inner) {
    if (this._lastRenderKey === inner) return;
    this._lastRenderKey = inner;
    this.shadowRoot.innerHTML = `
      <style>
        ha-card {
          padding: 16px;
        }
        .head {
          display: flex;
          align-items: center;
          gap: 14px;
        }
        /* Der Buchstabe ist ein echter Code, kein Schmuck - deshalb die
           Anmutung eines eingeschlagenen Schilds am Instrument. Der einzige
           Ort, an dem diese Karte eine andere Schrift verwendet. */
        .plate {
          flex: 0 0 auto;
          width: 46px;
          height: 46px;
          display: flex;
          align-items: center;
          justify-content: center;
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 4px;
          font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
          font-size: 26px;
          font-weight: 500;
          letter-spacing: 0;
          color: var(--primary-text-color);
        }
        .headline {
          min-width: 0;
        }
        .text {
          font-size: 20px;
          line-height: 1.25;
          color: var(--primary-text-color);
        }
        .sub {
          margin-top: 2px;
          font-size: 13px;
          color: var(--secondary-text-color);
        }
        svg {
          display: block;
          width: 100%;
          height: auto;
          margin-top: 16px;
          overflow: visible;
        }
        .rule {
          stroke: var(--divider-color, #e0e0e0);
          stroke-width: 1;
        }
        .rule-label {
          fill: var(--secondary-text-color);
          font-size: 9px;
          font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        }
        .trace {
          fill: none;
          stroke: var(--primary-text-color);
          stroke-width: 1.8;
          stroke-linejoin: round;
          stroke-linecap: round;
        }
        .trend {
          stroke: var(--primary-color, #03a9f4);
          stroke-width: 1.4;
          stroke-dasharray: 4 3;
        }
        .pen {
          fill: var(--primary-color, #03a9f4);
        }
        .axis {
          display: flex;
          justify-content: space-between;
          margin-top: 2px;
          font-size: 11px;
          color: var(--secondary-text-color);
        }
        .section {
          margin-top: 14px;
          padding-top: 12px;
          border-top: 1px solid var(--divider-color, #e0e0e0);
        }
        .label {
          font-size: 11px;
          text-transform: uppercase;
          letter-spacing: 0.06em;
          color: var(--secondary-text-color);
          margin-bottom: 8px;
        }
        .band {
          display: flex;
          align-items: center;
          gap: 12px;
        }
        .band-icon {
          --mdc-icon-size: 32px;
          color: var(--state-icon-color, var(--primary-text-color));
        }
        .band-main {
          font-size: 15px;
          color: var(--primary-text-color);
        }
        .band-sub {
          font-size: 12px;
          color: var(--secondary-text-color);
        }
        .hours {
          display: flex;
          justify-content: space-between;
          gap: 4px;
        }
        .hour {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 4px;
          flex: 1 1 0;
          min-width: 0;
        }
        .hour-time {
          font-size: 11px;
          color: var(--secondary-text-color);
          font-variant-numeric: tabular-nums;
        }
        .hour ha-icon {
          --mdc-icon-size: 24px;
          color: var(--state-icon-color, var(--primary-text-color));
        }
        .foot {
          display: flex;
          justify-content: space-between;
          align-items: baseline;
          gap: 8px;
          margin-top: 14px;
          padding-top: 12px;
          border-top: 1px solid var(--divider-color, #e0e0e0);
          font-size: 13px;
          color: var(--secondary-text-color);
        }
        .value {
          /* Tabellenziffern statt voller Monospace: gleiche Ziffernbreite,
             aber ohne die aufgerissene Anmutung, die eine Schreibmaschinen-
             schrift bei einer Zahl wie 1.023,5 erzeugt. */
          font-variant-numeric: tabular-nums;
          font-size: 15px;
          color: var(--primary-text-color);
        }
        .hint, .error {
          font-size: 14px;
          line-height: 1.4;
          color: var(--secondary-text-color);
        }
        .error {
          color: var(--error-color, #db4437);
        }
        .hint {
          margin-top: 12px;
        }
        @media (max-width: 380px) {
          .text { font-size: 17px; }
          .plate { width: 40px; height: 40px; font-size: 22px; }
        }
      </style>
      <ha-card>${inner}</ha-card>`;
  }
}

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

console.info(`%c LOCAL-FORECAST-CARD %c ${CARD_VERSION} `,
  "color:white;background:#03a9f4;font-weight:700",
  "color:#03a9f4;background:white;font-weight:700");
