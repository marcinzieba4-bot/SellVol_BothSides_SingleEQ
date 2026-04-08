#!/usr/bin/env python3
"""
Generate risk stats table + cumulative PnL chart for
sell_put_1m vs buy_call_1m (1M momentum, portfolio-level recovery).

Reads:  portfolio_sell_put_1m.csv  /  portfolio_buy_call_1m.csv
Writes: pnl_chart.png
"""

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
from matplotlib.ticker import FuncFormatter
import warnings
warnings.filterwarnings("ignore")

RF_ANNUAL = 0.04          # 4 % annual risk-free rate
RF_MONTHLY = RF_ANNUAL / 12


# ── Risk stats ────────────────────────────────────────────────────────────────

def compute_stats(port: pd.DataFrame) -> dict:
    r = port["monthly_return_pct"].values / 100.0
    n = len(r)
    ann_ret  = (1 + r).prod() ** (12 / n) - 1
    ann_vol  = r.std(ddof=1) * np.sqrt(12)
    sharpe   = (ann_ret - RF_ANNUAL) / ann_vol if ann_vol else np.nan
    excess   = r - RF_MONTHLY
    downside = excess[excess < 0]
    down_vol = downside.std(ddof=1) * np.sqrt(12) if len(downside) > 1 else np.nan
    sortino  = (ann_ret - RF_ANNUAL) / down_vol if down_vol else np.nan

    cum      = (1 + r).cumprod()
    roll_max = np.maximum.accumulate(cum)
    dd       = (cum - roll_max) / roll_max
    max_dd   = dd.min()
    calmar   = ann_ret / abs(max_dd) if max_dd else np.nan

    var95    = np.percentile(r, 5)
    var99    = np.percentile(r, 1)
    cvar95   = r[r <= var95].mean() if (r <= var95).any() else var95

    return {
        "n_months":        n,
        "ann_return_pct":  ann_ret  * 100,
        "ann_vol_pct":     ann_vol  * 100,
        "sharpe":          sharpe,
        "sortino":         sortino,
        "max_dd_pct":      max_dd   * 100,
        "calmar":          calmar,
        "var95_pct":       var95    * 100,
        "var99_pct":       var99    * 100,
        "cvar95_pct":      cvar95   * 100,
        "win_rate_pct":    (r > 0).mean() * 100,
        "best_month_pct":  r.max()  * 100,
        "worst_month_pct": r.min()  * 100,
        "total_return_pct": (cum[-1] - 1) * 100,
    }


# ── Load data ─────────────────────────────────────────────────────────────────

sp = pd.read_csv("portfolio_sell_put_1m.csv", parse_dates=["date"])
bc = pd.read_csv("portfolio_buy_call_1m.csv", parse_dates=["date"])

sp_stats = compute_stats(sp)
bc_stats = compute_stats(bc)

# ── Print stats side-by-side ──────────────────────────────────────────────────

ROWS = [
    ("Months",          "n_months",        "{:.0f}",  ""),
    ("Total return",    "total_return_pct","{:.2f}",  "%"),
    ("Ann. return",     "ann_return_pct",  "{:.2f}",  "%"),
    ("Ann. volatility", "ann_vol_pct",     "{:.2f}",  "%"),
    ("Sharpe (4% RF)",  "sharpe",          "{:.3f}",  ""),
    ("Sortino (4% RF)", "sortino",         "{:.3f}",  ""),
    ("Max drawdown",    "max_dd_pct",      "{:.2f}",  "%"),
    ("Calmar",          "calmar",          "{:.3f}",  ""),
    ("VaR 95%",         "var95_pct",       "{:.2f}",  "%"),
    ("VaR 99%",         "var99_pct",       "{:.2f}",  "%"),
    ("CVaR 95%",        "cvar95_pct",      "{:.2f}",  "%"),
    ("Win rate",        "win_rate_pct",    "{:.1f}",  "%"),
    ("Best month",      "best_month_pct",  "{:.2f}",  "%"),
    ("Worst month",     "worst_month_pct", "{:.2f}",  "%"),
]

w = 22
print()
print("=" * (w + 20))
print(f"{'METRIC':<{w}}  {'SELL PUT 1M':>12}  {'BUY CALL 1M':>12}")
print("=" * (w + 20))
for label, key, fmt, unit in ROWS:
    sv = fmt.format(sp_stats[key]) + unit
    bv = fmt.format(bc_stats[key]) + unit
    print(f"{label:<{w}}  {sv:>12}  {bv:>12}")
print("=" * (w + 20))
print()


# ── Chart ─────────────────────────────────────────────────────────────────────

fig = plt.figure(figsize=(14, 10))
fig.patch.set_facecolor("#0f0f0f")
gs = gridspec.GridSpec(3, 1, figure=fig, height_ratios=[3, 1, 1], hspace=0.08)

COLOR_SP  = "#00c8ff"   # cyan  — sell put
COLOR_BC  = "#ff9900"   # amber — buy call
COLOR_BG  = "#0f0f0f"
COLOR_AX  = "#1a1a2e"
COLOR_GRD = "#2a2a3e"
COLOR_TXT = "#e0e0e0"

def style_ax(ax):
    ax.set_facecolor(COLOR_AX)
    ax.tick_params(colors=COLOR_TXT, labelsize=9)
    ax.spines["bottom"].set_color(COLOR_GRD)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(COLOR_GRD)
    ax.yaxis.label.set_color(COLOR_TXT)
    ax.xaxis.label.set_color(COLOR_TXT)


# — cumulative return —
ax1 = fig.add_subplot(gs[0])
style_ax(ax1)

dates = sp["date"]
ax1.plot(dates, sp["cumulative_return_pct"], color=COLOR_SP, lw=1.8,
         label=f"Sell Put 1M  (Total {sp_stats['total_return_pct']:.1f}%)")
ax1.plot(dates, bc["cumulative_return_pct"], color=COLOR_BC, lw=1.8,
         label=f"Buy Call 1M  (Total {bc_stats['total_return_pct']:.1f}%)")
ax1.axhline(0, color="#555", lw=0.7, ls="--")
ax1.fill_between(dates, sp["cumulative_return_pct"], 0,
                 where=(sp["cumulative_return_pct"] >= 0),
                 alpha=0.08, color=COLOR_SP)
ax1.fill_between(dates, sp["cumulative_return_pct"], 0,
                 where=(sp["cumulative_return_pct"] < 0),
                 alpha=0.12, color="#ff4444")

ax1.set_ylabel("Cumulative Return %", color=COLOR_TXT, fontsize=10)
ax1.legend(facecolor="#1a1a2e", edgecolor=COLOR_GRD, labelcolor=COLOR_TXT,
           fontsize=9, loc="upper left")
ax1.set_title(
    "Sell Put vs Buy Call  |  1M Momentum  |  Portfolio-Level 2× Recovery Sizing\n"
    f"  Sell Put: Sharpe {sp_stats['sharpe']:.2f}  Calmar {sp_stats['calmar']:.2f}  "
    f"MaxDD {sp_stats['max_dd_pct']:.1f}%     "
    f"Buy Call: Sharpe {bc_stats['sharpe']:.2f}  Calmar {bc_stats['calmar']:.2f}  "
    f"MaxDD {bc_stats['max_dd_pct']:.1f}%",
    color=COLOR_TXT, fontsize=10, pad=8,
)
ax1.set_xticklabels([])
ax1.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:.0f}%"))
ax1.grid(True, color=COLOR_GRD, lw=0.5, alpha=0.6)

# — monthly returns bar chart (sell put) —
ax2 = fig.add_subplot(gs[1], sharex=ax1)
style_ax(ax2)
colors_sp = [COLOR_SP if v >= 0 else "#ff4444" for v in sp["monthly_return_pct"]]
ax2.bar(dates, sp["monthly_return_pct"], color=colors_sp, width=20, alpha=0.9)
ax2.axhline(0, color="#555", lw=0.7)
ax2.set_ylabel("Monthly %", color=COLOR_TXT, fontsize=9)
ax2.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:.0f}%"))
ax2.grid(True, axis="y", color=COLOR_GRD, lw=0.5, alpha=0.6)
sp_patch = mpatches.Patch(color=COLOR_SP, label="Sell Put 1M monthly")
ax2.legend(handles=[sp_patch], facecolor="#1a1a2e", edgecolor=COLOR_GRD,
           labelcolor=COLOR_TXT, fontsize=8, loc="upper left")
ax2.set_xticklabels([])

# — monthly returns bar chart (buy call) —
ax3 = fig.add_subplot(gs[2], sharex=ax1)
style_ax(ax3)
colors_bc = [COLOR_BC if v >= 0 else "#ff4444" for v in bc["monthly_return_pct"]]
ax3.bar(dates, bc["monthly_return_pct"], color=colors_bc, width=20, alpha=0.9)
ax3.axhline(0, color="#555", lw=0.7)
ax3.set_ylabel("Monthly %", color=COLOR_TXT, fontsize=9)
ax3.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:.0f}%"))
ax3.grid(True, axis="y", color=COLOR_GRD, lw=0.5, alpha=0.6)
bc_patch = mpatches.Patch(color=COLOR_BC, label="Buy Call 1M monthly")
ax3.legend(handles=[bc_patch], facecolor="#1a1a2e", edgecolor=COLOR_GRD,
           labelcolor=COLOR_TXT, fontsize=8, loc="upper left")
ax3.tick_params(axis="x", rotation=30)

# — risk stats box (right side) —
stats_text = (
    f"{'':─<28}\n"
    f"  {'':22}{'SELL PUT':>10}  {'BUY CALL':>10}\n"
    f"  {'Ann. Return':22}{'':>10}  {'':>10}\n"
    f"  {'':22}{sp_stats['ann_return_pct']:>9.1f}%  {bc_stats['ann_return_pct']:>9.1f}%\n"
    f"  {'Ann. Vol':22}{sp_stats['ann_vol_pct']:>9.1f}%  {bc_stats['ann_vol_pct']:>9.1f}%\n"
    f"  {'Sharpe':22}{sp_stats['sharpe']:>10.2f}  {bc_stats['sharpe']:>10.2f}\n"
    f"  {'Sortino':22}{sp_stats['sortino']:>10.2f}  {bc_stats['sortino']:>10.2f}\n"
    f"  {'Max DD':22}{sp_stats['max_dd_pct']:>9.1f}%  {bc_stats['max_dd_pct']:>9.1f}%\n"
    f"  {'Calmar':22}{sp_stats['calmar']:>10.2f}  {bc_stats['calmar']:>10.2f}\n"
    f"  {'Win Rate':22}{sp_stats['win_rate_pct']:>9.1f}%  {bc_stats['win_rate_pct']:>9.1f}%\n"
    f"  {'Best Month':22}{sp_stats['best_month_pct']:>9.1f}%  {bc_stats['best_month_pct']:>9.1f}%\n"
    f"  {'Worst Month':22}{sp_stats['worst_month_pct']:>9.1f}%  {bc_stats['worst_month_pct']:>9.1f}%\n"
    f"{'':─<28}"
)

fig.text(0.015, 0.01, stats_text,
         fontfamily="monospace", fontsize=7.5, color=COLOR_TXT,
         verticalalignment="bottom",
         bbox=dict(boxstyle="round,pad=0.5", facecolor="#1a1a2e",
                   edgecolor=COLOR_GRD, alpha=0.9))

plt.savefig("pnl_chart.png", dpi=150, bbox_inches="tight",
            facecolor=COLOR_BG)
print("Chart saved → pnl_chart.png")
