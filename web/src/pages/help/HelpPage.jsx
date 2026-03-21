import React, { useState } from "react";
import Icon from "../../components/Icon";
import { api } from "../../utils.jsx";
import { HELP_FAQ, HELP_TROUBLESHOOTING, HELP_TASK_GUIDES, HELP_SETUP_GUIDES } from "../../constants";

export default function HelpPage({ aboutMeta }) {
  const [debugLog, setDebugLog] = useState(null);
  const [debugLogLoading, setDebugLogLoading] = useState(false);

  async function fetchDebugLog() {
    setDebugLogLoading(true);
    try {
      const data = await api("/debug-log");
      setDebugLog(data);
    } catch (e) {
      setDebugLog({ error: String(e), log: "", log_available: false });
    } finally {
      setDebugLogLoading(false);
    }
  }

  function downloadDebugLog() {
    if (!debugLog) return;
    const h = debugLog.health || {};
    const db = h.db || {};
    const cfg = h.config || {};
    const conns = h.connections || {};
    const runs = h.runs || {};
    const sc = h.scheduler || {};
    const statusCounts = runs.status_counts || {};
    const connLine = (label, c) => `${label.padEnd(12)}${c?.ok ? "OK" : "FAIL"}  ${c?.detail || ""}`;

    const sections = [
      "=== CookDex Debug Report ===",
      `Version:    ${debugLog.app_version || "-"}`,
      `Python:     ${debugLog.python_version || "-"}`,
      `Platform:   ${debugLog.platform || "-"}`,
      `Log file:   ${debugLog.log_file || "-"}`,
      "",
      "=== Connection Tests ===",
      connLine("Mealie", conns.mealie),
      connLine("OpenAI", conns.openai),
      connLine("Anthropic", conns.anthropic),
      connLine("Ollama", conns.ollama),
      connLine("Direct DB", conns.direct_db),
      "",
      "=== Instance Health ===",
      `Users:      ${db.user_count ?? "-"}`,
      `Runs total: ${db.run_count ?? "-"}  (${Object.entries(statusCounts).map(([k, v]) => `${k}: ${v}`).join(", ") || "none"})`,
      `Schedules:  ${db.schedule_count ?? "-"} total, ${db.enabled_schedules ?? "-"} enabled`,
      `Scheduler:  ${sc.running ? "running" : "stopped"}`,
      "",
      "=== Configuration ===",
      `Mealie URL:       ${cfg.mealie_url_set ? "set" : "NOT SET"}`,
      `Mealie key:       ${cfg.mealie_key_set ? "set" : "NOT SET"}`,
      `OpenAI key:       ${cfg.openai_key_set ? "set" : "not set"}`,
      `OpenAI model:     ${cfg.openai_model || "(default)"}`,
      `Anthropic key:    ${cfg.anthropic_key_set ? "set" : "not set"}`,
      `Anthropic model:  ${cfg.anthropic_model || "(default)"}`,
      `Ollama URL:       ${cfg.ollama_url_set ? "set" : "not set"}`,
      `Ollama model:     ${cfg.ollama_model || "(default)"}`,
      "",
      "=== Recent Runs ===",
      ...(runs.recent || []).map(r =>
        `${r.started_at || "-"}  ${r.status.padEnd(10)}  ${r.task_id}  (${r.triggered_by})`
      ),
      "",
      "=== Server Log ===",
      debugLog.log || "(no log content)",
    ].join("\n");

    const blob = new Blob([sections], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "cookdex-debug.log";
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <section className="page-grid settings-grid help-grid">
      <div className="stacked-cards">
        <article className="card">
          <h3>Quick Guides</h3>
          <p className="muted">How to find the credentials and keys CookDex needs.</p>

          <div className="accordion-stack">
            {HELP_SETUP_GUIDES.map((guide) => (
              <details className="accordion" key={guide.id}>
                <summary>
                  <Icon name={guide.icon || "info"} />
                  <span>{guide.title}</span>
                  <Icon name="chevron" />
                </summary>
                <div className="doc-preview">
                  <p style={{ fontSize: "0.82rem", marginBottom: "0.5rem" }}>{guide.what}</p>
                  <ol style={{ margin: "0 0 0.6rem", paddingLeft: "1.2rem" }}>
                    {guide.steps.map((step, i) => (
                      <li key={i} className="muted" style={{ fontSize: "0.82rem", marginBottom: "0.25rem" }}>{step}</li>
                    ))}
                  </ol>
                  {guide.tip && (
                    <p className="muted" style={{ fontSize: "0.8rem", borderLeft: "3px solid var(--accent)", paddingLeft: "0.6rem", margin: 0 }}>
                      <strong>Tip:</strong> {guide.tip}
                    </p>
                  )}
                </div>
              </details>
            ))}
          </div>
        </article>

        <article className="card">
          <h3>Task Guides</h3>
          <p className="muted">Step-by-step instructions for every available task.</p>

          <div className="accordion-stack">
            {(() => {
              let lastGroup = null;
              return HELP_TASK_GUIDES.flatMap((guide) => {
                const items = [];
                if (guide.group !== lastGroup) {
                  lastGroup = guide.group;
                  items.push(
                    <p key={`group-${guide.group}`} className="accordion-group-label">
                      {guide.group}
                    </p>
                  );
                }
                items.push(
                  <details className="accordion" key={guide.id}>
                    <summary>
                      <Icon name={guide.icon || "play"} />
                      <span>{guide.title}</span>
                      <Icon name="chevron" />
                    </summary>
                    <div className="doc-preview">
                      <p style={{ fontSize: "0.82rem", marginBottom: "0.5rem" }}>{guide.what}</p>
                      <ol style={{ margin: "0 0 0.6rem", paddingLeft: "1.2rem" }}>
                        {guide.steps.map((step, i) => (
                          <li key={i} className="muted" style={{ fontSize: "0.82rem", marginBottom: "0.25rem" }}>{step}</li>
                        ))}
                      </ol>
                      {guide.tip && (
                        <p className="muted" style={{ fontSize: "0.8rem", borderLeft: "3px solid var(--accent)", paddingLeft: "0.6rem", margin: 0 }}>
                          <strong>Tip:</strong> {guide.tip}
                        </p>
                      )}
                    </div>
                  </details>
                );
                return items;
              });
            })()}
          </div>
        </article>

        <article className="card">
          <h3>Frequently Asked Questions</h3>
          <p className="muted">Common workflows and quick answers for daily use.</p>

          <div className="accordion-stack">
            {HELP_FAQ.map((item, index) => (
              <details className="accordion" key={item.question} open={index === 0}>
                <summary>
                  <Icon name={item.icon || "help"} />
                  <span>{item.question}</span>
                  <Icon name="chevron" />
                </summary>
                <p>{item.answer}</p>
              </details>
            ))}
          </div>
        </article>
      </div>

      <aside className="stacked-cards">
        <article className="card">
          <h3>Troubleshooting</h3>
          <p className="muted">Common issues grouped by area.</p>

          <div className="accordion-stack">
            {HELP_TROUBLESHOOTING.map((section) => (
              <details className="accordion" key={section.title}>
                <summary>
                  <Icon name={section.icon || "info"} />
                  <span>{section.title}</span>
                  <Icon name="chevron" />
                </summary>
                <div className="doc-preview">
                  <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>
                    {section.items.map((tip, idx) => (
                      <li key={idx} className="muted" style={{ fontSize: "0.82rem", marginBottom: "0.3rem" }}>
                        {tip}
                      </li>
                    ))}
                  </ul>
                </div>
              </details>
            ))}
          </div>
        </article>

        <article className="card">
          <h3>Report a Bug</h3>
          <p className="muted">Collect debug logs and open a GitHub issue to help the developer reproduce and fix problems.</p>

          <div className="debug-actions">
            <a
              className="button ghost"
              href={(aboutMeta?.links?.github || "https://github.com/thekannen/cookdex") + "/issues/new"}
              target="_blank"
              rel="noreferrer"
            >
              <Icon name="external" /> Open a GitHub Issue
            </a>

            {!debugLog ? (
              <button className="ghost" type="button" onClick={fetchDebugLog} disabled={debugLogLoading}>
                <Icon name={debugLogLoading ? "refresh" : "list"} />
                {debugLogLoading ? "Generating\u2026" : "Generate Debug Log"}
              </button>
            ) : (
              <>
                {debugLog.error ? (
                  <p className="muted tiny" style={{ color: "var(--error, #c0392b)" }}>{debugLog.error}</p>
                ) : (() => {
                  const h = debugLog.health || {};
                  const db = h.db || {};
                  const cfg = h.config || {};
                  const conns = h.connections || {};
                  const runs = h.runs || {};
                  const sc = h.scheduler || {};
                  const counts = runs.status_counts || {};
                  const ConnRow = ({ label, conn, detail }) => (
                    <div className="debug-health-row">
                      <span className="muted tiny">{label}</span>
                      <span className={`status-pill ${conn?.ok ? "success" : conn?.detail === "Not configured" ? "neutral" : "danger"}`}
                        title={conn?.detail || ""}>
                        {conn?.ok ? "OK" : conn?.detail === "Not configured" ? "Not configured" : "Failed"}
                      </span>
                    </div>
                  );
                  return (
                    <>
                      <div className="debug-health-grid">
                        <div className="debug-health-row">
                          <span className="muted tiny">Scheduler</span>
                          <span className={`status-pill ${sc.running ? "success" : "danger"}`}>{sc.running ? "Running" : "Stopped"}</span>
                        </div>
                        <ConnRow label="Mealie" conn={conns.mealie} />
                        <ConnRow label="OpenAI" conn={conns.openai} />
                        <ConnRow label="Anthropic" conn={conns.anthropic} />
                        <ConnRow label="Ollama" conn={conns.ollama} />
                        <ConnRow label="Direct DB" conn={conns.direct_db} />
                        <div className="debug-health-row">
                          <span className="muted tiny">Runs</span>
                          <span className="muted tiny">
                            {db.run_count ?? 0} total
                            {counts.failed ? <span style={{ color: "var(--error, #c0392b)", marginLeft: "0.4rem" }}>{counts.failed} failed</span> : null}
                          </span>
                        </div>
                        <div className="debug-health-row">
                          <span className="muted tiny">Schedules</span>
                          <span className="muted tiny">{db.enabled_schedules ?? 0} of {db.schedule_count ?? 0} enabled</span>
                        </div>
                      </div>
                      {!debugLog.log_available ? (
                        <p className="muted tiny">No server log file found yet — logs appear after the first server restart.</p>
                      ) : (
                        <pre className="debug-log-preview">{debugLog.log}</pre>
                      )}
                    </>
                  );
                })()}
                <div className="debug-log-row">
                  <button className="ghost small" type="button" onClick={downloadDebugLog}>
                    <Icon name="download" /> Download Report
                  </button>
                  <button className="ghost small" type="button" onClick={() => setDebugLog(null)}>
                    <Icon name="refresh" /> Regenerate
                  </button>
                </div>
                {debugLog.app_version && (
                  <p className="muted tiny">v{debugLog.app_version} · {debugLog.platform}</p>
                )}
              </>
            )}
          </div>
        </article>
      </aside>
    </section>
  );
}
