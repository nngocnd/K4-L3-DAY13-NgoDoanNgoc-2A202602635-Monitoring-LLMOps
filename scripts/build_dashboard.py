"""Render the six-panel dashboard from data/logs.jsonl following config/dashboard.yaml.

    python scripts/build_dashboard.py                 # render once
    python scripts/build_dashboard.py --watch         # re-render every refresh_seconds
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.cli import configure_utf8_stdio  # noqa: E402
from app.metrics import percentile  # noqa: E402
from scripts.validate_dashboard import load_dashboard_config  # noqa: E402

# Reference categorical palette (dataviz skill), fixed order; status red reserved for thresholds.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#4a3aa7"]
THRESHOLD = "#e34948"
INK, INK_MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
UNIT_LABELS = {
    "ms": "ms",
    "requests_per_minute": "requests / min",
    "percent": "%",
    "usd": "USD",
    "tokens": "tokens",
    "score_0_to_1": "score (0–1)",
}


def load_events(path: Path) -> list[dict]:
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if "ts" in record:
            record["_ts"] = datetime.fromisoformat(record["ts"].replace("Z", "+00:00"))
            events.append(record)
    return events


def by_minute(events: list[dict]) -> dict[datetime, list[dict]]:
    buckets: dict[datetime, list[dict]] = defaultdict(list)
    for e in events:
        buckets[e["_ts"].replace(second=0, microsecond=0)].append(e)
    return dict(sorted(buckets.items()))


def threshold_line(ax, panel: dict, label_suffix: str = "") -> None:
    t = panel["threshold"]
    op = "≤" if t["operator"] == "lte" else "≥"
    bottom, top = ax.get_ylim()
    if top < t["value"] * 1.15:
        ax.set_ylim(bottom, t["value"] * 1.15)
    ax.axhline(t["value"], color=THRESHOLD, linestyle="--", linewidth=1.5, zorder=1)
    ax.annotate(
        f"SLO {t['aggregation']} {op} {t['value']:g}{label_suffix}",
        xy=(1, t["value"]), xycoords=("axes fraction", "data"),
        xytext=(-4, 4), textcoords="offset points", ha="right", va="bottom",
        fontsize=8, color=INK_MUTED,
    )


def style_axis(ax, panel: dict, subtitle: str, start: datetime, end: datetime) -> None:
    ax.set_title(f"{panel['title']}\n", loc="left", fontsize=11, fontweight="bold", color=INK)
    ax.text(0, 1.02, subtitle, transform=ax.transAxes, fontsize=8.5, color=INK_MUTED)
    ax.set_ylabel(UNIT_LABELS.get(panel["unit"], panel["unit"]), color=INK_MUTED, fontsize=9)
    ax.set_xlim(start, end)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.xaxis.set_major_locator(mdates.MinuteLocator(byminute=range(0, 60, 10)))
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK_MUTED, labelsize=8)
    ax.set_ylim(bottom=0)


def line(ax, xs, ys, color, label) -> None:
    # Break the line across idle gaps so it does not imply data between runs.
    gx, gy = [], []
    for i, (x, y) in enumerate(zip(xs, ys)):
        if i and (x - xs[i - 1]) > timedelta(minutes=2):
            gx.append(x - timedelta(seconds=1))
            gy.append(float("nan"))
        gx.append(x)
        gy.append(y)
    xs, ys = gx, gy
    ax.plot(xs, ys, color=color, linewidth=2, marker="o", markersize=4, label=label, zorder=3)


def render(config_path: Path, logs_path: Path, out_path: Path) -> dict:
    dashboard = load_dashboard_config(config_path)["dashboard"]
    panels = {p["id"]: p for p in dashboard["panels"]}
    events = load_events(logs_path)
    end = max((e["_ts"] for e in events), default=datetime.now(timezone.utc)) + timedelta(minutes=1)
    start = end - timedelta(minutes=dashboard["time_range_minutes"])
    events = [e for e in events if start <= e["_ts"] <= end]

    received = [e for e in events if e.get("event") == "request_received"]
    sent = [e for e in events if e.get("event") == "response_sent"]
    failed = [e for e in events if e.get("event") == "request_failed"]
    sent_min = by_minute(sent)

    fig, axes = plt.subplots(3, 2, figsize=(15, 12.5), facecolor=SURFACE)
    fig.suptitle(
        f"{dashboard['title']}   ·   Time range: last {dashboard['time_range_minutes']} min "
        f"({start:%Y-%m-%d %H:%M}–{end:%H:%M} UTC)   ·   refresh {dashboard['refresh_seconds']}s   ·   source: {logs_path.as_posix().split('/')[-2]}/{logs_path.name}",
        x=0.01, ha="left", fontsize=12, fontweight="bold", color=INK,
    )
    summary: dict = {}

    # 1. Latency
    ax, panel = axes[0][0], panels["latency"]
    xs = list(sent_min)
    for p, color in zip((50, 95, 99), SERIES):
        line(ax, xs, [percentile([e["latency_ms"] for e in sent_min[x]], p) for x in xs], color, f"latency P{p}")
    line(ax, xs, [percentile([e["ttft_ms"] for e in sent_min[x]], 95) for x in xs], SERIES[3], "TTFT P95")
    lat = [e["latency_ms"] for e in sent]
    ttft = [e["ttft_ms"] for e in sent]
    summary["latency"] = {f"p{p}": percentile(lat, p) for p in (50, 95, 99)} | {"ttft_p95": percentile(ttft, 95)}
    s = summary["latency"]
    style_axis(ax, panel, f"Window: P50 {s['p50']:.0f} · P95 {s['p95']:.0f} · P99 {s['p99']:.0f} · TTFT P95 {s['ttft_p95']:.0f} ms", start, end)
    threshold_line(ax, panel, " ms")
    ax.legend(fontsize=8, frameon=False, loc="upper left", ncol=4)

    # 2. Traffic
    ax, panel = axes[0][1], panels["traffic"]
    rec_min = by_minute(received)
    ax.bar(list(rec_min), [len(v) for v in rec_min.values()], width=40 / 86400, color=SERIES[0], zorder=3)
    active = len(rec_min) or 1
    summary["traffic"] = {"count": len(received), "rate_per_active_minute": round(len(received) / active, 1)}
    style_axis(ax, panel, f"Window: {len(received)} requests · avg {summary['traffic']['rate_per_active_minute']} req/min over active minutes", start, end)
    threshold_line(ax, panel, " req/min")

    # 3. Errors + retrieval success
    ax, panel = axes[1][0], panels["errors"]
    fail_min = by_minute(failed)
    xs = list(rec_min)
    err_rate = [len(fail_min.get(x, [])) / len(rec_min[x]) * 100 for x in xs]
    tool_events = [e for e in events if e.get("tool_success") is not None]
    tool_min = by_minute(tool_events)
    succ = [sum(e["tool_success"] is True for e in tool_min[x]) / len(tool_min[x]) * 100 for x in tool_min]
    line(ax, xs, err_rate, SERIES[1], "error rate %")
    line(ax, list(tool_min), succ, SERIES[2], "retrieval success %")
    breakdown = Counter(e.get("error_type") for e in failed)
    total_err = len(failed) / len(received) * 100 if received else 0.0
    total_succ = sum(e["tool_success"] is True for e in tool_events) / len(tool_events) * 100 if tool_events else 0.0
    summary["errors"] = {"error_rate_pct": round(total_err, 2), "breakdown": dict(breakdown), "retrieval_success_pct": round(total_succ, 2)}
    bd = ", ".join(f"{k}={v}" for k, v in breakdown.items()) or "none"
    style_axis(ax, panel, f"Window: error rate {total_err:.2f}% · by type: {bd} · retrieval success {total_succ:.1f}%", start, end)
    ax.set_ylim(0, 105)
    threshold_line(ax, panel, " %")
    ax.legend(fontsize=8, frameon=False, loc="center left")

    # 4. Cost
    ax, panel = axes[1][1], panels["cost"]
    xs = list(sent_min)
    per_min = [sum(e["cost_usd"] for e in sent_min[x]) for x in xs]
    cumulative, running = [], 0.0
    for v in per_min:
        running += v
        cumulative.append(running)
    ax.bar(xs, per_min, width=40 / 86400, color=SERIES[0], label="cost per minute", zorder=3)
    line(ax, xs, cumulative, SERIES[1], "cumulative total")
    summary["cost"] = {"total_usd": round(running, 4), "max_per_minute_usd": round(max(per_min, default=0), 4)}
    style_axis(ax, panel, f"Window: total {running:.4f} USD · peak {summary['cost']['max_per_minute_usd']:.4f} USD/min", start, end)
    ax.set_yscale("symlog", linthresh=0.01)
    threshold_line(ax, panel, " USD")
    ax.set_ylabel("USD (symlog)", color=INK_MUTED, fontsize=9)
    ax.legend(fontsize=8, frameon=False, loc="upper left")

    # 5. Tokens
    ax, panel = axes[2][0], panels["tokens"]
    for field, color in (("tokens_in", SERIES[0]), ("tokens_out", SERIES[1])):
        running, ys = 0, []
        for x in xs:
            running += sum(e[field] for e in sent_min[x])
            ys.append(running)
        line(ax, xs, ys, color, f"cumulative {field}")
        summary.setdefault("tokens", {})[field] = running
    t = summary["tokens"]
    style_axis(ax, panel, f"Window: input {t['tokens_in']:,} · output {t['tokens_out']:,} tokens", start, end)
    ax.set_yscale("symlog", linthresh=1000)
    threshold_line(ax, panel, " per field")
    ax.set_ylabel("tokens (symlog)", color=INK_MUTED, fontsize=9)
    ax.legend(fontsize=8, frameon=False, loc="upper left")

    # 6. Quality
    ax, panel = axes[2][1], panels["quality"]
    line(ax, xs, [sum(e["quality_score"] for e in sent_min[x]) / len(sent_min[x]) for x in xs], SERIES[0], "mean quality_score")
    q = sum(e["quality_score"] for e in sent) / len(sent) if sent else 0.0
    summary["quality"] = {"mean": round(q, 3)}
    style_axis(ax, panel, f"Window: mean quality {q:.3f} over {len(sent)} responses", start, end)
    ax.set_ylim(0, 1.05)
    threshold_line(ax, panel)

    fig.tight_layout(rect=(0, 0, 1, 0.96), h_pad=3)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=110, facecolor=SURFACE)
    plt.close(fig)
    return summary


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Render the Day 13 dashboard")
    parser.add_argument("--config", type=Path, default=REPO_ROOT / "config" / "dashboard.yaml")
    parser.add_argument("--logs", type=Path, default=REPO_ROOT / "data" / "logs.jsonl")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "submission" / "evidence" / "11-dashboard-overview.png")
    parser.add_argument("--watch", action="store_true", help="Re-render every refresh_seconds")
    args = parser.parse_args()

    while True:
        summary = render(args.config, args.logs, args.out)
        print(json.dumps(summary, ensure_ascii=False))
        print(f"Đã ghi dashboard: {args.out}")
        if not args.watch:
            return 0
        time.sleep(load_dashboard_config(args.config)["dashboard"]["refresh_seconds"])


if __name__ == "__main__":
    raise SystemExit(main())
