import "@fontsource-variable/ibm-plex-sans";
import "@fontsource/ibm-plex-mono/latin-500.css";
import "@fontsource/ibm-plex-mono/latin-600.css";
import Plotly from "plotly.js-basic-dist-min";

import "./styles.css";


const numberFormat = new Intl.NumberFormat("zh-CN", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const integerFormat = new Intl.NumberFormat("zh-CN", {
  maximumFractionDigits: 0,
});

const dateFormat = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

const dateTimeFormat = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

const prefersDark = window.matchMedia("(prefers-color-scheme: dark)");
let currentData = null;


function parseLocalDate(value) {
  return new Date(`${value}T00:00:00+08:00`);
}


function formatDate(value) {
  return dateFormat.format(parseLocalDate(value));
}


function formatSigned(value, suffix = "") {
  const sign = value > 0 ? "+" : "";
  return `${sign}${numberFormat.format(value)}${suffix}`;
}


function getTheme() {
  const styles = getComputedStyle(document.documentElement);
  return {
    paper: styles.getPropertyValue("--surface").trim(),
    text: styles.getPropertyValue("--text").trim(),
    muted: styles.getPropertyValue("--text-muted").trim(),
    grid: styles.getPropertyValue("--grid-line").trim(),
    accent: styles.getPropertyValue("--accent").trim(),
    annotation: styles.getPropertyValue("--annotation-bg").trim(),
  };
}


function commonLayout(theme, height) {
  return {
    autosize: true,
    height,
    margin: { l: 58, r: 20, t: 28, b: 48 },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: {
      family: '"IBM Plex Sans Variable", "PingFang SC", "Microsoft YaHei", sans-serif',
      color: theme.muted,
      size: 12,
    },
    hoverlabel: {
      bgcolor: theme.annotation,
      bordercolor: theme.grid,
      font: { color: theme.text, size: 13 },
    },
    hovermode: "x unified",
    showlegend: false,
    xaxis: {
      type: "date",
      showgrid: false,
      showline: true,
      linecolor: theme.grid,
      tickfont: { color: theme.muted },
      fixedrange: false,
      rangeselector: {
        x: 0,
        y: 1.08,
        xanchor: "left",
        yanchor: "bottom",
        bgcolor: "rgba(0,0,0,0)",
        activecolor: theme.grid,
        font: { size: 11, color: theme.muted },
        buttons: [
          { count: 1, label: "1年", step: "year", stepmode: "backward" },
          { count: 3, label: "3年", step: "year", stepmode: "backward" },
          { count: 5, label: "5年", step: "year", stepmode: "backward" },
          { label: "全部", step: "all" },
        ],
      },
    },
    yaxis: {
      title: { text: "亿份", standoff: 10, font: { size: 11, color: theme.muted } },
      gridcolor: theme.grid,
      zeroline: false,
      tickfont: { color: theme.muted },
      fixedrange: false,
      rangemode: "tozero",
    },
  };
}


const plotConfig = {
  responsive: true,
  displayModeBar: false,
  scrollZoom: false,
  locale: "zh-CN",
};


function renderAggregate(data) {
  const theme = getTheme();
  const layout = commonLayout(theme, window.innerWidth < 768 ? 390 : 500);
  layout.margin = window.innerWidth < 768
    ? { l: 48, r: 12, t: 36, b: 44 }
    : layout.margin;
  layout.yaxis.rangemode = "normal";

  const trace = {
    type: "scatter",
    mode: "lines",
    x: data.dates,
    y: data.aggregate.values,
    line: { color: theme.accent, width: 2.6 },
    fill: "tozeroy",
    fillcolor: prefersDark.matches
      ? "rgba(217, 103, 44, 0.12)"
      : "rgba(201, 89, 41, 0.11)",
    hovertemplate: "%{x|%Y-%m-%d}<br><b>%{y:.2f} 亿份</b><extra></extra>",
  };

  return Plotly.react("aggregate-chart", [trace], layout, plotConfig);
}


function extremaAnnotations(fund, dates, theme) {
  const entries = [
    {
      date: fund.maximum_date,
      value: fund.maximum_shares_100m,
      text: `最高 ${numberFormat.format(fund.maximum_shares_100m)}`,
      ay: 34,
    },
    {
      date: fund.minimum_date,
      value: fund.minimum_shares_100m,
      text: `最低 ${numberFormat.format(fund.minimum_shares_100m)}`,
      ay: -34,
    },
  ];
  const midpoint = dates[Math.floor(dates.length / 2)];
  return entries.map((entry) => ({
    x: entry.date,
    y: entry.value,
    text: entry.text,
    showarrow: true,
    arrowhead: 0,
    arrowwidth: 1,
    arrowcolor: theme.grid,
    ax: entry.date < midpoint ? 54 : -54,
    ay: entry.ay,
    bgcolor: theme.annotation,
    bordercolor: theme.grid,
    borderwidth: 1,
    borderpad: 4,
    font: { size: 10, color: theme.muted },
  }));
}


function eventLayers(data, fund, theme) {
  const events = data.reviewed_events.filter((event) => event.code === fund.code);
  const shapes = [];
  const annotations = [];
  for (const event of events) {
    shapes.push({
      type: "line",
      x0: event.date,
      x1: event.date,
      y0: 0,
      y1: 1,
      yref: "paper",
      line: { color: theme.accent, width: 1.2, dash: "dot" },
    });
    annotations.push({
      x: event.date,
      y: 1,
      yref: "paper",
      text: event.label,
      showarrow: false,
      xanchor: "left",
      yanchor: "top",
      textangle: -90,
      font: { size: 10, color: theme.accent },
    });
  }
  return { shapes, annotations };
}


function renderFundChart(data, fund) {
  const theme = getTheme();
  const chartId = `chart-${fund.code}`;
  const layout = commonLayout(theme, window.innerWidth < 768 ? 330 : 360);
  layout.margin = window.innerWidth < 768
    ? { l: 48, r: 10, t: 32, b: 42 }
    : { l: 54, r: 14, t: 34, b: 44 };
  layout.yaxis.rangemode = "normal";
  const eventLayer = eventLayers(data, fund, theme);
  layout.shapes = eventLayer.shapes;
  layout.annotations = window.innerWidth < 640
    ? eventLayer.annotations
    : [...extremaAnnotations(fund, data.dates, theme), ...eventLayer.annotations];

  const trace = {
    type: "scatter",
    mode: "lines",
    x: data.dates,
    y: data.series[fund.code],
    line: { color: fund.color, width: 2.2, dash: fund.line_dash },
    hovertemplate: "%{x|%Y-%m-%d}<br><b>%{y:.2f} 亿份</b><extra></extra>",
  };

  return Plotly.react(chartId, [trace], layout, plotConfig);
}


function fundCard(fund) {
  const changeClass = fund.change_pct > 0 ? "positive" : fund.change_pct < 0 ? "negative" : "";
  return `
    <article class="fund-panel" aria-labelledby="fund-title-${fund.code}">
      <header class="fund-header">
        <div>
          <p class="fund-code">${fund.code} / TOP ${fund.rank}</p>
          <h3 id="fund-title-${fund.code}">${fund.name}</h3>
          <p class="fund-manager">${fund.manager} / ${fund.exchange}</p>
        </div>
        <div class="fund-latest">
          <strong>${numberFormat.format(fund.latest_shares_100m)}</strong>
          <span>亿份</span>
        </div>
      </header>
      <div class="chart-shell">
        <div class="chart-loading" aria-hidden="true"></div>
        <div
          class="chart"
          id="chart-${fund.code}"
          role="img"
          aria-label="${fund.name}${fund.code}最近十年份额趋势图"
        ></div>
      </div>
      <dl class="fund-stats">
        <div>
          <dt>十年变化</dt>
          <dd class="${changeClass}">${formatSigned(fund.change_pct, "%")}</dd>
        </div>
        <div>
          <dt>最高</dt>
          <dd>${numberFormat.format(fund.maximum_shares_100m)} <small>${formatDate(fund.maximum_date)}</small></dd>
        </div>
        <div>
          <dt>最低</dt>
          <dd>${numberFormat.format(fund.minimum_shares_100m)} <small>${formatDate(fund.minimum_date)}</small></dd>
        </div>
      </dl>
    </article>
  `;
}


function populateSummary(data) {
  const metadata = data.metadata;
  document.querySelector("#header-date").textContent = `数据截止 ${formatDate(metadata.latest_data_date)}`;
  document.querySelector("#latest-date").textContent = formatDate(metadata.latest_data_date);
  document.querySelector("#observation-count").textContent = integerFormat.format(metadata.common_observations);
  document.querySelector("#aggregate-latest").textContent = numberFormat.format(data.aggregate.latest_shares_100m);
  document.querySelector("#aggregate-change").textContent = formatSigned(data.aggregate.change_pct, "%");
  document.querySelector("#updated-at").textContent = dateTimeFormat.format(new Date(metadata.updated_at));

  const latest = parseLocalDate(metadata.latest_data_date);
  const ageDays = Math.floor((Date.now() - latest.getTime()) / 86_400_000);
  const freshness = document.querySelector("#freshness-label");
  freshness.textContent = ageDays <= 4 ? "数据正常" : `延迟 ${ageDays} 天`;
  freshness.classList.toggle("stale", ageDays > 4);
}


async function render(data) {
  currentData = data;
  populateSummary(data);
  const grid = document.querySelector("#fund-grid");
  grid.innerHTML = data.funds.map(fundCard).join("");
  await renderAggregate(data);
  await Promise.all(data.funds.map((fund) => renderFundChart(data, fund)));
  document.body.classList.add("data-ready");
}


async function load() {
  try {
    const response = await fetch(`${import.meta.env.BASE_URL}data/etf-shares.json`, {
      cache: "no-cache",
    });
    if (!response.ok) {
      throw new Error(`data request failed with ${response.status}`);
    }
    const data = await response.json();
    if (!Array.isArray(data.dates) || data.dates.length === 0 || data.funds.length !== 4) {
      throw new Error("data contract is incomplete");
    }
    await render(data);
  } catch (error) {
    console.error(error);
    document.querySelector("#data-error").hidden = false;
    document.body.classList.add("data-failed");
  }
}


prefersDark.addEventListener("change", () => {
  if (currentData) {
    render(currentData);
  }
});

load();
