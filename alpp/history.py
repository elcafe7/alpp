"""Persistent session history: tickers, compares, indicators, chart prefs."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .indicators import IndicatorSpec, parse_indicators

HISTORY_DIR = Path.home() / ".config" / "alpp"
HISTORY_FILE = HISTORY_DIR / "history.json"
MAX_RUNS = 40
MAX_TICKERS = 30


@dataclass
class HistoryRun:
    """One chart session the user completed."""

    symbol: str
    timeframe: str = "ytd"
    indicators: list[str] = field(default_factory=list)
    compare: str | None = None
    chart_style: str | None = None
    change_display: str | None = None
    html: str | None = None
    ts: str = ""

    def label(self) -> str:
        """CLI-friendly one-liner: tickers + TF + overlays."""
        parts = [self.symbol.upper()]
        if self.compare:
            parts[0] = f"{self.symbol.upper()} vs {self.compare.upper()}"
        bits = [parts[0], self.timeframe.upper()]
        if self.indicators:
            bits.append(", ".join(i.upper() for i in self.indicators))
        if self.chart_style and self.chart_style != "candle":
            bits.append(self.chart_style)
        return " · ".join(bits)

    def indicator_specs(self) -> list[IndicatorSpec]:
        if not self.indicators:
            return []
        try:
            return parse_indicators(",".join(self.indicators))
        except SystemExit:
            return []

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HistoryRun:
        inds = data.get("indicators") or []
        if isinstance(inds, str):
            inds = [x.strip() for x in inds.split(",") if x.strip()]
        return cls(
            symbol=str(data.get("symbol") or "").upper(),
            timeframe=str(data.get("timeframe") or "ytd").lower(),
            indicators=[str(x) for x in inds],
            compare=(str(data["compare"]).upper() if data.get("compare") else None),
            chart_style=data.get("chart_style"),
            change_display=data.get("change_display"),
            html=data.get("html"),
            ts=str(data.get("ts") or ""),
        )


def history_path() -> Path:
    override = os.environ.get("ALPP_HISTORY", "").strip()
    if override:
        return Path(override).expanduser()
    return HISTORY_FILE


def _empty() -> dict[str, Any]:
    return {"version": 1, "runs": [], "tickers": []}


def load_history() -> dict[str, Any]:
    path = history_path()
    if not path.is_file():
        return _empty()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    data.setdefault("version", 1)
    data.setdefault("runs", [])
    data.setdefault("tickers", [])
    return data


def save_history(data: dict[str, Any]) -> Path:
    path = history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def list_runs(limit: int = 12) -> list[HistoryRun]:
    data = load_history()
    runs = [HistoryRun.from_dict(r) for r in data.get("runs") or [] if r]
    return runs[:limit]


def recent_tickers(limit: int = 12) -> list[str]:
    data = load_history()
    out: list[str] = []
    for t in data.get("tickers") or []:
        s = str(t).strip().upper()
        if s and s not in out:
            out.append(s)
        if len(out) >= limit:
            break
    if len(out) < limit:
        for run in list_runs(limit=MAX_RUNS):
            for s in (run.symbol, run.compare):
                if s and s not in out:
                    out.append(s)
                if len(out) >= limit:
                    return out
    return out


def last_indicators_for(symbol: str | None = None) -> list[str]:
    """Most recent indicator set, optionally matching symbol."""
    want = (symbol or "").upper()
    for run in list_runs(limit=MAX_RUNS):
        if want and run.symbol != want:
            continue
        if run.indicators:
            return list(run.indicators)
    if want:
        for run in list_runs(limit=MAX_RUNS):
            if run.indicators:
                return list(run.indicators)
    return []


def record_run(
    *,
    symbol: str,
    timeframe: str,
    indicators: list[IndicatorSpec] | list[str] | None = None,
    compare: str | None = None,
    chart_style: str | None = None,
    change_display: str | None = None,
    html: Path | str | None = None,
) -> HistoryRun:
    """Prepend a run and refresh recent-ticker list."""
    ind_keys: list[str] = []
    if indicators:
        for item in indicators:
            if isinstance(item, IndicatorSpec):
                ind_keys.append(item.key())
            else:
                ind_keys.append(str(item))

    run = HistoryRun(
        symbol=symbol.upper().strip(),
        timeframe=(timeframe or "ytd").lower().strip(),
        indicators=ind_keys,
        compare=compare.upper().strip() if compare else None,
        chart_style=chart_style,
        change_display=change_display,
        html=str(Path(html).expanduser()) if html else None,
        ts=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )

    data = load_history()
    runs = [run.to_dict()]
    for old in data.get("runs") or []:
        try:
            other = HistoryRun.from_dict(old)
        except Exception:
            continue
        # drop near-duplicate of same setup at head
        if (
            other.symbol == run.symbol
            and other.timeframe == run.timeframe
            and other.indicators == run.indicators
            and other.compare == run.compare
            and other.html == run.html
        ):
            continue
        runs.append(other.to_dict())
        if len(runs) >= MAX_RUNS:
            break
    data["runs"] = runs

    tickers: list[str] = [run.symbol]
    if run.compare:
        tickers.append(run.compare)
    for t in data.get("tickers") or []:
        s = str(t).strip().upper()
        if s and s not in tickers:
            tickers.append(s)
        if len(tickers) >= MAX_TICKERS:
            break
    data["tickers"] = tickers

    save_history(data)
    return run


def clear_history() -> None:
    save_history(_empty())
