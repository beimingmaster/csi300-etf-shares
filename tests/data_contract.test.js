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
  assert.match(html, /id="holder-category-filter"/);
  assert.match(html, /id="fund-grid"/);
  assert.match(html, /href="\/data\/etf-shares\.csv"/);
  assert.match(html, /href="\/data\/holder-structure\.csv"/);
  assert.match(script, /data\.funds\.map\(fundCard\)/);
  assert.match(script, /renderAggregate\(data\)/);
  assert.match(script, /renderHolderAggregate/);
  assert.match(script, /data-chart-action/);
  assert.match(script, /"yaxis\.autorange": true/);
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
});
