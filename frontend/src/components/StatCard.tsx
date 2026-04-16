import React from "react";

interface Props {
  label: string;
  value: string | number;
  hint?: string;
  tone?: "default" | "success" | "danger" | "warning";
}

export default function StatCard({ label, value, hint, tone = "default" }: Props) {
  return (
    <div className={`stat-card stat-card-${tone}`}>
      <div className="stat-card-label">{label}</div>
      <div className="stat-card-value">{value}</div>
      {hint && <div className="stat-card-hint">{hint}</div>}
    </div>
  );
}
