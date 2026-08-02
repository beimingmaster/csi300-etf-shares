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
let currentHolderData = null;
let holderMetric = "shares_100m";


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
    holderColors: {
      national_team: styles.getPropertyValue("--holder-national").trim(),
      other_institution: styles.getPropertyValue("--holder-institution").trim(),
      individual: styles.getPropertyValue("--holder-individual").trim(),
    },
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
  doubleClick: "reset+autosize",
  locale: "zh-CN",
};


function revealChart(chartId) {
  document.querySelector(`#${chartId}`)?.closest(".chart-shell")?.classList.add("is-ready");
}


function visibleYRange(chart, xRange) {
  const start = new Date(xRange[0]).getTime();
  const end = new Date(xRange[1]).getTime();
  const values = [];
  for (const trace of chart.data) {
    (trace.x || []).forEach((xValue, index) => {
      const timestamp = new Date(xValue).getTime();
      const yValue = Number(trace.y?.[index]);
      if (timestamp >= start && timestamp <= end && Number.isFinite(yValue)) {
        values.push(yValue);
      }
    });
  }
  if (values.length === 0) {
    return null;
  }
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const span = Math.max(maximum - minimum, Math.abs(maximum) * 0.08, 1);
  if (chart._fullLayout?.yaxis?.rangemode === "tozero" && minimum >= 0) {
    return [0, maximum + span * 0.08];
  }
  return [minimum - span * 0.1, maximum + span * 0.1];
}


function bindVisibleRangeAutorange(chartId) {
  const chart = document.querySelector(`#${chartId}`);
  if (!chart || typeof chart.on !== "function") {
    return;
  }
  if (chart.visibleRangeHandler && typeof chart.removeListener === "function") {
    chart.removeListener("plotly_relayout", chart.visibleRangeHandler);
  }
  chart.visibleRangeHandler = (changes) => {
    const xChanged = Object.keys(changes).some((key) => (
      key === "xaxis.range"
      || key.startsWith("xaxis.range[")
      || key === "xaxis.autorange"
    ));
    const yChanged = Object.keys(changes).some((key) => key.startsWith("yaxis."));
    if (xChanged && !yChanged) {
      if (changes["xaxis.autorange"]) {
        Plotly.relayout(chart, { "yaxis.autorange": true });
        return;
      }
      const xRange = changes["xaxis.range"] || [
        changes["xaxis.range[0]"] || chart._fullLayout.xaxis.range[0],
        changes["xaxis.range[1]"] || chart._fullLayout.xaxis.range[1],
      ];
      const yRange = visibleYRange(chart, xRange);
      if (yRange) {
        Plotly.relayout(chart, { "yaxis.range": yRange });
      }
    }
  };
  chart.on("plotly_relayout", chart.visibleRangeHandler);
}


function finishChart(chartId) {
  revealChart(chartId);
  bindVisibleRangeAutorange(chartId);
}


function chartDateBounds(chart) {
  const timestamps = chart.data
    .flatMap((trace) => trace.x || [])
    .map((value) => new Date(value).getTime())
    .filter(Number.isFinite);
  if (timestamps.length === 0) {
    return null;
  }
  return [Math.min(...timestamps), Math.max(...timestamps)];
}


async function resetChart(chart) {
  await Plotly.relayout(chart, {
    "xaxis.autorange": true,
    "yaxis.autorange": true,
  });
}


async function zoomChart(chart, factor) {
  const bounds = chartDateBounds(chart);
  const currentRange = chart._fullLayout?.xaxis?.range || chart.layout?.xaxis?.range;
  if (!bounds || !currentRange) {
    await resetChart(chart);
    return;
  }
  const [fullStart, fullEnd] = bounds;
  const start = new Date(currentRange[0]).getTime();
  const end = new Date(currentRange[1]).getTime();
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) {
    await resetChart(chart);
    return;
  }

  const fullSpan = Math.max(fullEnd - fullStart, 86_400_000);
  const targetSpan = Math.min(Math.max((end - start) * factor, 86_400_000), fullSpan);
  if (targetSpan >= fullSpan * 0.995) {
    await resetChart(chart);
    return;
  }
  const center = (start + end) / 2;
  let nextStart = center - targetSpan / 2;
  let nextEnd = center + targetSpan / 2;
  if (nextStart < fullStart) {
    nextEnd += fullStart - nextStart;
    nextStart = fullStart;
  }
  if (nextEnd > fullEnd) {
    nextStart -= nextEnd - fullEnd;
    nextEnd = fullEnd;
  }
  const xRange = [new Date(nextStart).toISOString(), new Date(nextEnd).toISOString()];
  const yRange = visibleYRange(chart, xRange);
  const changes = { "xaxis.range": xRange };
  if (yRange) {
    changes["yaxis.range"] = yRange;
  } else {
    changes["yaxis.autorange"] = true;
  }
  await Plotly.relayout(chart, changes);
}


document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-chart-action]");
  if (!button) {
    return;
  }
  const chart = document.querySelector(`#${button.dataset.chartId}`);
  if (!chart?.data) {
    return;
  }
  button.disabled = true;
  try {
    if (button.dataset.chartAction === "zoom-in") {
      await zoomChart(chart, 0.62);
    } else if (button.dataset.chartAction === "zoom-out") {
      await zoomChart(chart, 1.62);
    } else {
      await resetChart(chart);
    }
  } finally {
    button.disabled = false;
  }
});


async function renderAggregate(data) {
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

  await Plotly.react("aggregate-chart", [trace], layout, plotConfig);
  finishChart("aggregate-chart");
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


async function renderFundChart(data, fund) {
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

  await Plotly.react(chartId, [trace], layout, plotConfig);
  finishChart(chartId);
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
        <div class="chart-tools" role="group" aria-label="${fund.code}图表缩放控制">
          <button type="button" data-chart-action="zoom-in" data-chart-id="chart-${fund.code}" aria-label="放大${fund.code}图表">+</button>
          <button type="button" data-chart-action="zoom-out" data-chart-id="chart-${fund.code}" aria-label="缩小${fund.code}图表">−</button>
          <button type="button" data-chart-action="reset" data-chart-id="chart-${fund.code}">重置</button>
        </div>
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


function selectedHolderCategories() {
  return [...document.querySelectorAll("#holder-category-filter input:checked")]
    .map((input) => input.value);
}


function holderTrace(data, values, categoryKey, metric) {
  const category = data.categories[categoryKey];
  const theme = getTheme();
  const suffix = metric === "ratio_pct" ? "%" : " 亿份";
  const markerSymbols = {
    national_team: "diamond",
    other_institution: "square",
    individual: "circle",
  };
  return {
    type: "scatter",
    mode: "lines+markers",
    name: category.label,
    legendgroup: categoryKey,
    x: data.periods,
    y: values,
    line: {
      color: theme.holderColors[categoryKey],
      width: categoryKey === "national_team" ? 2.8 : 2.2,
      dash: category.line_dash,
    },
    marker: {
      color: theme.holderColors[categoryKey],
      size: categoryKey === "national_team" ? 8 : 7,
      symbol: markerSymbols[categoryKey],
      line: { color: theme.paper, width: 1 },
    },
    customdata: data.periods.map(() => category.precision_label),
    hovertemplate: [
      "%{x|%Y-%m-%d}",
      `<b>%{y:.2f}${suffix}</b>`,
      "%{customdata}",
      "<extra>%{fullData.name}</extra>",
    ].join("<br>"),
  };
}


function holderLayout(metric, showLegend, revisionKey) {
  const theme = getTheme();
  const mobile = window.innerWidth < 768;
  const layout = commonLayout(theme, mobile ? 370 : 420);
  delete layout.xaxis.rangeselector;
  layout.margin = mobile
    ? { l: 50, r: 10, t: 32, b: showLegend ? 150 : 54 }
    : { l: 62, r: 16, t: 34, b: showLegend ? 94 : 54 };
  layout.height = mobile && showLegend ? 460 : layout.height;
  layout.dragmode = "zoom";
  layout.showlegend = showLegend;
  layout.uirevision = revisionKey;
  layout.xaxis.tickformat = "%Y-%m";
  layout.xaxis.tickangle = mobile ? -35 : 0;
  layout.yaxis.title.text = metric === "ratio_pct" ? "占总份额（%）" : "亿份";
  layout.yaxis.rangemode = "tozero";
  layout.legend = showLegend
    ? {
        orientation: mobile ? "v" : "h",
        x: 0,
        y: mobile ? -0.18 : -0.23,
        xanchor: "left",
        yanchor: "top",
        font: { size: mobile ? 10 : 11, color: theme.muted },
        bgcolor: "rgba(0,0,0,0)",
      }
    : undefined;
  return layout;
}


function holderFundCard(fund) {
  const metricLabel = holderMetric === "ratio_pct" ? "占总份额" : "持有份额";
  return `
    <article class="holder-fund-panel" aria-labelledby="holder-fund-title-${fund.code}">
      <header>
        <div>
          <p class="panel-index">${fund.code}</p>
          <h4 id="holder-fund-title-${fund.code}">${fund.name}</h4>
        </div>
        <span class="holder-fund-unit">${metricLabel}</span>
      </header>
      <div class="chart-shell">
        <div class="chart-loading" aria-hidden="true"></div>
        <div class="chart-tools" role="group" aria-label="${fund.code}持有人图缩放控制">
          <button type="button" data-chart-action="zoom-in" data-chart-id="holder-fund-chart-${fund.code}" aria-label="放大${fund.code}持有人图">+</button>
          <button type="button" data-chart-action="zoom-out" data-chart-id="holder-fund-chart-${fund.code}" aria-label="缩小${fund.code}持有人图">−</button>
          <button type="button" data-chart-action="reset" data-chart-id="holder-fund-chart-${fund.code}">重置</button>
        </div>
        <div
          class="chart holder-fund-chart"
          id="holder-fund-chart-${fund.code}"
          role="img"
          aria-label="${fund.name}按持有人类别的${metricLabel}趋势图"
        ></div>
      </div>
    </article>
  `;
}


async function renderHolderAggregate(data, metric, chartId) {
  const categories = selectedHolderCategories();
  const traces = categories.map((categoryKey) => holderTrace(
    data,
    data.aggregate.categories[categoryKey][metric],
    categoryKey,
    metric,
  ));
  const layout = holderLayout(
    metric,
    true,
    `${chartId}-${metric}-${categories.join("-")}-${prefersDark.matches}`,
  );
  await Plotly.react(chartId, traces, layout, plotConfig);
  finishChart(chartId);
}


async function renderHolderFund(data, fund) {
  const categories = selectedHolderCategories();
  const traces = categories.map((categoryKey) => holderTrace(
    data,
    data.series[fund.code].categories[categoryKey][holderMetric],
    categoryKey,
    holderMetric,
  ));
  const chartId = `holder-fund-chart-${fund.code}`;
  const layout = holderLayout(
    holderMetric,
    false,
    `${chartId}-${holderMetric}-${categories.join("-")}-${prefersDark.matches}`,
  );
  layout.height = window.innerWidth < 768 ? 320 : 340;
  await Plotly.react(chartId, traces, layout, plotConfig);
  finishChart(chartId);
}


function populateHolderSummary(data) {
  document.querySelector("#holder-latest-period").textContent = formatDate(
    data.metadata.latest_period,
  );
  document.querySelector("#holder-latest-disclosure").textContent = formatDate(
    data.metadata.latest_disclosure_date,
  );
}


async function renderHolders(data) {
  currentHolderData = data;
  populateHolderSummary(data);
  const grid = document.querySelector("#holder-fund-grid");
  grid.innerHTML = data.funds.map(holderFundCard).join("");
  await Promise.all([
    renderHolderAggregate(data, "shares_100m", "holder-aggregate-shares-chart"),
    renderHolderAggregate(data, "ratio_pct", "holder-aggregate-ratio-chart"),
    ...data.funds.map((fund) => renderHolderFund(data, fund)),
  ]);
}


document.querySelector("#holder-category-filter").addEventListener("change", async (event) => {
  const message = document.querySelector("#holder-filter-message");
  if (selectedHolderCategories().length === 0) {
    event.target.checked = true;
    message.textContent = "至少保留一个持有人类别。";
    return;
  }
  message.textContent = "";
  if (currentHolderData) {
    await renderHolders(currentHolderData);
  }
});


document.querySelectorAll("[data-holder-metric]").forEach((button) => {
  button.addEventListener("click", async () => {
    holderMetric = button.dataset.holderMetric;
    document.querySelectorAll("[data-holder-metric]").forEach((item) => {
      item.setAttribute("aria-pressed", String(item === button));
    });
    if (currentHolderData) {
      await renderHolders(currentHolderData);
    }
  });
});


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
}


async function loadShareData() {
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


async function loadHolderData() {
  try {
    const response = await fetch(`${import.meta.env.BASE_URL}data/holder-structure.json`, {
      cache: "no-cache",
    });
    if (!response.ok) {
      throw new Error(`holder data request failed with ${response.status}`);
    }
    const data = await response.json();
    if (
      !Array.isArray(data.periods)
      || data.periods.length === 0
      || data.funds.length !== 4
      || data.metadata.disclosure_frequency !== "semiannual"
    ) {
      throw new Error("holder data contract is incomplete");
    }
    await renderHolders(data);
  } catch (error) {
    console.error(error);
    document.querySelector("#holder-data-error").hidden = false;
  }
}


prefersDark.addEventListener("change", async () => {
  if (currentData) {
    await render(currentData);
  }
  if (currentHolderData) {
    await renderHolders(currentHolderData);
  }
});

Promise.allSettled([loadShareData(), loadHolderData()]);
