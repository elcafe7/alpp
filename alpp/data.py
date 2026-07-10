"""Alpaca market-data + asset metadata."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockSnapshotRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.client import TradingClient

from .creds import Credentials, require_credentials
from .timeframes import RangeSpec, to_utc


@dataclass(frozen=True)
class AssetInfo:
    symbol: str
    name: str
    exchange: str
    asset_class: str
    tradable: bool
    status: str


_active_creds: Credentials | None = None


def set_active_credentials(creds: Credentials) -> None:
    global _active_creds
    _active_creds = creds


def _active() -> Credentials:
    if _active_creds is not None:
        return _active_creds
    return require_credentials()


def _creds() -> tuple[str, str]:
    creds = _active()
    return creds.api_key, creds.secret_key


def _paper_mode() -> bool:
    return _active().paper


def resolve_asset(symbol: str) -> AssetInfo:
    """Look up ticker and return semantic name / metadata."""
    key, secret = _creds()
    client = TradingClient(key, secret, paper=_paper_mode())
    sym = symbol.strip().upper()
    try:
        a = client.get_asset(sym)
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"Unknown or unavailable ticker {sym!r}: {exc}") from exc

    name = (getattr(a, "name", None) or "").strip() or "(name unavailable)"
    exchange = str(getattr(a, "exchange", "") or "").replace("AssetExchange.", "")
    asset_class = str(getattr(a, "asset_class", "") or "").replace("AssetClass.", "")
    status = str(getattr(a, "status", "") or "").replace("AssetStatus.", "")
    tradable = bool(getattr(a, "tradable", False))
    return AssetInfo(
        symbol=str(a.symbol).upper(),
        name=name,
        exchange=exchange,
        asset_class=asset_class,
        tradable=tradable,
        status=status,
    )


def _timeframe(bar: str) -> TimeFrame:
    mapping = {
        "1Min": TimeFrame(1, TimeFrameUnit.Minute),
        "5Min": TimeFrame(5, TimeFrameUnit.Minute),
        "15Min": TimeFrame(15, TimeFrameUnit.Minute),
        "1Hour": TimeFrame(1, TimeFrameUnit.Hour),
        "1Day": TimeFrame(1, TimeFrameUnit.Day),
        "1Week": TimeFrame(1, TimeFrameUnit.Week),
    }
    if bar not in mapping:
        raise SystemExit(f"Unsupported bar size: {bar}")
    return mapping[bar]


def fetch_bars(symbol: str, rng: RangeSpec) -> pd.DataFrame:
    key, secret = _creds()
    client = StockHistoricalDataClient(key, secret)
    req = StockBarsRequest(
        symbol_or_symbols=symbol.upper(),
        timeframe=_timeframe(rng.bar),
        start=to_utc(rng.start),
        end=to_utc(rng.end),
        adjustment=Adjustment.ALL,
        feed=DataFeed.IEX,  # free/default-friendly; SIP if entitled
    )
    try:
        bars = client.get_stock_bars(req)
    except Exception as exc:  # noqa: BLE001
        # Retry without explicit feed if account feed differs
        if "feed" in str(exc).lower() or "subscription" in str(exc).lower():
            req = StockBarsRequest(
                symbol_or_symbols=symbol.upper(),
                timeframe=_timeframe(rng.bar),
                start=to_utc(rng.start),
                end=to_utc(rng.end),
                adjustment=Adjustment.ALL,
            )
            bars = client.get_stock_bars(req)
        else:
            raise SystemExit(f"Alpaca data error for {symbol}: {exc}") from exc

    df = bars.df
    if df is None or df.empty:
        raise SystemExit(f"No bars returned for {symbol.upper()} ({rng.label}, {rng.bar})")

    if isinstance(df.index, pd.MultiIndex):
        df = df.xs(symbol.upper(), level=0)

    df = df.reset_index()
    # column may be timestamp or index name
    ts_col = "timestamp" if "timestamp" in df.columns else df.columns[0]
    df = df.rename(columns={ts_col: "timestamp"})
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def period_stats(df: pd.DataFrame) -> dict:
    if df.empty:
        return {}
    first = float(df["close"].iloc[0])
    last = float(df["close"].iloc[-1])
    hi = float(df["high"].max())
    lo = float(df["low"].min())
    nominal = last - first
    pct = (nominal / first) * 100.0 if first else 0.0
    vol = float(df["volume"].sum()) if "volume" in df.columns else None
    avg_vol = float(df["volume"].mean()) if "volume" in df.columns else None
    return {
        "open": first,
        "last": last,
        "high": hi,
        "low": lo,
        "nominal": nominal,
        "pct": pct,
        "bars": len(df),
        "start": df["timestamp"].iloc[0],
        "end": df["timestamp"].iloc[-1],
        "volume_sum": vol,
        "volume_avg": avg_vol,
    }


def _bar_field(bar: Any, name: str, default=None):
    if bar is None:
        return default
    if isinstance(bar, dict):
        return bar.get(name, default)
    return getattr(bar, name, default)


def _client() -> StockHistoricalDataClient:
    key, secret = _creds()
    return StockHistoricalDataClient(key, secret)


def fetch_snapshot(symbol: str) -> dict[str, Any]:
    """Latest trade/quote + daily/prev daily bars (IEX-friendly)."""
    client = _client()
    sym = symbol.upper()
    try:
        raw = client.get_stock_snapshot(
            StockSnapshotRequest(symbol_or_symbols=sym, feed=DataFeed.IEX)
        )
    except Exception:
        raw = client.get_stock_snapshot(StockSnapshotRequest(symbol_or_symbols=sym))

    snap = raw[sym] if isinstance(raw, dict) else raw[sym]
    # object or dict-like
    if not isinstance(snap, dict):
        snap = {
            "latest_trade": getattr(snap, "latest_trade", None),
            "latest_quote": getattr(snap, "latest_quote", None),
            "daily_bar": getattr(snap, "daily_bar", None),
            "previous_daily_bar": getattr(snap, "previous_daily_bar", None),
            "minute_bar": getattr(snap, "minute_bar", None),
        }

    trade = snap.get("latest_trade")
    quote = snap.get("latest_quote")
    daily = snap.get("daily_bar")
    prev = snap.get("previous_daily_bar")

    last = _bar_field(trade, "price")
    if last is None:
        last = _bar_field(daily, "close")
    prev_close = _bar_field(prev, "close")
    day_open = _bar_field(daily, "open")
    day_high = _bar_field(daily, "high")
    day_low = _bar_field(daily, "low")
    day_vol = _bar_field(daily, "volume")
    day_vwap = _bar_field(daily, "vwap")
    bid = _bar_field(quote, "bid_price")
    ask = _bar_field(quote, "ask_price")

    day_chg = None
    day_pct = None
    if last is not None and prev_close not in (None, 0):
        day_chg = float(last) - float(prev_close)
        day_pct = (day_chg / float(prev_close)) * 100.0

    return {
        "last": float(last) if last is not None else None,
        "prev_close": float(prev_close) if prev_close is not None else None,
        "day_open": float(day_open) if day_open is not None else None,
        "day_high": float(day_high) if day_high is not None else None,
        "day_low": float(day_low) if day_low is not None else None,
        "day_volume": float(day_vol) if day_vol is not None else None,
        "day_vwap": float(day_vwap) if day_vwap is not None else None,
        "day_change": day_chg,
        "day_pct": day_pct,
        "bid": float(bid) if bid is not None else None,
        "ask": float(ask) if ask is not None else None,
        "spread": (
            float(ask) - float(bid)
            if bid is not None and ask is not None
            else None
        ),
    }


def fetch_trailing_stats(symbol: str, days: int = 365) -> dict[str, Any]:
    """
    52-week-style stats from daily bars:
    high/low, avg volume, returns (1m/3m/6m/1y when history allows).
    """
    client = _client()
    sym = symbol.upper()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days + 20)
    req = StockBarsRequest(
        symbol_or_symbols=sym,
        timeframe=TimeFrame(1, TimeFrameUnit.Day),
        start=start,
        end=end,
        adjustment=Adjustment.ALL,
        feed=DataFeed.IEX,
    )
    try:
        bars = client.get_stock_bars(req)
    except Exception:
        req = StockBarsRequest(
            symbol_or_symbols=sym,
            timeframe=TimeFrame(1, TimeFrameUnit.Day),
            start=start,
            end=end,
            adjustment=Adjustment.ALL,
        )
        bars = client.get_stock_bars(req)

    df = bars.df
    if df is None or df.empty:
        return {}
    if isinstance(df.index, pd.MultiIndex):
        df = df.xs(sym, level=0)
    df = df.reset_index()
    ts_col = "timestamp" if "timestamp" in df.columns else df.columns[0]
    df = df.rename(columns={ts_col: "timestamp"})
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # last ~252 trading days ≈ 52 weeks
    trail = df.tail(252) if len(df) > 252 else df
    last = float(trail["close"].iloc[-1])
    hi = float(trail["high"].max())
    lo = float(trail["low"].min())
    hi_idx = trail["high"].idxmax()
    lo_idx = trail["low"].idxmin()
    hi_date = trail.loc[hi_idx, "timestamp"]
    lo_date = trail.loc[lo_idx, "timestamp"]
    span = hi - lo
    pos = ((last - lo) / span * 100.0) if span > 0 else None
    from_hi = ((last - hi) / hi * 100.0) if hi else None
    from_lo = ((last - lo) / lo * 100.0) if lo else None

    avg_vol_20 = (
        float(trail["volume"].tail(20).mean()) if "volume" in trail.columns else None
    )
    avg_vol_50 = (
        float(trail["volume"].tail(50).mean()) if "volume" in trail.columns else None
    )
    last_vol = float(trail["volume"].iloc[-1]) if "volume" in trail.columns else None
    rvol = (last_vol / avg_vol_20) if avg_vol_20 and last_vol is not None else None

    def _ret(n: int) -> float | None:
        if len(trail) <= n:
            return None
        a = float(trail["close"].iloc[-n - 1])
        b = last
        if a == 0:
            return None
        return (b / a - 1.0) * 100.0

    # ATR(14) rough
    prev_c = trail["close"].shift(1)
    tr = pd.concat(
        [
            trail["high"] - trail["low"],
            (trail["high"] - prev_c).abs(),
            (trail["low"] - prev_c).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr14 = float(tr.tail(14).mean()) if len(tr) >= 14 else None

    return {
        "week52_high": hi,
        "week52_low": lo,
        "week52_high_date": hi_date,
        "week52_low_date": lo_date,
        "week52_range_pos_pct": pos,  # 0=at low, 100=at high
        "from_52w_high_pct": from_hi,
        "from_52w_low_pct": from_lo,
        "avg_volume_20": avg_vol_20,
        "avg_volume_50": avg_vol_50,
        "last_volume": last_vol,
        "relative_volume": rvol,
        "ret_1w_pct": _ret(5),
        "ret_1m_pct": _ret(21),
        "ret_3m_pct": _ret(63),
        "ret_6m_pct": _ret(126),
        "ret_1y_pct": _ret(min(251, len(trail) - 1)) if len(trail) > 1 else None,
        "atr14": atr14,
        "trail_bars": len(trail),
    }


def fetch_market_context(symbol: str) -> dict[str, Any]:
    """Snapshot + trailing 52w profile for CLI table."""
    out: dict[str, Any] = {"symbol": symbol.upper()}
    try:
        out["snapshot"] = fetch_snapshot(symbol)
    except Exception as exc:  # noqa: BLE001
        out["snapshot"] = {"error": str(exc)}
    try:
        out["trailing"] = fetch_trailing_stats(symbol)
    except Exception as exc:  # noqa: BLE001
        out["trailing"] = {"error": str(exc)}
    return out


def normalize_compare(primary: pd.DataFrame, other: pd.DataFrame) -> pd.DataFrame:
    """Align comparison series and reindex as percent from first common point."""
    a = primary[["timestamp", "close"]].rename(columns={"close": "primary"})
    b = other[["timestamp", "close"]].rename(columns={"close": "compare"})
    # nearest merge on time for mismatched bars
    merged = pd.merge_asof(
        a.sort_values("timestamp"),
        b.sort_values("timestamp"),
        on="timestamp",
        direction="nearest",
        tolerance=pd.Timedelta("2D"),
    ).dropna()
    if merged.empty:
        return merged
    p0 = float(merged["primary"].iloc[0])
    c0 = float(merged["compare"].iloc[0])
    merged["primary_pct"] = (merged["primary"] / p0 - 1.0) * 100.0
    merged["compare_pct"] = (merged["compare"] / c0 - 1.0) * 100.0
    return merged
