import React, { useMemo } from "react";
import Icon from "../../components/Icon";
import CoverageRing from "../../components/CoverageRing";
import { formatDateTime, parseIso } from "../../utils.jsx";

export default function OverviewPage({
  tasks,
  runs,
  schedules,
  overviewMetrics,
  qualityMetrics,
  taxonomyCounts,
  navigateTo,
  onTaskHandoff,
}) {
  const taskTitleById = useMemo(() => {
    const map = new Map();
    for (const task of tasks) map.set(task.task_id, task.title);
    return map;
  }, [tasks]);

  const runStats = useMemo(() => {
    const stats = { queued: 0, running: 0, succeeded: 0, failed: 0, canceled: 0 };
    for (const run of runs) {
      const key = String(run.status || "").toLowerCase();
      if (stats[key] !== undefined) {
        stats[key] += 1;
      }
    }
    return stats;
  }, [runs]);

  const sortedRuns = useMemo(() => {
    const copy = [...runs];
    copy.sort((a, b) => {
      const aTs = parseIso(a.started_at || a.created_at)?.getTime() || 0;
      const bTs = parseIso(b.started_at || b.created_at)?.getTime() || 0;
      return bTs - aTs;
    });
    return copy;
  }, [runs]);

  const runsTodayCount = useMemo(() => {
    const now = new Date();
    const start = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    return sortedRuns.filter((run) => {
      const ts = parseIso(run.started_at || run.created_at)?.getTime() || 0;
      return ts >= start;
    }).length;
  }, [sortedRuns]);

  const latestFailureLabel = useMemo(() => {
    const failed = sortedRuns.find((run) => String(run.status || "").toLowerCase() === "failed");
    if (!failed) {
      return "None";
    }
    const ts = parseIso(failed.finished_at || failed.started_at || failed.created_at);
    if (!ts) {
      return "Unknown";
    }
    const deltaMs = Date.now() - ts.getTime();
    const deltaDays = Math.floor(deltaMs / (24 * 60 * 60 * 1000));
    if (deltaDays <= 0) {
      return "Today";
    }
    return `${deltaDays}d ago`;
  }, [sortedRuns]);

  const upcomingScheduleCount = useMemo(() => {
    const now = Date.now();
    const nextDay = now + 24 * 60 * 60 * 1000;
    return schedules.filter((schedule) => {
      const ts = parseIso(schedule.next_run_at)?.getTime();
      return Boolean(ts && ts >= now && ts <= nextDay);
    }).length;
  }, [schedules]);

  const taskMixRows = useMemo(() => {
    const weekAgo = Date.now() - 7 * 24 * 60 * 60 * 1000;
    const counts = new Map();
    for (const run of runs) {
      const ts = parseIso(run.started_at || run.created_at)?.getTime();
      if (!ts || ts < weekAgo) {
        continue;
      }
      const taskId = String(run.task_id || "");
      const key = taskTitleById.get(taskId) || taskId || "Unknown";
      counts.set(key, (counts.get(key) || 0) + 1);
    }
    const rows = [...counts.entries()]
      .map(([name, count]) => ({ name, count }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 3);
    const total = rows.reduce((sum, row) => sum + row.count, 0) || 1;
    return rows.map((row) => ({ ...row, percent: Math.round((row.count / total) * 100) }));
  }, [runs, taskTitleById]);

  const upcomingScheduleRows = useMemo(() => {
    const rows = [...schedules]
      .filter((schedule) => parseIso(schedule.next_run_at))
      .sort((a, b) => {
        const aTs = parseIso(a.next_run_at)?.getTime() || Number.MAX_SAFE_INTEGER;
        const bTs = parseIso(b.next_run_at)?.getTime() || Number.MAX_SAFE_INTEGER;
        return aTs - bTs;
      })
      .slice(0, 3);

    return rows.map((schedule) => ({
      id: schedule.schedule_id,
      label: taskTitleById.get(schedule.task_id) || schedule.task_id || schedule.name || "Scheduled task",
      nextRun: formatDateTime(schedule.next_run_at),
    }));
  }, [schedules, taskTitleById]);

  const overviewTotals = useMemo(() => {
    const liveTotals = overviewMetrics?.totals || {};
    return {
      recipes: liveTotals.recipes ?? 0,
      ingredients: liveTotals.ingredients ?? 0,
      categories: liveTotals.categories ?? taxonomyCounts.categories ?? 0,
      tags: liveTotals.tags ?? taxonomyCounts.tags ?? 0,
      tools: liveTotals.tools ?? taxonomyCounts.tools ?? 0,
      cookbooks: liveTotals.cookbooks ?? taxonomyCounts.cookbooks ?? 0,
      labels: liveTotals.labels ?? taxonomyCounts.labels ?? 0,
      units: liveTotals.units ?? taxonomyCounts.units_aliases ?? 0,
    };
  }, [overviewMetrics, taxonomyCounts]);

  const overviewCoverage = useMemo(
    () => overviewMetrics?.coverage || { categories: 0, tags: 0, tools: 0 },
    [overviewMetrics]
  );

  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  const hasFailed = runStats.failed > 0;
  const needsConnectionSetup = !overviewMetrics?.ok && overviewMetrics?.reason?.includes("Set Mealie URL");
  const statusMsg = hasFailed
    ? `${runStats.failed} run${runStats.failed === 1 ? "" : "s"} failed recently.`
    : !overviewMetrics?.ok && overviewMetrics?.reason
    ? "Mealie is not connected."
    : "Your organizer is healthy and ready.";

  return (
    <section className="page-grid overview-grid">
      <article className="card tone-soft intro-card">
        <h3>{greeting}. {statusMsg}</h3>
        <div className="status-row">
          <span className="status-pill success">Queued {runStats.queued}</span>
          <span className="status-pill neutral">Scheduled {upcomingScheduleCount}</span>
          {runStats.failed > 0 && <span className="status-pill danger">Failed {runStats.failed}</span>}
        </div>
        {!overviewMetrics?.ok && overviewMetrics?.reason ? (
          <p className="muted tiny">{overviewMetrics.reason}</p>
        ) : null}
      </article>

      {needsConnectionSetup && (
        <p className="banner warning" role="alert">
          <span>
            <strong>Mealie connection not configured.</strong>{" "}
            Go to{" "}
            <button className="link-inline" onClick={() => navigateTo("settings")}>Settings</button>
            {" "}to add your Mealie URL and API key before running tasks.
          </span>
        </p>
      )}

      <section className="overview-stats">
        <article className="card stat-card">
          <p className="label">Runs Today</p>
          <p className="value">{runsTodayCount}</p>
        </article>
        <article className="card stat-card">
          <p className="label">Schedules</p>
          <p className="value">{schedules.length}</p>
        </article>
      </section>

      <div className="overview-left">
        <article className="card chart-panel">
          <h3>Coverage</h3>
          <div className="coverage-grid">
            <CoverageRing label="Categories" value={overviewCoverage.categories} />
            <CoverageRing label="Tags" value={overviewCoverage.tags} />
            <CoverageRing label="Tools" value={overviewCoverage.tools} />
            {qualityMetrics?.available && <>
              <CoverageRing label="Ingredients" value={qualityMetrics.dimension_coverage?.ingredients?.pct_have ?? 0} />
              <CoverageRing label="Cook Time" value={qualityMetrics.dimension_coverage?.time?.pct_have ?? 0} />
              <CoverageRing label="Yield" value={qualityMetrics.dimension_coverage?.yield?.pct_have ?? 0} />
            </>}
          </div>
        </article>

        <article className="card library-metrics">
          <h3>Library</h3>
          <div className="metric-grid">
            <article><span>Recipes</span><strong>{overviewTotals.recipes}</strong></article>
            <article><span>Ingredients</span><strong>{overviewTotals.ingredients}</strong></article>
            <article><span>Tools</span><strong>{overviewTotals.tools}</strong></article>
            <article><span>Categories</span><strong>{overviewTotals.categories}</strong></article>
            <article><span>Cookbooks</span><strong>{overviewTotals.cookbooks}</strong></article>
            <article><span>Tags</span><strong>{overviewTotals.tags}</strong></article>
            <article><span>Labels</span><strong>{overviewTotals.labels}</strong></article>
            <article><span>Units</span><strong>{overviewTotals.units}</strong></article>
          </div>
          {!overviewMetrics?.ok && overviewMetrics?.reason ? (
            <p className="banner error"><span>{overviewMetrics.reason}</span></p>
          ) : null}
        </article>
      </div>

      <div className="overview-right">
        <article className="card medallion-card">
          <h3>Recipe Quality</h3>
          {qualityMetrics?.available ? (() => {
            const { total, gold, silver, bronze, gold_pct, dimension_coverage } = qualityMetrics;
            const tier = gold_pct >= 80 ? "gold" : gold_pct >= 50 ? "silver" : "bronze";
            const DIMS = ["category", "tags", "tools", "ingredients", "time", "yield"];
            const DIM_LABELS = { category: "Category", tags: "Tags", tools: "Tools", ingredients: "Ingredients", time: "Cook Time", yield: "Yield" };
            return (
              <div className="medallion-body">
                <div className={`medallion-badge medallion-${tier}`}>
                  <span className="medallion-icon">{tier === "gold" ? "\u{1F947}" : tier === "silver" ? "\u{1F948}" : "\u{1F949}"}</span>
                  <span className="medallion-tier">{tier.charAt(0).toUpperCase() + tier.slice(1)}</span>
                  <span className="medallion-pct">{gold_pct}% gold</span>
                </div>
                <div className="medallion-tiers">
                  <span className="medallion-tier-row gold-row"><strong>{gold}</strong> gold</span>
                  <span className="medallion-tier-row silver-row"><strong>{silver}</strong> silver</span>
                  <span className="medallion-tier-row bronze-row"><strong>{bronze}</strong> bronze</span>
                </div>
                <div className="medallion-dims">
                  {DIMS.map((dim) => {
                    const d = dimension_coverage?.[dim];
                    const pct = d?.pct_have ?? 0;
                    return (
                      <div key={dim} className="dim-row">
                        <span className="dim-label">{DIM_LABELS[dim]}</span>
                        <div className="dim-bar-track">
                          <div className="dim-bar-fill" style={{ width: `${pct}%` }} />
                        </div>
                        <span className="dim-pct">{pct}%</span>
                      </div>
                    );
                  })}
                </div>
                <p className="muted tiny">{total} recipes scored</p>
              </div>
            );
          })() : (
            <div className="medallion-empty">
              <p className="muted">No quality audit data yet.</p>
              <button
                className="ghost small"
                onClick={() => onTaskHandoff("health-check")}
              >
                Run Quality Audit &rarr;
              </button>
            </div>
          )}
        </article>

        <article className="card quick-view">
          <h3>Activity</h3>
          <ul className="kv-list">
            <li>
              <span>Upcoming schedules (24h)</span>
              <strong>{upcomingScheduleCount}</strong>
            </li>
            <li>
              <span>Queued runs</span>
              <strong>{runStats.queued}</strong>
            </li>
            <li>
              <span>Last failure</span>
              <strong>{latestFailureLabel}</strong>
            </li>
          </ul>

          <div className="top-usage">
            <h4>Task Mix This Week</h4>
            <ul>
              {taskMixRows.map((item) => (
                <li key={`taskmix-${item.name}`}>
                  <span>{item.name}</span>
                  <span>{item.percent}%</span>
                </li>
              ))}
              {taskMixRows.length === 0 ? <li className="muted">No runs in the last seven days.</li> : null}
            </ul>

            <h4>Next Scheduled Jobs</h4>
            <ul>
              {upcomingScheduleRows.map((item) => (
                <li key={`next-${item.id}`}>
                  <span>{item.nextRun}</span>
                  <span>{item.label}</span>
                </li>
              ))}
              {upcomingScheduleRows.length === 0 ? <li className="muted">No scheduled jobs in the queue.</li> : null}
            </ul>
          </div>
        </article>
      </div>
    </section>
  );
}
