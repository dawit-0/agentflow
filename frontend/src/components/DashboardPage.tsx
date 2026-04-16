import React, { useCallback, useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  AnalyticsSummary,
  DayBucket,
  DurationBucket,
  RecentFailure,
  TopFailingTask,
  api,
} from "../api";
import StatCard from "./StatCard";

type Range = "24h" | "7d" | "30d";

const RANGES: { value: Range; label: string; days: number }[] = [
  { value: "24h", label: "Last 24 hours", days: 1 },
  { value: "7d", label: "Last 7 days", days: 7 },
  { value: "30d", label: "Last 30 days", days: 30 },
];

function sinceFor(range: Range): string {
  const days = RANGES.find((r) => r.value === range)?.days ?? 30;
  const d = new Date(Date.now() - days * 24 * 60 * 60 * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${pad(
    d.getUTCHours()
  )}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`;
}

function formatDuration(ms: number): string {
  if (!ms) return "0s";
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  if (ms < 3_600_000) return `${(ms / 60_000).toFixed(1)}m`;
  return `${(ms / 3_600_000).toFixed(1)}h`;
}

function formatCost(usd: number): string {
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  if (usd < 1) return `$${usd.toFixed(3)}`;
  return `$${usd.toFixed(2)}`;
}

interface Props {
  onSelectTask?: (taskId: string) => void;
}

export default function DashboardPage({ onSelectTask }: Props) {
  const [range, setRange] = useState<Range>("7d");
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [daily, setDaily] = useState<DayBucket[]>([]);
  const [topFails, setTopFails] = useState<TopFailingTask[]>([]);
  const [hist, setHist] = useState<DurationBucket[]>([]);
  const [recent, setRecent] = useState<RecentFailure[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    const since = sinceFor(range);
    try {
      const [s, d, tf, h, rf] = await Promise.all([
        api.analytics.summary(since),
        api.analytics.runsByDay(since),
        api.analytics.topFailures(since, 10),
        api.analytics.durationHistogram(since),
        api.analytics.recentFailures(20),
      ]);
      setSummary(s);
      setDaily(d);
      setTopFails(tf);
      setHist(h);
      setRecent(rf);
    } catch (e) {
      setError("Failed to load analytics");
    } finally {
      setLoading(false);
    }
  }, [range]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="dashboard-page">
      <div className="dashboard-header">
        <div>
          <h2>Observability</h2>
          <p className="dashboard-subtitle">
            Aggregated metrics over your task runs.
          </p>
        </div>
        <div className="dashboard-controls">
          <select
            className="dashboard-range"
            value={range}
            onChange={(e) => setRange(e.target.value as Range)}
          >
            {RANGES.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
          <button className="btn btn-sm" onClick={load} disabled={loading}>
            {loading ? "Loading..." : "Refresh"}
          </button>
        </div>
      </div>

      {error && <div className="dashboard-error">{error}</div>}

      <div className="stat-card-grid">
        <StatCard
          label="Total runs"
          value={summary?.total_runs ?? 0}
          hint={
            summary
              ? `${summary.success_count} success / ${summary.failed_count} failed`
              : ""
          }
        />
        <StatCard
          label="Success rate"
          value={summary ? `${Math.round(summary.success_rate * 100)}%` : "0%"}
          tone={
            summary && summary.success_rate >= 0.9
              ? "success"
              : summary && summary.success_rate < 0.7
              ? "danger"
              : "default"
          }
        />
        <StatCard
          label="Total spend"
          value={summary ? formatCost(summary.total_cost_usd) : "$0"}
        />
        <StatCard
          label="p95 duration"
          value={summary ? formatDuration(summary.p95_duration_ms) : "0s"}
          hint={
            summary ? `p50 ${formatDuration(summary.p50_duration_ms)}` : ""
          }
        />
      </div>

      <div className="dashboard-grid">
        <div className="dashboard-card">
          <h3>Runs per day</h3>
          <div className="chart-container">
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={daily}>
                <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
                <XAxis dataKey="date" stroke="var(--text-secondary)" fontSize={11} />
                <YAxis stroke="var(--text-secondary)" fontSize={11} allowDecimals={false} />
                <Tooltip
                  contentStyle={{
                    background: "var(--bg-secondary)",
                    border: "1px solid var(--border)",
                    borderRadius: 6,
                  }}
                  labelStyle={{ color: "var(--text-primary)" }}
                />
                <Legend />
                <Line
                  type="monotone"
                  dataKey="success"
                  stroke="var(--success)"
                  strokeWidth={2}
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="failed"
                  stroke="var(--danger)"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="dashboard-card">
          <h3>Spend per day</h3>
          <div className="chart-container">
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={daily}>
                <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
                <XAxis dataKey="date" stroke="var(--text-secondary)" fontSize={11} />
                <YAxis
                  stroke="var(--text-secondary)"
                  fontSize={11}
                  tickFormatter={(v) => `$${v.toFixed(2)}`}
                />
                <Tooltip
                  contentStyle={{
                    background: "var(--bg-secondary)",
                    border: "1px solid var(--border)",
                    borderRadius: 6,
                  }}
                  formatter={(v) => formatCost(Number(v ?? 0))}
                  labelStyle={{ color: "var(--text-primary)" }}
                />
                <Bar dataKey="cost_usd" fill="var(--accent)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="dashboard-card">
          <h3>Duration distribution</h3>
          <div className="chart-container">
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={hist}>
                <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
                <XAxis dataKey="bucket" stroke="var(--text-secondary)" fontSize={11} />
                <YAxis stroke="var(--text-secondary)" fontSize={11} allowDecimals={false} />
                <Tooltip
                  contentStyle={{
                    background: "var(--bg-secondary)",
                    border: "1px solid var(--border)",
                    borderRadius: 6,
                  }}
                  labelStyle={{ color: "var(--text-primary)" }}
                />
                <Bar dataKey="count" fill="var(--info)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="dashboard-card">
          <h3>Top failing tasks</h3>
          {topFails.length === 0 ? (
            <div className="dashboard-empty">No failures in this range.</div>
          ) : (
            <table className="dashboard-table">
              <thead>
                <tr>
                  <th>Task</th>
                  <th>Failures</th>
                  <th>Last</th>
                </tr>
              </thead>
              <tbody>
                {topFails.map((t) => (
                  <tr
                    key={t.task_id}
                    className={onSelectTask ? "clickable" : ""}
                    onClick={() => onSelectTask?.(t.task_id)}
                  >
                    <td>{t.title}</td>
                    <td>{t.failure_count}</td>
                    <td>{t.last_failure_at ? new Date(t.last_failure_at + "Z").toLocaleString() : "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      <div className="dashboard-card dashboard-card-wide">
        <h3>Recent failures</h3>
        {recent.length === 0 ? (
          <div className="dashboard-empty">No recent failures.</div>
        ) : (
          <table className="dashboard-table">
            <thead>
              <tr>
                <th>When</th>
                <th>Task</th>
                <th>Run #</th>
                <th>Duration</th>
                <th>Error</th>
              </tr>
            </thead>
            <tbody>
              {recent.map((r) => (
                <tr
                  key={r.run_id}
                  className={onSelectTask ? "clickable" : ""}
                  onClick={() => onSelectTask?.(r.task_id)}
                >
                  <td>{r.finished_at ? new Date(r.finished_at + "Z").toLocaleString() : "-"}</td>
                  <td>{r.task_title}</td>
                  <td>#{r.run_number}</td>
                  <td>{formatDuration(r.duration_ms)}</td>
                  <td className="dashboard-error-cell">{r.error_message || "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
