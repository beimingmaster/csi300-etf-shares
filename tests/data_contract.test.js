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
  assert.match(html, /id="fund-grid"/);
  assert.match(html, /href="\/data\/etf-shares\.csv"/);
  assert.match(script, /data\.funds\.map\(fundCard\)/);
  assert.match(script, /renderAggregate\(data\)/);
});
