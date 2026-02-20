import React from "react";

export default function CoverageRing({ label, value, helper, detail, tone = "accent" }) {
  const percent = Math.max(0, Math.min(100, Number(value) || 0));
  const degree = Math.round((percent / 100) * 360);

  return (
    <div className="coverage-card">
      <div
        className={`coverage-ring tone-${tone}`}
        style={{ background: `conic-gradient(var(--tone-color) ${degree}deg, var(--line-soft) ${degree}deg)` }}
      >
        <span>{percent}%</span>
      </div>
      <h4>{label}</h4>
      <p>{helper}</p>
      {detail ? <p className="tiny muted">{detail}</p> : null}
    </div>
  );
}
