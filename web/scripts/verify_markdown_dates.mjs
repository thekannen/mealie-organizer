import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

const server = await createServer({
  root: process.cwd(),
  appType: "custom",
  logLevel: "error",
  optimizeDeps: {
    entries: [],
    noDiscovery: true,
  },
  server: { middlewareMode: true },
});

const failures = [];

globalThis.window = {
  location: {
    pathname: "/",
  },
};

function check(name, fn) {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (error) {
    failures.push({ name, error });
    console.error(`FAIL ${name}`);
    console.error(error.message);
  }
}

function renderHtml(node) {
  return renderToStaticMarkup(React.createElement(React.Fragment, null, node));
}

try {
  const utils = await server.ssrLoadModule("/src/utils.jsx");
  const taskLogUtils = await server.ssrLoadModule("/src/pages/tasks/taskLogUtils.jsx");

  const markdownHtml = renderHtml(
    utils.renderMarkdownDocument(`## Details

See https://example.com and [docs](https://docs.example.com).

- [x] Done
- [ ] Later

| Name | Value |
| --- | --- |
| **Food** | \`salt\` |

![remote](https://images.example.com/food.png)

\`\`\`js
const x = 1;
\`\`\`
`)
  );

  check("markdown renders GFM autolinks with existing link class and safety attrs", () => {
    assert.match(
      markdownHtml,
      /<a href="https:\/\/example\.com" target="_blank" rel="noreferrer noopener" class="md-link">https:\/\/example\.com<\/a>/
    );
  });

  check("markdown renders GFM task list checkboxes", () => {
    assert.match(markdownHtml, /<input[^>]*type="checkbox"[^>]*checked/);
    assert.match(markdownHtml, /<input[^>]*type="checkbox"[^>]*disabled/);
  });

  check("markdown preserves table, code, inline code, link, and heading styling", () => {
    assert.match(markdownHtml, /<h4>Details<\/h4>/);
    assert.match(markdownHtml, /<div class="md-table-wrap"><table class="md-table">/);
    assert.match(markdownHtml, /<code class="md-inline-code">salt<\/code>/);
    assert.match(markdownHtml, /<pre class="doc-code"><code class="language-js">const x = 1;\n<\/code><\/pre>/);
    assert.match(
      markdownHtml,
      /<a href="https:\/\/docs\.example\.com" target="_blank" rel="noreferrer noopener" class="md-link">docs<\/a>/
    );
  });

  check("markdown renders images as safe links instead of remote images", () => {
    assert.doesNotMatch(markdownHtml, /<img\b/);
    assert.match(
      markdownHtml,
      /<a href="https:\/\/images\.example\.com\/food\.png" target="_blank" rel="noreferrer noopener" class="md-link">remote<\/a>/
    );
  });

  check("markdown keeps empty content fallback", () => {
    assert.equal(renderHtml(utils.renderMarkdownDocument(" \n\t ")), '<p class="muted tiny">No content available.</p>');
  });

  const originalNow = Date.now;
  Date.now = () => new Date("2026-05-02T12:00:00.000Z").getTime();
  try {
    check("date helpers keep compact relative labels and ignore invalid input", () => {
      assert.equal(utils.formatRelativeTime("2026-05-02T11:55:00.000Z"), "5m ago");
      assert.equal(utils.formatRelativeTime("2026-05-02T10:00:00.000Z"), "2h ago");
      assert.equal(utils.formatRelativeTime("2026-04-30T12:00:00.000Z"), "2d ago");
      assert.equal(utils.formatRelativeTime("2026-04-11T12:00:00.000Z"), "3w ago");
      assert.equal(utils.formatRelativeTime("2026-04-30T13:00:00.000Z"), "1d ago");
      assert.equal(utils.formatRelativeTime("not-a-date"), "");
    });

    check("countdown and runtime helpers preserve existing labels and ignore invalid input", () => {
      assert.equal(utils.formatCountdown("2026-05-02T12:30:00.000Z"), "in 30m");
      assert.equal(utils.formatCountdown("2026-05-02T14:05:00.000Z"), "in 2h 5m");
      assert.equal(utils.formatCountdown("2026-05-04T12:00:00.000Z"), "in 2d");
      assert.equal(utils.formatCountdown("2026-05-02T11:59:00.000Z"), "overdue");
      assert.equal(utils.formatCountdown("not-a-date"), null);
      assert.equal(
        utils.formatRunTime({ started_at: "2026-05-02T11:59:50.000Z", status: "running" }),
        "00:00:10"
      );
    });
  } finally {
    Date.now = originalNow;
  }

  check("task datetime helpers preserve local datetime input behavior", () => {
    const localInput = "2026-05-02T08:30";
    assert.equal(taskLogUtils.toDateTimeLocalValue(localInput), localInput);
    assert.equal(taskLogUtils.localDatetimeToUTC(localInput), new Date(localInput).toISOString());
    assert.equal(taskLogUtils.localDatetimeToUTC("not-a-date"), "not-a-date");
  });
} finally {
  await server.close();
}

if (failures.length > 0) {
  console.error(`\n${failures.length} verification check(s) failed.`);
  process.exit(1);
}

console.log("\nAll utility verification checks passed.");
