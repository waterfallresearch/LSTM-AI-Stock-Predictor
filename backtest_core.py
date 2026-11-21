"""Pure, testable backtest engine for the LSTM probability strategy.

Design rules (see research/audit_2026-11-19_preregistration.md):
- Signals use only information up to and including day t.
- Fill modes (StrategyParams.fill):
    "same_close"  fill at the close the signal was computed on (old, look-ahead-prone behaviour)
    "next_close"  an order decided on day t fills at day t+1's close (legacy default)
    "next_open"   an order decided on day t fills at day t+1's open; time exits also happen at
                  the open, so a "1d" hold is open(t+1) -> open(t+2). Default of StrategyParams.pit().
  The legacy flag next_bar_fill still works: fill=None means next_close if next_bar_fill else same_close.
- The spike filter is causal: a ticker is ineligible on day t once any daily
  move above the threshold has occurred at or before t.
- Costs are charged on every buy and sell. cost_bps is a flat per-side charge. When the panel
  carries the inputs, the PIT cost model adds half-spread, square-root impact and sell-side
  SEC Section 31 + FINRA TAF fees, and a participation cap shrinks entries. Every cost input for
  a trade on session i is taken from session i-1 (known before the trade).

Point-in-time panel (all optional, see build_panel):
- Prices must be RAW (unadjusted) when corporate-action inputs are given; the simulator then
  applies splits, dividends and settlements itself. With split/dividend-adjusted prices pass none.
- Corporate actions are applied at the start of a session, before any trading:
    split     shares *= factor on the effective session (factor = new shares per old share)
    dividend  cash += shares * cash_per_share on the ex-date
    settlement (delisting / merger) the position is closed at
              cash_per_share + successor_shares * successor open on the first session at or after
              the settlement date on which the successor has an open. Only the stock leg is a
              market sale and pays sell-side costs; the cash leg is costless.
- Dates >= CONFIRM_START (the reserved confirmation period) raise ConfirmationPeriodError in
  build_panel and run_strategy unless confirm=True is passed explicitly.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np
import pandas as pd

PERIODS: dict[str, int] = {"1d": 1, "1w": 5, "1m": 21, "6m": 126}
FILL_MODES = ("next_open", "next_close", "same_close")

# Reserved confirmation period (preregistered). Must equal TrainingData/pit/config.py CONFIRM_START.
CONFIRM_START = pd.Timestamp("2025-01-02")


class ConfirmationPeriodError(RuntimeError):
    """Raised when the engine is asked to load or simulate the confirmation period without confirm=True."""


def guard_confirmation(dates, confirm: bool, what: str) -> None:
    if confirm or len(dates) == 0:
        return
    last = pd.Timestamp(max(dates))
    if last >= CONFIRM_START:
        raise ConfirmationPeriodError(
            f"{what} reaches {last.date()}, inside the reserved confirmation period (>= {CONFIRM_START.date()}). "
            "Pass confirm=True only for the single final confirmation run.")


@dataclass(frozen=True)
class StrategyParams:
    min_accepted: float = 0.25
    std_factor: float = 1.0
    max_positions: int = 5
    cost_bps: float = 20.0          # flat per-side cost in bps of notional (commission / legacy cost)
    min_price: float = 5.0
    spike_threshold: float = 0.80
    spike_mode: str = "causal"      # "causal" (point-in-time) or "full" (old look-ahead behaviour)
    next_bar_fill: bool = True      # legacy alias, used only when fill is None
    initial_value: float = 5000.0
    # --- PIT extensions (all inert on a Close-only panel) ---
    fill: str | None = None         # "next_open" | "next_close" | "same_close"; None -> legacy alias
    use_member_mask: bool = False   # only enter tickers that are index members on the signal day
    use_spread_cost: bool = True    # half of panel.spread_est per fill, when the panel has it
    spread_fallback: float = 0.002  # full spread used when the estimate is missing (counted in Result)
    impact_k: float = 0.0           # impact fraction = k * sigma20 * sqrt(shares / ADV20)
    participation_cap: float | None = 0.05   # max entry shares as a fraction of ADV20 (needs volume)
    # Sell fees: rows (effective_date, sec_rate_per_dollar, taf_per_share, taf_max_per_trade).
    sell_fee_table: tuple = ()

    @classmethod
    def pit(cls, **overrides) -> "StrategyParams":
        """Defaults for point-in-time runs: next-open fills, member mask, cost model instead of flat bps."""
        base = dict(fill="next_open", use_member_mask=True, cost_bps=0.0, impact_k=1.0)
        base.update(overrides)
        return cls(**base)

    @property
    def fill_mode(self) -> str:
        if self.fill is None:
            return "next_close" if self.next_bar_fill else "same_close"
        if self.fill not in FILL_MODES:
            raise ValueError(f"unknown fill {self.fill!r}; expected one of {FILL_MODES}")
        if not self.next_bar_fill and self.fill != "same_close":
            raise ValueError(f"fill={self.fill!r} contradicts next_bar_fill=False")
        return self.fill


@dataclass(frozen=True)
class Settlement:
    """Terminal event: holders of `ticker` receive cash_per_share plus successor_shares of the
    successor per share, effective at session index `idx`."""
    idx: int
    j: int
    cash_per_share: float
    successor_j: int | None
    successor_shares: float
    date: pd.Timestamp
    ticker: str
    successor_ticker: str | None


@dataclass
class Panel:
    """Wide arrays aligned on dates (rows) x tickers (columns)."""
    dates: list[pd.Timestamp]
    tickers: list[str]
    close: np.ndarray                 # [T, N], NaN where no bar
    prob: dict[str, np.ndarray]       # horizon -> [T, N]
    std: dict[str, np.ndarray]        # horizon -> [T, N]
    max_move_to_date: np.ndarray      # [T, N] expanding max |daily pct change| (causal)
    max_move_full: np.ndarray         # [N] full-period max |daily pct change| (look-ahead, attribution only)
    # --- optional PIT inputs, [T, N] unless stated ---
    open: np.ndarray | None = None
    high: np.ndarray | None = None
    low: np.ndarray | None = None
    volume: np.ndarray | None = None          # shares
    member: np.ndarray | None = None          # bool universe mask
    spread_est: np.ndarray | None = None      # fractional full spread dated by the session it is known
    adv20: np.ndarray | None = None           # trailing ADV in shares (split-restated), ffilled
    sigma20: np.ndarray | None = None         # trailing std of daily log returns, ffilled
    split_factor: np.ndarray | None = None    # 1.0 except on effective sessions
    dividend: np.ndarray | None = None        # cash per share on ex-date sessions, else 0.0
    settlements: list[Settlement] = field(default_factory=list)


@dataclass
class Result:
    equity: np.ndarray
    trades: pd.DataFrame
    buy_points: list[dict] = field(default_factory=list)
    total_costs: float = 0.0
    open_at_end: int = 0
    days_invested: int = 0
    traded_notional: float = 0.0
    cost_breakdown: dict = field(default_factory=dict)   # flat / spread / impact / fees
    dividends: float = 0.0
    spread_fallbacks: int = 0      # fills that used spread_fallback because the estimate was missing
    cap_blocked: int = 0           # entries skipped because ADV20 was unknown
    cap_shrunk: int = 0            # entries reduced by the participation cap
    cash_path: np.ndarray | None = None
    holdings_path: np.ndarray | None = None
    cancelled_entries: int = 0
    deferred_exits: int = 0
    cash_events: list[dict] = field(default_factory=list)


def is_non_common(symbol: str) -> bool:
    """5+ letter symbols ending in W/U/R/P are warrants, units, rights or preferred shares."""
    return len(symbol) >= 5 and symbol[-1] in "WURP"


def load_forecasts(forecast_dir: Path, exclude_non_common: bool = True) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """Load *_forecast.csv files. Returns (ticker -> DataFrame indexed by Date, excluded symbols)."""
    cols = ["Date", "Close"] + [f"Pred_Prob_{h}" for h in PERIODS] + [f"Pred_Prob_Std_{h}" for h in PERIODS]
    out: dict[str, pd.DataFrame] = {}
    excluded: list[str] = []
    for filename in sorted(os.listdir(forecast_dir)):
        if not filename.endswith("_forecast.csv"):
            continue
        ticker = filename.split("_forecast")[0]
        symbol = ticker.split("_")[0]
        if exclude_non_common and is_non_common(symbol):
            excluded.append(symbol)
            continue
        df = pd.read_csv(Path(forecast_dir) / filename, parse_dates=["Date"], usecols=lambda c: c in cols)
        out[ticker] = df.set_index("Date").sort_index()
    return out, excluded


FEE_RATES_CSV = Path(__file__).resolve().parent / "TrainingData" / "pit" / "overrides" / "fee_rates.csv"


def load_sell_fee_table(path: str | Path = FEE_RATES_CSV) -> tuple:
    """Read the dated sell-fee history into StrategyParams.sell_fee_table form.

    The CSV is long-form: effective_date, fee ("sec31" in $ per million of sales, or "finra_taf" in $ per
    share with max_per_trade), rate, max_per_trade, source_url, note. Each fee keeps its rate until its next
    row. The two histories are merged onto their union of change dates. A blank rate means "unknown from this
    date": sell_fees then raises rather than charging a guessed fee. Dates before both histories start raise too.
    """
    df = pd.read_csv(path, parse_dates=["effective_date"])
    unknown = set(df["fee"]) - {"sec31", "finra_taf"}
    if unknown:
        raise ValueError(f"unknown fee types {sorted(unknown)} in {path}")
    sec = df[df["fee"] == "sec31"].set_index("effective_date").sort_index()
    taf = df[df["fee"] == "finra_taf"].set_index("effective_date").sort_index()
    if sec.index.has_duplicates or taf.index.has_duplicates:
        raise ValueError(f"duplicate effective dates in {path}")
    start = max(sec.index.min(), taf.index.min())
    dates = sorted(d for d in set(sec.index) | set(taf.index) if d >= start)
    rows = []
    for d in dates:
        s = sec.loc[:d].iloc[-1]
        t = taf.loc[:d].iloc[-1]
        rows.append((str(d.date()), float(s["rate"]) / 1e6, float(t["rate"]), float(t["max_per_trade"])))
    return tuple(rows)


# ----------------------------------------------------------------------------- panel

# Optional per-ticker columns in the forecast frames
_OPTIONAL_COLS = {"open": "Open", "high": "High", "low": "Low", "volume": "Volume", "spread_est": "SpreadEst"}


def _event_index(idx: pd.DatetimeIndex, date) -> int | None:
    """First session at or after `date`; None if the date lies outside the panel."""
    d = pd.Timestamp(date)
    if len(idx) == 0 or d < idx[0] or d > idx[-1]:
        return None
    return int(idx.searchsorted(d, side="left"))


def _require_cols(df: pd.DataFrame, cols: list[str], what: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"{what} is missing columns {missing}; expected {cols}")


def build_panel(forecasts: dict[str, pd.DataFrame], start: str | pd.Timestamp | None = None, *,
                end: str | pd.Timestamp | None = None,
                splits: pd.DataFrame | None = None,
                dividends: pd.DataFrame | None = None,
                settlements: pd.DataFrame | None = None,
                confirm: bool = False) -> Panel:
    """Build a Panel from per-ticker frames indexed by Date.

    Required column: Close (plus Pred_Prob_* / Pred_Prob_Std_*; missing -> NaN).
    Optional columns: Open, High, Low, Volume (shares), Member (bool), SpreadEst (fractional).
    If any frame has a column, the panel gets that array; other tickers get NaN (Member: False).

    Corporate-action inputs (prices must then be raw / unadjusted):
      splits       columns date, ticker, factor                 (factor = new shares per old share)
      dividends    columns ex_date, ticker, cash                (cash per pre-ex-date share)
      settlements  columns date, ticker, cash_per_share, successor_ticker, successor_shares
                   (successor_ticker NaN/None for pure cash; date = first session holders are paid)
    Event dates that are not sessions map to the next session; events outside the panel are dropped.
    """
    if end is not None:
        forecasts = {t: df[df.index <= pd.Timestamp(end)] for t, df in forecasts.items()}
    tickers = sorted(forecasts)
    all_dates = sorted(set().union(*[set(df.index) for df in forecasts.values()]))
    if start is not None:
        all_dates = [d for d in all_dates if d >= pd.Timestamp(start)]
    guard_confirmation(all_dates, confirm, "build_panel")
    idx = pd.DatetimeIndex(all_dates)
    col_of = {t: j for j, t in enumerate(tickers)}
    T, N = len(idx), len(tickers)

    def wide(col: str) -> np.ndarray:
        return np.column_stack([
            forecasts[t][col].reindex(idx).to_numpy(dtype=float) if col in forecasts[t] else np.full(len(idx), np.nan)
            for t in tickers
        ]) if tickers else np.empty((len(idx), 0))

    def has(col: str) -> bool:
        return any(col in df.columns for df in forecasts.values())

    close = wide("Close")
    prob = {h: wide(f"Pred_Prob_{h}") for h in PERIODS}
    std = {h: wide(f"Pred_Prob_Std_{h}") for h in PERIODS}
    opt = {k: (wide(c) if has(c) else None) for k, c in _OPTIONAL_COLS.items()}
    member = None
    if has("Member"):
        m = wide("Member")
        member = np.where(np.isfinite(m), m, 0.0) > 0.5

    # ---- corporate actions -> wide arrays
    split_factor = None
    split_by_ticker: dict[str, pd.Series] = {}
    if splits is not None and len(splits):
        _require_cols(splits, ["date", "ticker", "factor"], "splits")
        split_factor = np.ones((T, N))
        for r in splits.itertuples(index=False):
            if r.ticker not in col_of:
                continue
            if not (np.isfinite(r.factor) and r.factor > 0):
                raise ValueError(f"bad split factor {r.factor!r} for {r.ticker} on {r.date}")
            k = _event_index(idx, r.date)
            if k is not None:
                split_factor[k, col_of[r.ticker]] *= float(r.factor)
            # on the ticker's own bar calendar (for the spike filter / vol / ADV)
            own = forecasts[r.ticker].index
            p = own.searchsorted(pd.Timestamp(r.date), side="left")
            if p < len(own):
                s = split_by_ticker.setdefault(r.ticker, pd.Series(1.0, index=own))
                s.iloc[p] *= float(r.factor)

    dividend = None
    if dividends is not None and len(dividends):
        _require_cols(dividends, ["ex_date", "ticker", "cash"], "dividends")
        dividend = np.zeros((T, N))
        for r in dividends.itertuples(index=False):
            if r.ticker not in col_of:
                continue
            k = _event_index(idx, r.ex_date)
            if k is not None:
                dividend[k, col_of[r.ticker]] += float(r.cash)

    settle_list: list[Settlement] = []
    if settlements is not None and len(settlements):
        _require_cols(settlements, ["date", "ticker", "cash_per_share", "successor_ticker", "successor_shares"],
                      "settlements")
        for r in settlements.itertuples(index=False):
            if r.ticker not in col_of:
                continue
            k = _event_index(idx, r.date)
            if k is None:
                continue
            ss = float(r.successor_shares) if pd.notna(r.successor_shares) else 0.0
            succ = r.successor_ticker if isinstance(r.successor_ticker, str) and r.successor_ticker else None
            if ss > 0:
                if succ is None or succ not in col_of:
                    raise ValueError(f"settlement of {r.ticker}: successor {succ!r} is not in the panel")
                if opt["open"] is None:
                    raise ValueError("stock settlements need Open prices (valued at the successor's open)")
            cash_ps = float(r.cash_per_share) if pd.notna(r.cash_per_share) else 0.0
            settle_list.append(Settlement(k, col_of[r.ticker], cash_ps, col_of[succ] if ss > 0 else None, ss,
                                          idx[k], r.ticker, succ if ss > 0 else None))
        if len({s.j for s in settle_list}) != len(settle_list):
            raise ValueError("more than one settlement per ticker")

    # ---- daily moves on each ticker's own bar sequence (not the union calendar)
    max_to_date = np.zeros_like(close)
    max_full = np.zeros(len(tickers))
    for j, t in enumerate(tickers):
        c = forecasts[t]["Close"]
        c = c[c.index >= idx[0]] if len(idx) else c
        if t in split_by_ticker:   # raw prices: a 2-for-1 split is not a -50% move
            f = split_by_ticker[t].reindex(c.index).fillna(1.0)
            moves = (c * f / c.shift(1) - 1.0).abs().fillna(0.0)
        else:
            moves = c.pct_change().abs().fillna(0.0)
        max_full[j] = float(moves.max()) if len(moves) else 0.0
        max_to_date[:, j] = moves.cummax().reindex(idx).ffill().fillna(0.0).to_numpy()

    # ---- ADV20 / sigma20 for the impact model and participation cap (needs Volume)
    adv20 = sigma20 = None
    if opt["volume"] is not None and N:
        from TrainingData.pit import costs as _costs   # lazy: Close-only runs never import the data layer
        adv20 = np.full((T, N), np.nan)
        sigma20 = np.full((T, N), np.nan)
        for j, t in enumerate(tickers):
            df = forecasts[t]
            if "Volume" not in df:
                continue
            f = split_by_ticker.get(t)
            adv20[:, j] = _costs.adv(df["Volume"].astype(float), split_factor=f).reindex(idx).ffill().to_numpy()
            sigma20[:, j] = _costs.realized_vol(df["Close"].astype(float), split_factor=f).reindex(idx).ffill().to_numpy()

    return Panel(list(idx), tickers, close, prob, std, max_to_date, max_full,
                 open=opt["open"], high=opt["high"], low=opt["low"], volume=opt["volume"], member=member,
                 spread_est=opt["spread_est"], adv20=adv20, sigma20=sigma20,
                 split_factor=split_factor, dividend=dividend, settlements=settle_list)


def _eligible_mask(panel: Panel, i: int, p: StrategyParams) -> np.ndarray:
    c = panel.close[i]
    ok = np.isfinite(c) & (c >= p.min_price)
    if p.spike_mode == "causal":
        ok &= panel.max_move_to_date[i] <= p.spike_threshold
    elif p.spike_mode == "full":
        ok &= panel.max_move_full <= p.spike_threshold
    else:
        raise ValueError(f"unknown spike_mode {p.spike_mode!r}")
    if p.use_member_mask:
        ok &= panel.member[i]
    return ok


def _fee_rows(table: tuple) -> list[tuple[pd.Timestamp, float, float, float]]:
    rows = sorted((pd.Timestamp(d), float(sec), float(taf), float(cap)) for d, sec, taf, cap in table)
    return rows


def sell_fees(date: pd.Timestamp, notional: float, shares: float, rows: list) -> float:
    """SEC Section 31 (rate x notional) + FINRA TAF (per share, capped per trade) for one sale."""
    row = None
    for r in rows:
        if r[0] <= date:
            row = r
        else:
            break
    if row is None:
        raise ValueError(f"sell_fee_table has no rate in force on {date.date()}")
    _, sec, taf, cap = row
    if not (np.isfinite(sec) and np.isfinite(taf) and np.isfinite(cap)):
        raise ValueError(f"sell fee rates are unknown on {date.date()} (blank row in effect from {row[0].date()})")
    return sec * notional + min(taf * shares, cap)


# ----------------------------------------------------------------------------- simulator

def run_strategy(panel: Panel, p: StrategyParams, rng: np.random.Generator | None = None,
                 shuffle_signals: bool = False, *, confirm: bool = False,
                 targets: dict[int, dict[int, float]] | None = None) -> Result:
    """Simulate the strategy. With shuffle_signals=True (negative control) each day's
    (prob, std) pairs are randomly reassigned among that day's tickers that have a forecast."""
    guard_confirmation(panel.dates, confirm, "run_strategy")
    T, N = panel.close.shape
    fill = p.fill_mode
    open_mode = fill == "next_open"
    if targets is not None:
        if not open_mode or shuffle_signals:
            raise ValueError("Target rebalancing requires deterministic next-open fills")
        for i, weights in targets.items():
            if not 0 <= i < T - 1 or any(not 0 <= j < N or not 0 < w <= 1 for j, w in weights.items()):
                raise ValueError("Invalid rebalance schedule")
            if sum(weights.values()) > 1 + 1e-10:
                raise ValueError("Target weights exceed unlevered exposure")
    if open_mode and panel.open is None:
        raise ValueError("fill='next_open' needs a panel with Open prices")
    if p.use_member_mask and panel.member is None:
        raise ValueError("use_member_mask=True needs a panel with a Member column")
    cost_rate = p.cost_bps / 10_000.0
    horizons = list(PERIODS.items())

    use_spread = p.use_spread_cost and panel.spread_est is not None
    use_impact = p.impact_k > 0 and panel.adv20 is not None
    use_cap = p.participation_cap is not None and panel.adv20 is not None
    fee_rows = _fee_rows(p.sell_fee_table) if p.sell_fee_table else []
    settle_at: dict[int, list[Settlement]] = {}
    for s in panel.settlements:
        settle_at.setdefault(s.idx, []).append(s)
    active_settle: dict[int, Settlement] = {}

    cash = p.initial_value
    positions: list[dict] = []
    pending: list[dict] = []
    equity = np.zeros(T)
    cash_path = np.zeros(T) if targets is not None else None
    holdings_path = np.zeros(T) if targets is not None else None
    deferred: dict[int, float] = {}
    cash_events: list[dict] = []
    cancelled_entries = deferred_exits = 0
    trades: list[dict] = []
    buy_points: list[dict] = []
    total_costs = 0.0
    days_invested = 0
    traded = 0.0
    last_px = np.full(N, np.nan)
    br = {"flat": 0.0, "spread": 0.0, "impact": 0.0, "fees": 0.0}
    stats = {"spread_fallbacks": 0, "cap_blocked": 0, "cap_shrunk": 0, "dividends": 0.0}

    def prior_adv(i: int, j: int) -> float:
        if i == 0:
            return np.nan
        scale = panel.split_factor[i, j] if targets is not None and panel.split_factor is not None else 1.0
        return panel.adv20[i - 1, j] * scale

    def cash_event(i: int, j: int, kind: str, amount: float, shares: float, price: float, cost=0.0) -> None:
        if targets is not None:
            cash_events.append({"date": panel.dates[i], "ticker": panel.tickers[j], "kind": kind,
                                "cash_change": amount, "shares": shares, "price": price, "cost": cost})

    def trade_cost(i: int, j: int, notional: float, shares: float, side: str) -> float:
        c = notional * cost_rate
        br["flat"] += c
        if use_spread:
            s = panel.spread_est[i - 1, j] if i > 0 else np.nan
            if not np.isfinite(s):
                s = p.spread_fallback
                stats["spread_fallbacks"] += 1
            x = 0.5 * s * notional
            br["spread"] += x
            c += x
        if use_impact and i > 0:
            a, sig = prior_adv(i, j), panel.sigma20[i - 1, j]
            if np.isfinite(a) and a > 0 and np.isfinite(sig):
                x = p.impact_k * sig * np.sqrt(shares / a) * notional
                br["impact"] += x
                c += x
        if side == "sell" and fee_rows:
            x = sell_fees(panel.dates[i], notional, shares, fee_rows)
            br["fees"] += x
            c += x
        return c

    def record_exit(pos: dict, i: int, px: float, gross: float, cost: float, kind: str) -> None:
        proceeds = gross - cost + pos["divs"]
        net_ret = proceeds / pos["cost_basis"] - 1.0
        trades.append({
            "BuyDate": panel.dates[pos["entry_idx"]], "SellDate": panel.dates[i],
            "SignalDate": panel.dates[pos["signal_idx"]],
            "Ticker": panel.tickers[pos["j"]], "Horizon": pos["h"], "DaysHeld": i - pos["entry_idx"],
            "Pred_Prob": pos["prob"], "Pred_Prob_Std": pos["std"], "Adj_Prob": pos["adj"],
            "EntryPrice": pos["entry_px"], "ExitPrice": px,
            "Gross_Return%": (px / pos["entry_px"] - 1.0) * 100,
            "Actual_Return%": net_ret * 100,
            "Actual_LogR": np.log1p(net_ret),
            "PnL$": proceeds - pos["cost_basis"],
            "Dividends$": pos["divs"], "ExitType": kind,
        })

    def equity_now() -> float:
        return cash + sum(q["shares"] * q["last_px"] for q in positions)

    def equity_at_open(i: int, prev_px: np.ndarray) -> float:
        """Marks known at the open of session i: today's open, else the previous close."""
        tot = cash
        for q in positions:
            o = panel.open[i, q["j"]]
            tot += q["shares"] * (o if np.isfinite(o) else (q["last_px"] if q.get("settling") else prev_px[q["j"]]))
        return tot

    def open_position(o: dict, i: int, px: float, slot: float, value_fn) -> bool:
        """Buy for order o at px. Returns False when cash is exhausted (stop filling)."""
        nonlocal cash, total_costs, traded
        alloc = min(slot, cash)
        if alloc < 1.0:
            return False
        j = o["j"]
        if use_cap:
            a = panel.adv20[i - 1, j] if i > 0 else np.nan
            if not (np.isfinite(a) and a > 0):
                stats["cap_blocked"] += 1
                return True
            cap_notional = p.participation_cap * a * px
            if cap_notional < alloc:
                alloc = cap_notional
                stats["cap_shrunk"] += 1
            if alloc < 1.0:
                return True
        cost = trade_cost(i, j, alloc, alloc / px, "buy")
        cash -= alloc
        total_costs += cost
        traded += alloc
        positions.append({**o, "entry_idx": i, "entry_px": px, "last_px": px,
                          "shares": (alloc - cost) / px, "cost_basis": alloc, "divs": 0.0,
                          "exit_idx": min(i + o["days"], T - 1)})
        buy_points.append({"Date": panel.dates[i], "Value": value_fn(), "Ticker": panel.tickers[j],
                           "Horizon": o["h"], "Pred_Prob": o["prob"], "Adj_Prob": o["adj"]})
        return True

    def rebalance(i: int, prev_px: np.ndarray) -> None:
        nonlocal cash, traded, total_costs, cancelled_entries, deferred_exits
        weights = targets.get(i - 1)
        marks = panel.open[i]
        held = {pos["j"]: pos for pos in positions}
        if weights is not None:
            value = equity_at_open(i, prev_px)
            deferred.clear()
            for j, pos in held.items():
                mark = marks[j] if np.isfinite(marks[j]) and marks[j] > 0 else prev_px[j]
                if j in active_settle:
                    continue
                if j not in weights:
                    deferred[j] = pos["shares"]
                elif np.isfinite(mark) and mark > 0:
                    trim = pos["shares"] - value * weights[j] / mark
                    if trim > 1e-10:
                        deferred[j] = trim
        for j in sorted(deferred, key=lambda j: panel.tickers[j]):
            pos = held.get(j)
            if pos is None or j in active_settle:
                del deferred[j]
                continue
            px = marks[j]
            if not np.isfinite(px) or px <= 0:
                deferred_exits += 1
                continue
            quantity = min(deferred[j], pos["shares"])
            if use_cap:
                a = prior_adv(i, j)
                if not np.isfinite(a) or a <= 0:
                    stats["cap_blocked"] += 1
                    deferred_exits += 1
                    continue
                cap = p.participation_cap * a
                if cap < quantity:
                    quantity = cap
                    stats["cap_shrunk"] += 1
            fraction = quantity / pos["shares"]
            basis = pos["cost_basis"] * fraction
            divs = pos["divs"] * fraction
            gross = quantity * px
            cost = trade_cost(i, j, gross, quantity, "sell")
            record_exit({**pos, "cost_basis": basis, "divs": divs}, i, px, gross, cost, "rebalance")
            cash += gross - cost
            cash_event(i, j, "sell", gross - cost, quantity, px, cost)
            traded += gross
            total_costs += cost
            pos["shares"] -= quantity
            pos["cost_basis"] -= basis
            pos["divs"] -= divs
            deferred[j] -= quantity
            if pos["shares"] <= 1e-10:
                positions.remove(pos)
                del held[j]
            if deferred[j] <= 1e-10 or j not in held:
                del deferred[j]
            else:
                deferred_exits += 1
        if weights is None:
            return
        for j, weight in weights.items():
            px = marks[j]
            if j in active_settle or not np.isfinite(px) or px <= 0:
                cancelled_entries += 1
                continue
            pos = held.get(j)
            shares = pos["shares"] if pos else 0.0
            alloc = min(cash, value * weight - shares * px)
            if alloc < 1.0:
                continue
            if use_cap:
                a = prior_adv(i, j)
                if not np.isfinite(a) or a <= 0:
                    stats["cap_blocked"] += 1
                    continue
                cap = p.participation_cap * a * px
                if cap < alloc:
                    alloc = cap
                    stats["cap_shrunk"] += 1
            if alloc < 1.0:
                continue
            cost = trade_cost(i, j, alloc, alloc / px, "buy")
            acquired = (alloc - cost) / px
            if acquired <= 0:
                raise ValueError("Buy costs exceed allocation")
            cash -= alloc
            cash_event(i, j, "buy", -alloc, acquired, px, cost)
            total_costs += cost
            traded += alloc
            if pos:
                pos["entry_px"] = (pos["entry_px"] * shares + px * acquired) / (shares + acquired)
                pos["shares"] += acquired
                pos["cost_basis"] += alloc
            else:
                positions.append({"j": j, "entry_idx": i, "signal_idx": i - 1, "entry_px": px,
                                  "last_px": px, "shares": acquired, "cost_basis": alloc, "divs": 0.0,
                                  "exit_idx": T, "h": "rebalance", "prob": np.nan,
                                  "std": np.nan, "adj": np.nan})

    for i in range(T):
        row = panel.close[i]
        fin = np.isfinite(row)

        # 0) Corporate actions at the start of the session, before any trading
        if panel.split_factor is not None:
            f = panel.split_factor[i]
            sj = np.flatnonzero(f != 1.0)
            if sj.size:
                last_px[sj] = last_px[sj] / f[sj]          # stale marks restated in post-split units
                for j in deferred:
                    deferred[j] *= f[j]
                for pos in positions:
                    fj = f[pos["j"]]
                    if fj != 1.0:
                        pos["shares"] *= fj
                        pos["entry_px"] /= fj
                        pos["last_px"] /= fj
        if panel.dividend is not None:
            dv = panel.dividend[i]
            for pos in positions:
                d = dv[pos["j"]]
                if d != 0.0:
                    amt = pos["shares"] * d
                    cash += amt
                    cash_event(i, pos["j"], "dividend", amt, pos["shares"], d)
                    pos["divs"] += amt
                    stats["dividends"] += amt
        for s in settle_at.get(i, []):
            active_settle[s.j] = s

        prev_px = last_px.copy()
        last_px[fin] = row[fin]

        # 1) Mark to market
        for pos in positions:
            pos["last_px"] = last_px[pos["j"]]

        # 1b) Settlements: forced exit at settlement value
        if active_settle:
            keep = []
            for pos in positions:
                s = active_settle.get(pos["j"])
                if s is None:
                    keep.append(pos)
                    continue
                po = 0.0
                if s.successor_j is not None:
                    po = panel.open[i, s.successor_j]
                    if not (np.isfinite(po) and po > 0):
                        lp = prev_px[s.successor_j] if targets is not None else last_px[s.successor_j]
                        if i < T - 1 or targets is not None:
                            if np.isfinite(lp):
                                pos["last_px"] = s.cash_per_share + s.successor_shares * lp
                            pos["settling"] = True
                            keep.append(pos)
                            continue
                        if not np.isfinite(lp):
                            raise ValueError(f"settlement of {s.ticker}: successor {s.successor_ticker} never priced")
                        po = lp
                stock_sh = pos["shares"] * s.successor_shares
                stock_val = stock_sh * po
                cost = trade_cost(i, s.successor_j, stock_val, stock_sh, "sell") if stock_sh > 0 else 0.0
                gross = pos["shares"] * s.cash_per_share + stock_val
                cash += gross - cost
                cash_event(i, pos["j"], "settlement", gross - cost, pos["shares"],
                           gross / pos["shares"], cost)
                total_costs += cost
                traded += stock_val
                value_ps = s.cash_per_share + s.successor_shares * po
                pos["last_px"] = value_ps
                record_exit(pos, i, value_ps, gross, cost, "settlement")
            positions = keep

        if targets is not None:
            rebalance(i, prev_px)
            for pos in positions:
                if pos.get("settling"):
                    s = active_settle[pos["j"]]
                    lp = last_px[s.successor_j]
                    if np.isfinite(lp):
                        pos["last_px"] = s.cash_per_share + s.successor_shares * lp
                elif np.isfinite(last_px[pos["j"]]):
                    pos["last_px"] = last_px[pos["j"]]
            cash_path[i] = cash
            holdings_path[i] = sum(q["shares"] * q["last_px"] for q in positions)
            equity[i] = cash_path[i] + holdings_path[i]
            days_invested += bool(positions)
            continue

        # 2) Time exits (at the open in next_open mode, else at the close / last mark)
        keep = []
        for pos in positions:
            if i < pos["exit_idx"] or pos["j"] in active_settle:
                keep.append(pos)
                continue
            px = pos["last_px"]
            if open_mode:
                o = panel.open[i, pos["j"]]
                if np.isfinite(o) and o > 0:
                    px = o
                elif i < T - 1:
                    keep.append(pos)       # no executable open (halt): retry next session
                    continue
            gross = pos["shares"] * px
            cost = trade_cost(i, pos["j"], gross, pos["shares"], "sell")
            cash += gross - cost
            total_costs += cost
            traded += gross
            record_exit(pos, i, px, gross, cost, "time")
        positions = keep

        # 3) Fill pending orders from yesterday's signals (today's open or close)
        if pending:
            if open_mode:
                slot = equity_at_open(i, prev_px) / p.max_positions
                fill_row = panel.open[i]
                value_fn = lambda: equity_at_open(i, prev_px)  # noqa: E731
            else:
                slot = equity_now() / p.max_positions
                fill_row = row
                value_fn = equity_now
            for o in pending:
                px = fill_row[o["j"]]
                if (not np.isfinite(px) or px <= 0 or any(q["j"] == o["j"] for q in positions)
                        or o["j"] in active_settle):
                    continue
                if not open_position(o, i, px, slot, value_fn):
                    break
            pending = []
            if open_mode:   # positions bought at the open are marked at today's close
                for pos in positions:
                    lp = last_px[pos["j"]]
                    if not pos.get("settling") and np.isfinite(lp):
                        pos["last_px"] = lp

        # 4) New signals (decided at today's close)
        free = p.max_positions - len(positions)
        # No new signals on the final day: an order could never be held
        if free > 0 and i <= T - 2:
            elig = _eligible_mask(panel, i, p)
            for q in positions:
                elig[q["j"]] = False
            for j in active_settle:
                elig[j] = False

            probs = {h: panel.prob[h][i].copy() for h, _ in horizons}
            stds = {h: panel.std[h][i].copy() for h, _ in horizons}
            if shuffle_signals:
                assert rng is not None, "shuffle_signals needs an rng"
                has = np.isfinite(probs[horizons[0][0]])
                cols = np.flatnonzero(has)
                perm = rng.permutation(cols)
                for h, _ in horizons:
                    probs[h][cols] = probs[h][perm]
                    stds[h][cols] = stds[h][perm]

            best_adj = np.full(N, -np.inf)
            best_h = np.empty(N, dtype=object)
            for h, _ in horizons:
                s = np.where(np.isfinite(stds[h]), stds[h], 0.0)
                adj = probs[h] - p.std_factor * np.maximum(s, 1e-6)
                better = np.isfinite(adj) & (adj > best_adj)
                best_adj[better] = adj[better]
                best_h[better] = h
            cand = np.flatnonzero(elig & (best_adj > p.min_accepted))
            cand = cand[np.argsort(-best_adj[cand], kind="stable")][:free]

            orders = []
            for j in cand:
                h = best_h[j]
                orders.append({"j": int(j), "h": h, "days": PERIODS[h], "signal_idx": i,
                               "prob": float(panel.prob[h][i, j]) if not shuffle_signals else float(probs[h][j]),
                               "std": float(stds[h][j]) if np.isfinite(stds[h][j]) else 0.0,
                               "adj": float(best_adj[j])})
            if fill != "same_close":
                pending = orders
            else:
                # Old behaviour: fill at the same close the signal was computed on
                slot = equity_now() / p.max_positions
                for o in orders:
                    if not open_position(o, i, row[o["j"]], slot, equity_now):
                        break

        if positions:
            days_invested += 1
        equity[i] = cash + sum(q["shares"] * q["last_px"] for q in positions)

    return Result(equity, pd.DataFrame(trades), buy_points, total_costs, len(positions), days_invested, traded,
                  cost_breakdown=br, dividends=stats["dividends"], spread_fallbacks=stats["spread_fallbacks"],
                  cap_blocked=stats["cap_blocked"], cap_shrunk=stats["cap_shrunk"],
                  cash_path=cash_path, holdings_path=holdings_path, cancelled_entries=cancelled_entries,
                  deferred_exits=deferred_exits, cash_events=cash_events)


# ----------------------------------------------------------------------------- metrics

def daily_returns(equity: np.ndarray) -> np.ndarray:
    e = np.asarray(equity, dtype=float)
    r = e[1:] / e[:-1] - 1.0
    return r[np.isfinite(r)]


def max_drawdown(equity: np.ndarray) -> float:
    e = np.asarray(equity, dtype=float)
    if len(e) < 2:
        return 0.0
    return float((e / np.maximum.accumulate(e) - 1.0).min())


def sharpe(r: np.ndarray, periods: int = 252) -> float:
    r = np.asarray(r, dtype=float)
    sd = r.std(ddof=1) if r.size > 1 else 0.0
    return float(np.sqrt(periods) * r.mean() / sd) if sd > 1e-12 else float("nan")


def sortino(r: np.ndarray, periods: int = 252) -> float:
    r = np.asarray(r, dtype=float)
    downside = np.sqrt(np.mean(np.minimum(r, 0.0) ** 2)) if r.size else 0.0
    return float(np.sqrt(periods) * r.mean() / downside) if downside > 1e-12 else float("nan")


def newey_west_t(r: np.ndarray, lags: int = 10) -> float:
    """t-stat of the mean with Newey-West (Bartlett) HAC standard error."""
    r = np.asarray(r, dtype=float)
    n = r.size
    if n < lags + 2:
        return float("nan")
    u = r - r.mean()
    var = u @ u / n
    for k in range(1, lags + 1):
        w = 1.0 - k / (lags + 1)
        var += 2.0 * w * (u[k:] @ u[:-k]) / n
    se = np.sqrt(var / n)
    return float(r.mean() / se) if se > 0 else float("nan")


def summarize(res: Result, initial_value: float) -> dict:
    r = daily_returns(res.equity)
    t = res.trades
    pnl = t["PnL$"] if len(t) else pd.Series(dtype=float)
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    avg_equity = float(np.mean(res.equity)) if len(res.equity) else initial_value
    years = max(len(res.equity) - 1, 1) / 252.0
    return {
        "total_return": float(res.equity[-1] / initial_value - 1.0),
        "cagr": float((res.equity[-1] / initial_value) ** (1 / years) - 1.0) if res.equity[-1] > 0 else float("nan"),
        "sharpe": sharpe(r),
        "sortino": sortino(r),
        "max_drawdown": max_drawdown(res.equity),
        "nw_t_stat": newey_west_t(r),
        "trades": int(len(t)),
        "win_rate": float((pnl > 0).mean()) if len(t) else float("nan"),
        "avg_win_pct": float(t.loc[pnl > 0, "Actual_Return%"].mean()) if len(wins) else float("nan"),
        "avg_loss_pct": float(t.loc[pnl <= 0, "Actual_Return%"].mean()) if len(losses) else float("nan"),
        "profit_factor": float(wins.sum() / -losses.sum()) if len(losses) and losses.sum() < 0 else float("nan"),
        "time_in_market": res.days_invested / max(len(res.equity), 1),
        "annual_turnover": float(res.traded_notional / avg_equity / years),
        "total_costs": float(res.total_costs),
        "open_at_end": res.open_at_end,
    }
