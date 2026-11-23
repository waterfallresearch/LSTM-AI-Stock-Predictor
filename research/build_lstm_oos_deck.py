"""Build the 16:9 PDF deck on the old LSTM rule: 2016-2024 development record and the 2025-2026 out-of-sample run.

    python research/build_lstm_oos_deck.py          -> research/lstm_old_rule_oos_deck.pdf

Every number is read from saved artifacts (development ledgers in wf_pit/, out-of-sample results in
wf_pit_unsealed_2025_2026/); nothing is typed in by hand except the study facts cited from research/*.md.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "wf_pit" / "model_comparison" / "rule_attribution"
OOS = ROOT / "wf_pit_unsealed_2025_2026"
SPY = ROOT / "TrainingData" / "indicators_data" / "pit" / "spy_pit.csv"
OUTFILE = ROOT / "research" / "lstm_old_rule_oos_deck.pdf"

# Validated default palette (light): slots 1-3 in fixed order; control also dashed (secondary encoding).
C = {"rule": "#2a78d6", "spy": "#eb6834", "control": "#1baf7a"}
INK, INK2, MUTED, GRID, SURF = "#0b0b0b", "#52514e", "#8a8984", "#e4e3df", "#fcfcfb"
BAD, GOOD = "#d03b3b", "#0ca30c"
NAMES = {"rule": "LSTM old rule (p − σ > 0.25)", "spy": "SPY total return", "control": "LSTM raw top-decile"}
W, H = 13.333, 7.5

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 13, "text.color": INK, "axes.labelcolor": INK2,
    "axes.edgecolor": GRID, "xtick.color": INK2, "ytick.color": INK2, "axes.facecolor": SURF,
    "figure.facecolor": SURF, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
})


# ----------------------------------------------------------------------------- data

def stats(eq: np.ndarray) -> dict:
    r = eq[1:] / eq[:-1] - 1
    peak = np.maximum.accumulate(eq)
    return {"total": eq[-1] / eq[0] - 1, "cagr": (eq[-1] / eq[0]) ** (252 / (len(eq) - 1)) - 1,
            "sharpe": np.sqrt(252) * r.mean() / r.std(ddof=1), "mdd": float((eq / peak - 1).min())}


def dev_data() -> pd.DataFrame:
    rule = pd.read_csv(DEV / "restored_equity.csv", parse_dates=["Date"]).set_index("Date").net
    ctrl = pd.read_csv(DEV / "control_equity.csv", parse_dates=["Date"]).set_index("Date").net
    spy = pd.read_csv(SPY, parse_dates=["session"]).set_index("session").tr_index.reindex(rule.index).ffill()
    return pd.DataFrame({"rule": rule, "control": ctrl, "spy": spy / spy.iloc[0] * rule.iloc[0]})


def oos_data():
    if not (OOS / "results.json").exists():
        return None, None
    res = json.loads((OOS / "results.json").read_text())
    eq = pd.read_csv(OOS / "equity.csv", parse_dates=["Date"]).set_index("Date")
    eq = eq.rename(columns={"restored": "rule", "spy_tr": "spy"})[["rule", "control", "spy"]]
    return res, eq


# ----------------------------------------------------------------------------- slide helpers

def slide(title: str, kicker: str | None = None):
    fig = plt.figure(figsize=(W, H))
    fig.text(0.05, 0.92, title, fontsize=26, weight="bold", color=INK, va="top")
    if kicker:
        fig.text(0.05, 0.835, kicker, fontsize=14.5, color=INK2, va="top", wrap=True)
    return fig


def footer(fig, n: int, source: str):
    fig.text(0.05, 0.035, source, fontsize=9.5, color=MUTED)
    fig.text(0.95, 0.035, str(n), fontsize=9.5, color=MUTED, ha="right")


def bullets(fig, items, x=0.05, y=0.74, size=15, gap=0.085, width=None):
    for item in items:
        head, _, tail = item.partition("|")
        fig.text(x, y, "•", fontsize=size, color=C["rule"], va="top")
        if tail:
            fig.text(x + 0.02, y, head, fontsize=size, weight="bold", va="top")
            fig.text(x + 0.02, y - 0.037, tail.strip(), fontsize=size - 2, color=INK2, va="top")
        else:
            fig.text(x + 0.02, y, head, fontsize=size, va="top")
        y -= gap


def table(fig, rect, header, rows, col_w=None, highlight_col=None, size=13):
    ax = fig.add_axes(rect)
    ax.axis("off")
    n = len(header)
    col_w = col_w or [1 / n] * n
    xs = np.cumsum([0] + col_w[:-1])
    row_h = 1 / (len(rows) + 1)
    for j, h in enumerate(header):
        ax.text(xs[j] + (0 if j == 0 else col_w[j]), 1 - row_h / 2, h, ha="left" if j == 0 else "right",
                va="center", fontsize=size - 1, color=INK2, weight="bold", transform=ax.transAxes)
    ax.plot([0, 1], [1 - row_h, 1 - row_h], color=INK2, lw=1, transform=ax.transAxes)
    for i, row in enumerate(rows):
        y = 1 - row_h * (i + 1.5)
        for j, v in enumerate(row):
            ax.text(xs[j] + (0 if j == 0 else col_w[j]), y, v, ha="left" if j == 0 else "right", va="center",
                    fontsize=size, color=INK, weight="bold" if (highlight_col is not None and j == highlight_col)
                    else "normal", transform=ax.transAxes)
        if i < len(rows) - 1:
            ax.plot([0, 1], [y - row_h / 2] * 2, color=GRID, lw=0.8, transform=ax.transAxes)
    return ax


def pct(x, signed=True):
    return f"{x * 100:+.1f}%" if signed else f"{x * 100:.1f}%"


def equity_chart(ax, df: pd.DataFrame, label_dx_days=12):
    base = df.iloc[0]
    idx = df / base * 100
    for key in ("spy", "control", "rule"):
        ax.plot(idx.index, idx[key], color=C[key], lw=2.2 if key == "rule" else 1.8,
                ls="--" if key == "control" else "-", solid_capstyle="round")
        last = idx[key].iloc[-1]
        ax.annotate(f"{NAMES[key].split(' (')[0]}  {last:.0f}", (idx.index[-1], last),
                    xytext=(8, 0), textcoords="offset points", va="center", fontsize=11.5, color=INK)
    ax.axhline(100, color=MUTED, lw=0.8)
    ax.set_ylabel("Growth of 100 (net of costs)")
    ax.margins(x=0)
    ax.spines["left"].set_visible(False)
    ax.tick_params(length=0)


def oos_summary(res) -> str:
    r, s = res["portfolios"]["restored"]["net"], res["spy_tr"]["net"]
    return (f"{pct(r['total_return'])} vs SPY {pct(s['total_return'])}, Sharpe {r['sharpe']:.2f} vs {s['sharpe']:.2f}, "
            f"paired lower bound {res['paired_sharpe']['spy_tr']['lower_95']:+.2f}")


# ----------------------------------------------------------------------------- slides

def s_title(pdf, res):
    fig = plt.figure(figsize=(W, H))
    fig.patches.append(plt.Rectangle((0, 0), 0.012, 1, transform=fig.transFigure, color=C["rule"]))
    fig.text(0.07, 0.66, "The old LSTM rule", fontsize=40, weight="bold")
    fig.text(0.07, 0.575, "Development record and out-of-sample test, 2016 – 2026", fontsize=22, color=INK2)
    if res:
        fig.text(0.07, 0.42, f"Out-of-sample verdict: {res['reading']}", fontsize=17, weight="bold",
                 color=GOOD if res["reading"].startswith("consistent") else BAD)
    fig.text(0.07, 0.36, "Point-in-time S&P 500 (survivorship-free) · next-open fills · full trading costs",
             fontsize=14, color=INK2)
    fig.text(0.07, 0.12, "Research only. Not investment advice.  ·  2026-11-23", fontsize=12, color=MUTED)
    pdf.savefig(fig); plt.close(fig)


def s_strategy(pdf, n):
    fig = slide("What the strategy does",
                "A Conv1D + LSTM network scores every S&P 500 member each day; a fixed rule turns scores into trades.")
    bullets(fig, [
        "Inputs|34 daily features from price and volume plus SPY context (momentum, volatility, RSI, MACD, gaps …)",
        "Forecast|Probability of an unusually large gain over 1 day, 1 week, 1 month and 6 months",
        "Uncertainty|25 Monte Carlo dropout passes × 3 training seeds give a mean p and a spread σ",
        "Rule|Buy when the best horizon's p − σ exceeds 0.25; hold up to 5 positions; exit at the horizon",
        "Execution|Signal at the close, fill at the next open; spread, square-root impact, SEC/FINRA fees, 5% ADV cap",
        "Comparators|SPY total return, and the same LSTM picking its raw top decile (no σ, no 0.25 cutoff)",
    ], gap=0.105)
    footer(fig, n, "Code: pit_walk_forward.py, pit_evaluate.py, backtest_core.py")
    pdf.savefig(fig); plt.close(fig)


def s_timeline(pdf, n):
    fig = slide("How it was tested",
                "Walk-forward: each year's model is trained only on data that ended at least 126 sessions earlier.")
    ax = fig.add_axes([0.05, 0.42, 0.9, 0.22])
    ax.axis("off")
    spans = [(2016, 2025.0, "Development  2016 – 2024\n9 yearly folds × 3 seeds · ~50 variants tried", "#cde2fb"),
             (2025.0, 2025.88, "A", "#fde0cf"),
             (2025.88, 2026.88, "B", "#e9e8e4")]
    for a, b, txt, col in spans:
        ax.add_patch(plt.Rectangle((a, 0.25), b - a - 0.02, 0.6, color=col))
        ax.text((a + b) / 2, 0.55, txt, ha="center", va="center", fontsize=12 if len(txt) > 1 else 16,
                weight="normal" if len(txt) > 1 else "bold")
    for y in range(2016, 2027):
        ax.text(y, 0.08, str(y), ha="center", fontsize=10, color=MUTED)
    ax.set_xlim(2015.9, 2027.0); ax.set_ylim(0, 1)
    ax.annotate("Unsealed 2026-11-23\nby owner decision", (2025.0, 0.88), xytext=(2023.0, 1.25),
                fontsize=11.5, color=BAD, arrowprops=dict(arrowstyle="-|>", color=BAD, lw=1.2),
                annotation_clip=False)
    fig.text(0.05, 0.36, "A  Reserved confirmation window, 2025-01-02 → 2025-11-18 (sealed until now)",
             fontsize=12, color=INK2)
    fig.text(0.05, 0.325, "B  2025-11-19 → 2026-11-18, used earlier by a different (pre-close) study",
             fontsize=12, color=INK2)
    bullets(fig, [
        "Out-of-sample test = 2025-01-02 → 2026-11-18|Frozen recipe, retrained for 2025 and 2026 folds; no settings changed",
        "Not a confirmation|The rule failed its 2016–2024 promotion gate, so this run can only describe, not promote",
    ], y=0.25, gap=0.09, size=14)
    footer(fig, n, "Preregistrations: research/pit_nextopen_2026-11-20_*, research/pit_lstm_unsealed_2025_2026_preregistration.md")
    pdf.savefig(fig); plt.close(fig)


def s_dev_curve(pdf, n, dev):
    st = {k: stats(dev[k].to_numpy()) for k in dev}
    fig = slide("Development 2016 – 2024: more return, more risk",
                f"CAGR {pct(st['rule']['cagr'], False)} vs SPY {pct(st['spy']['cagr'], False)}, but Sharpe "
                f"{st['rule']['sharpe']:.2f} vs {st['spy']['sharpe']:.2f} and a deeper drawdown.")
    ax = fig.add_axes([0.06, 0.13, 0.46, 0.64])
    equity_chart(ax, dev)
    ax.xaxis.set_major_locator(mdates.YearLocator(2)); ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    rows = [[NAMES[k].split(" (")[0], pct(st[k]["cagr"], False), f"{st[k]['sharpe']:.2f}", pct(st[k]["mdd"])]
            for k in ("rule", "spy", "control")]
    table(fig, [0.665, 0.42, 0.31, 0.3], ["", "CAGR", "Sharpe", "Max DD"], rows, col_w=[0.40, 0.19, 0.19, 0.22],
          size=12)
    fig.text(0.665, 0.36, "Net of costs, $1m start, 2016-01-04 → 2024-12-31", fontsize=10.5, color=MUTED)
    footer(fig, n, "Source: wf_pit/model_comparison/rule_attribution/*_equity.csv; SPY total-return index")
    pdf.savefig(fig); plt.close(fig)


def s_dev_years(pdf, n, dev):
    yr = dev.pct_change().groupby(dev.index.year).apply(lambda x: (1 + x.dropna()).prod() - 1)
    fig = slide("Year by year, the gains are uneven",
                "Flat-to-negative 2016–2018; most of the gain came in 2019, 2021 and 2024 on a five-stock book.")
    ax = fig.add_axes([0.06, 0.13, 0.88, 0.62])
    x = np.arange(len(yr))
    w = 0.38
    for off, key in ((-w / 2 - 0.01, "rule"), (w / 2 + 0.01, "spy")):
        vals = yr[key].to_numpy() * 100
        ax.bar(x + off, vals, width=w, color=C[key], label=NAMES[key])
        for xi, v in zip(x + off, vals):
            ax.text(xi, v + (1.5 if v >= 0 else -1.5), "0" if abs(v) < 0.5 else f"{v:+.0f}", ha="center", va="bottom" if v >= 0 else "top",
                    fontsize=10, color=INK2)
    ax.set_xticks(x, yr.index.astype(str)); ax.axhline(0, color=INK2, lw=1)
    ax.set_ylabel("Calendar-year return, %"); ax.tick_params(length=0); ax.spines["left"].set_visible(False)
    ax.legend(frameon=False, loc="upper left", fontsize=12)
    footer(fig, n, "Source: same ledgers as previous slide")
    pdf.savefig(fig); plt.close(fig)


def s_dev_caveats(pdf, n):
    fig = slide("Why the development record is not proof",
                "It beat its own raw version, but failed every check that guards against luck or fragility.")
    rows = [
        ["Deflated Sharpe at 50 trials", "0.35", "≥ 0.95", "Fail"],
        ["Sharpe vs SPY total return", "0.79 vs 0.85", "above SPY", "Fail"],
        ["Seed stability (3 separate seeds)", "0.70 / 0.10 / 0.46", "all ≥ raw control 0.30", "Fail"],
        ["σ flags worse forecasts", "−0.009 excess Brier", "> 0", "Fail"],
        ["Factor alpha (FF5 + momentum)", "+6.3% / yr, CI −4.5 … +17.0", "CI above 0", "Fail"],
        ["Gain over raw top-decile (paired)", "+0.49 Sharpe, lower bound +0.06", "> 0", "Pass"],
    ]
    ax = table(fig, [0.05, 0.16, 0.9, 0.58], ["Check", "Result", "Needed", ""], rows,
               col_w=[0.36, 0.3, 0.24, 0.1], size=13.5)
    for t in ax.texts:
        if t.get_text() in ("Pass", "Fail"):
            t.set_color(GOOD if t.get_text() == "Pass" else BAD)
            t.set_weight("bold")
    footer(fig, n, "Sources: research/pit_lstm_rule_attribution_results.md, pit_lstm_uncertainty_and_attribution_results.md, "
                   "pit_lstm_matched_uncertainty_results.md")
    pdf.savefig(fig); plt.close(fig)


def s_oos_setup(pdf, n, res):
    spec = json.loads((OOS / "feature_spec.json").read_text())
    p = spec["parity"]
    fig = slide("Out-of-sample setup: nothing re-tuned",
                "The 2025 and 2026 models were trained with the frozen code; only the calendar moved forward.")
    auc = res["fold_test_auc"] if res else {}
    auc_txt = ", ".join(f"{k.replace('_', ' ')}: {v['1m']:.3f}" for k, v in auc.items() if v.get("1m")) or "pending"
    bullets(fig, [
        f"Feature parity|{p['rows_both']:,} feature rows for 2011–2024 rebuilt and matched the frozen file exactly "
        + ("(zero difference)" if p["max_scaled_abs_diff"] == 0 else f"(max difference {p['max_scaled_abs_diff']:.1e})"),
        "Folds|2025 model trained to mid-2023, validated to mid-2024; 2026 model trained to mid-2024, validated to mid-2025",
        "Same rule|p − σ > 0.25, 5 slots, next-open fills, identical cost model and eligibility",
        f"Trial count|This run is trial 57 in the project's ledger",
        f"1-month AUC by fold and seed|{auc_txt}",
    ], gap=0.115, size=14.5)
    footer(fig, n, "Source: wf_pit_unsealed_2025_2026/feature_spec.json, results.json")
    pdf.savefig(fig); plt.close(fig)


def s_oos_curve(pdf, n, res, eq):
    p, s = res["portfolios"], res["spy_tr"]
    rule, spy = p["restored"]["net"], s["net"]
    fig = slide("Out-of-sample 2025-01-02 → 2026-11-18",
                f"Old rule {pct(rule['total_return'])} vs SPY {pct(spy['total_return'])}; "
                f"Sharpe {rule['sharpe']:.2f} vs {spy['sharpe']:.2f}; max drawdown {pct(rule['max_drawdown'])} "
                f"vs {pct(spy['max_drawdown'])}.")
    ax = fig.add_axes([0.06, 0.13, 0.72, 0.64])
    equity_chart(ax, eq)
    ax.axvline(pd.Timestamp("2025-11-18"), color=MUTED, lw=1, ls=":")
    ax.text(pd.Timestamp("2025-11-18"), ax.get_ylim()[1], " end of sealed window", fontsize=10, color=MUTED,
            va="top")
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=(1, 4, 7, 10)))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    footer(fig, n, "Source: wf_pit_unsealed_2025_2026/equity.csv")
    pdf.savefig(fig); plt.close(fig)


def s_oos_table(pdf, n, res):
    p, s = res["portfolios"], res["spy_tr"]
    windows = [("2025", "2025"), ("2026_ytd", "2026 YTD"), ("sealed_2025-01-02_2025-11-18", "Sealed window"),
               ("full", "Full OOS")]
    rows = []
    for key, label in windows:
        r, c, b = p["restored"]["windows"][key], p["control"]["windows"][key], s["windows"][key]
        rows.append([label, pct(r["total_return"]), pct(b["total_return"]), pct(c["total_return"]),
                     f"{r['sharpe']:.2f}", f"{b['sharpe']:.2f}"])
    fig = slide("Out-of-sample by window",
                "Total return net of costs. Sealed window = the original reserved period, 2025-01-02 → 2025-11-18.")
    table(fig, [0.05, 0.36, 0.9, 0.38], ["Window", "Old rule", "SPY TR", "Raw top-decile", "Rule Sharpe", "SPY Sharpe"],
          rows, col_w=[0.24, 0.14, 0.14, 0.18, 0.15, 0.15], highlight_col=1, size=14)
    st = p["restored"]["net"]
    fig.text(0.05, 0.27, f"Old rule: {st['trades']} trades, {pct(st['time_in_market'], False)} of days invested, "
                         f"win rate {pct(st['win_rate'], False)}, costs ${st['total_costs']:,.0f}.",
             fontsize=13.5, color=INK2)
    t3 = p["restored"]["top3_share_of_net_pnl"]
    if t3 is not None:
        fig.text(0.05, 0.22, f"The three largest winners equal {pct(t3, False)} of net P&L.", fontsize=13.5,
                 color=INK2)
    footer(fig, n, "Source: wf_pit_unsealed_2025_2026/results.json")
    pdf.savefig(fig); plt.close(fig)


def s_oos_tests(pdf, n, res):
    pr, p = res["paired_sharpe"], res["portfolios"]["restored"]
    dsr = res["deflated_sharpe"]["dsr"]
    rows = [
        ["Sharpe minus SPY (paired)", f"{pr['spy_tr']['difference']:+.2f}", f"{pr['spy_tr']['lower_95']:+.2f}"],
        ["Sharpe minus raw top-decile (paired)", f"{pr['control']['difference']:+.2f}",
         f"{pr['control']['lower_95']:+.2f}"],
    ]
    fig = slide("How robust is the shortfall?",
                "Paired moving-block bootstrap, 5,000 draws of 20 sessions; one-sided 95% lower bound.")
    table(fig, [0.05, 0.5, 0.9, 0.22], ["Comparison", "Point estimate", "Lower bound"], rows,
          col_w=[0.5, 0.25, 0.25], size=14)
    bullets(fig, [
        f"Cost stress (2× spread, 2× impact)|Sharpe {p['stress']['sharpe']:.2f} vs {p['net']['sharpe']:.2f} base",
        f"Without the three largest winners|Sharpe {p['pruned']['sharpe']:.2f}, total return {pct(p['pruned']['total_return'])}",
        f"Deflated Sharpe at 57 trials|{dsr:.2f} (0.95 needed)",
    ], y=0.4, gap=0.1, size=14)
    footer(fig, n, "Source: wf_pit_unsealed_2025_2026/results.json")
    pdf.savefig(fig); plt.close(fig)


def s_why(pdf, n, res):
    p = res["portfolios"]
    auc = res["fold_test_auc"]
    short = [v[h] for v in auc.values() for h in ("1d", "1w", "1m") if v.get(h)]
    trades = pd.read_csv(OOS / "restored_trades.csv")
    worst = trades.nsmallest(5, "PnL$")
    six = int((worst.Horizon == "6m").sum())
    hz = p["restored"]["horizon_counts"]
    fig = slide("What went wrong: the filter, not the forecasts",
                "The same forecasts, ranked by raw probability, made money; the p − σ > 0.25 filter picked losers.")
    bullets(fig, [
        f"Forecasts kept some skill|Test AUC {min(short):.2f}–{max(short):.2f} at 1 day, 1 week and 1 month "
        f"(0.50 = no skill); about 0.50 at 6 months",
        f"Raw top-decile on the same forecasts|{pct(p['control']['net']['total_return'])}, Sharpe "
        f"{p['control']['net']['sharpe']:.2f} (context only: it failed its own 2016–2024 test)",
        f"Old rule's picks|{p['restored']['net']['trades']} trades, win rate {pct(p['restored']['net']['win_rate'], False)}; "
        f"{hz.get('6m', 0)} were six-month holds",
        f"Losses concentrated in long holds|{'All' if six == 5 else six} of the 5 largest losses were six-month positions "
        f"({', '.join(f'{x:.0f}%' for x in worst['Actual_Return%'])})",
        "Consistent with earlier warnings|σ did not flag worse forecasts in 2016–2024, and the rule's gains rested on a few trades",
    ], gap=0.11, size=14.5)
    footer(fig, n, "Source: wf_pit_unsealed_2025_2026/results.json, restored_trades.csv")
    pdf.savefig(fig); plt.close(fig)


def s_verdict(pdf, n, res):
    ok = bool(res) and res["reading"].startswith("consistent")
    fig = slide("Verdict", None)
    fig.text(0.05, 0.78, f"Out-of-sample: {res['reading'] if res else 'pending'}.", fontsize=20, weight="bold",
             color=GOOD if ok else BAD, va="top")
    bullets(fig, [
        "Development 2016–2024|Higher return than SPY with more risk; failed every luck-adjusted test",
        "Out-of-sample 2025–2026|" + (oos_summary(res) if res else "pending"),
        "Data spent|No untouched pre-2026-11-19 data is left for a future confirmation",
        "Next step|Retire this rule; test new information (earnings, fundamentals) or new history (CRSP 2000–2015)",
    ], y=0.66, gap=0.12, size=15)
    fig.text(0.05, 0.12, "Research only. Not investment advice; the author is not a licensed advisor.", fontsize=11,
             color=MUTED)
    footer(fig, n, "")
    pdf.savefig(fig); plt.close(fig)


def main():
    dev = dev_data()
    res, eq = oos_data()
    with PdfPages(OUTFILE) as pdf:
        n = 1
        s_title(pdf, res)
        for fn in (s_strategy, s_timeline):
            n += 1; fn(pdf, n)
        for fn in (s_dev_curve, s_dev_years):
            n += 1; fn(pdf, n, dev)
        n += 1; s_dev_caveats(pdf, n)
        n += 1; s_oos_setup(pdf, n, res)
        if res is not None:
            n += 1; s_oos_curve(pdf, n, res, eq)
            n += 1; s_oos_table(pdf, n, res)
            n += 1; s_oos_tests(pdf, n, res)
            n += 1; s_why(pdf, n, res)
        n += 1; s_verdict(pdf, n, res)
        meta = pdf.infodict()
        meta["Title"] = "The old LSTM rule: development and out-of-sample"
    print(OUTFILE)


if __name__ == "__main__":
    main()
