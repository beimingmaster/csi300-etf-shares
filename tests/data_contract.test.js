import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);

async function read(relativePath) {
  return readFile(new URL(relativePath, root), "utf8");
}

test("visible source copy avoids long dash characters", async () => {
  const files = await Promise.all([
    read("index.html"),
    read("src/main.js"),
    read("src/styles.css"),
  ]);
  assert.doesNotMatch(files.join("\n"), /[—–]/u);
});

test("the page exposes all required static data views", async () => {
  const [html, script] = await Promise.all([
    read("index.html"),
    read("src/main.js"),
  ]);

  assert.match(html, /id="aggregate-chart"/);
  assert.match(html, /id="about"/);
  assert.match(html, /id="holder-aggregate-shares-chart"/);
  assert.match(html, /id="holder-aggregate-ratio-chart"/);
  assert.match(html, /id="holder-chinext-shares-chart"/);
  assert.match(html, /id="holder-chinext-ratio-chart"/);
  assert.match(html, /id="holder-category-filter"/);
  assert.match(html, /id="fund-grid"/);
  assert.match(html, /href="\/data\/etf-shares\.csv"/);
  assert.match(html, /href="\/data\/holder-structure\.csv"/);
  assert.match(script, /data\.funds\.map\(fundCard\)/);
  assert.match(script, /fund-panel-standalone/);
  assert.match(script, /data\.funds\.length !== 5/);
  assert.match(script, /data\.quality_series\[fund\.code\]/);
  assert.match(script, /renderAggregate\(data\)/);
  assert.match(script, /renderHolderAggregate/);
  assert.match(script, /renderHolderStandalone/);
  assert.match(script, /data-chart-action/);
  assert.match(script, /bindPressCursor/);
  assert.match(script, /chart-press-readout/);
  assert.match(script, /"yaxis\.autorange": true/);
  assert.match(html, /2012年至今/);
  assert.match(html, /159915只在此独立展示/);
});

test("holder controls expose all requested categories and metrics", async () => {
  const [html, script] = await Promise.all([
    read("index.html"),
    read("src/main.js"),
  ]);

  for (const category of ["national_team", "other_institution", "individual"]) {
    assert.match(html, new RegExp(`value="${category}"`));
  }
  assert.match(html, /data-holder-metric="shares_100m"/);
  assert.match(html, /data-holder-metric="ratio_pct"/);
  assert.match(script, /selectedHolderCategories/);
  assert.match(script, /metadata\.aggregate_fund_codes/);
  assert.match(script, /metadata\.standalone_fund_codes/);
});

test("CI installs Python requirements before running the test suite", async () => {
  const workflow = await read(".github/workflows/ci.yml");
  const installStep = workflow.indexOf("pip install -r scripts/requirements.txt");
  const testStep = workflow.indexOf("- run: npm test");

  assert.notEqual(installStep, -1, "CI must install scripts/requirements.txt");
  assert.ok(installStep < testStep, "CI must install Python dependencies before npm test");
});

test("range selector clicks bypass press cursor interception", async () => {
  const script = await read("src/main.js");
  const handlerStart = script.indexOf("const onPointerDown = (event) => {");
  const handlerEnd = script.indexOf("const onPointerMove = (event) => {", handlerStart);
  const handler = script.slice(handlerStart, handlerEnd);

  assert.match(handler, /event\.target\.closest\?\.\("\.rangeselector"\)/);
  assert.ok(
    handler.indexOf(".rangeselector") < handler.indexOf("event.preventDefault()"),
    "range selector guard must run before pointerdown prevents the native click",
  );
});
