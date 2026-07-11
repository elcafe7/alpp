"""Indicator catalog, parse, and lightweight computations (no extra quant deps)."""

from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class IndicatorSpec:
    name: str
    params: tuple[int, ...] = ()

    def key(self) -> str:
        if self.params:
            return f"{self.name}:" + ",".join(str(p) for p in self.params)
        return self.name

    def label(self) -> str:
        return self.key().upper()


@dataclass(frozen=True)
class IndicatorDef:
    """Catalog entry for Miller-column picker + typeahead."""

    id: str
    title: str
    category: str
    subcategory: str
    spec: IndicatorSpec
    pane: str  # overlay | sub
    aliases: tuple[str, ...] = ()
    blurb: str = ""


def _def(
    title: str,
    category: str,
    subcategory: str,
    spec: IndicatorSpec,
    pane: str,
    *aliases: str,
    blurb: str = "",
) -> IndicatorDef:
    return IndicatorDef(
        id=spec.key(),
        title=title,
        category=category,
        subcategory=subcategory,
        spec=spec,
        pane=pane,
        aliases=aliases,
        blurb=blurb,
    )


# Hierarchical catalog (category → subcategory → indicator)
CATALOG: list[IndicatorDef] = [
    # --- Trend / MAs ---
    _def("SMA 9", "Trend", "Moving Averages", IndicatorSpec("sma", (9,)), "overlay", "sma9"),
    _def("SMA 20", "Trend", "Moving Averages", IndicatorSpec("sma", (20,)), "overlay", "sma20", "sma"),
    _def("SMA 50", "Trend", "Moving Averages", IndicatorSpec("sma", (50,)), "overlay", "sma50"),
    _def("SMA 100", "Trend", "Moving Averages", IndicatorSpec("sma", (100,)), "overlay", "sma100"),
    _def("SMA 200", "Trend", "Moving Averages", IndicatorSpec("sma", (200,)), "overlay", "sma200"),
    _def("EMA 9", "Trend", "Moving Averages", IndicatorSpec("ema", (9,)), "overlay", "ema9", "ema"),
    _def("EMA 12", "Trend", "Moving Averages", IndicatorSpec("ema", (12,)), "overlay", "ema12"),
    _def("EMA 21", "Trend", "Moving Averages", IndicatorSpec("ema", (21,)), "overlay", "ema21"),
    _def("EMA 50", "Trend", "Moving Averages", IndicatorSpec("ema", (50,)), "overlay", "ema50"),
    _def("EMA 200", "Trend", "Moving Averages", IndicatorSpec("ema", (200,)), "overlay", "ema200"),
    _def("WMA 20", "Trend", "Moving Averages", IndicatorSpec("wma", (20,)), "overlay", "wma20", "wma"),
    _def(
        "Bollinger Bands 20,2",
        "Trend",
        "Bands / Channels",
        IndicatorSpec("bbands", (20, 2)),
        "overlay",
        "bb",
        "bbands",
        "bollinger",
        blurb="mid ± 2σ",
    ),
    _def(
        "Bollinger Bands 20,1",
        "Trend",
        "Bands / Channels",
        IndicatorSpec("bbands", (20, 1)),
        "overlay",
        blurb="mid ± 1σ",
    ),
    _def(
        "Donchian 20",
        "Trend",
        "Bands / Channels",
        IndicatorSpec("donchian", (20,)),
        "overlay",
        "donchian",
        "dc",
    ),
    # --- Momentum ---
    _def("RSI 7", "Momentum", "RSI", IndicatorSpec("rsi", (7,)), "sub", "rsi7"),
    _def("RSI 14", "Momentum", "RSI", IndicatorSpec("rsi", (14,)), "sub", "rsi", "rsi14"),
    _def("RSI 21", "Momentum", "RSI", IndicatorSpec("rsi", (21,)), "sub", "rsi21"),
    _def(
        "MACD 12,26,9",
        "Momentum",
        "MACD",
        IndicatorSpec("macd", (12, 26, 9)),
        "sub",
        "macd",
    ),
    _def(
        "MACD 8,17,9",
        "Momentum",
        "MACD",
        IndicatorSpec("macd", (8, 17, 9)),
        "sub",
        "macd_fast",
    ),
    _def(
        "Stochastic 14,3",
        "Momentum",
        "Oscillators",
        IndicatorSpec("stoch", (14, 3)),
        "sub",
        "stoch",
        "stochastic",
    ),
    _def(
        "CCI 20",
        "Momentum",
        "Oscillators",
        IndicatorSpec("cci", (20,)),
        "sub",
        "cci",
    ),
    _def(
        "ROC 12",
        "Momentum",
        "Oscillators",
        IndicatorSpec("roc", (12,)),
        "sub",
        "roc",
        "rateofchange",
    ),
    _def(
        "Williams %R 14",
        "Momentum",
        "Oscillators",
        IndicatorSpec("willr", (14,)),
        "sub",
        "willr",
        "williams",
    ),
    # --- Volume ---
    _def(
        "Volume SMA 20",
        "Volume",
        "Volume MAs",
        IndicatorSpec("vol_sma", (20,)),
        "sub",
        "volsma",
        "volume_sma",
    ),
    _def(
        "OBV",
        "Volume",
        "Flow",
        IndicatorSpec("obv", ()),
        "sub",
        "obv",
        "onbalance",
    ),
    _def(
        "VWAP",
        "Volume",
        "Flow",
        IndicatorSpec("vwap", ()),
        "overlay",
        "vwap",
        blurb="cumulative typical×vol",
    ),
    _def(
        "Chaikin MF 20",
        "Volume",
        "Flow",
        IndicatorSpec("cmf", (20,)),
        "sub",
        "cmf",
        "chaikin",
    ),
    # --- Volatility ---
    _def("ATR 14", "Volatility", "Range", IndicatorSpec("atr", (14,)), "sub", "atr", "atr14"),
    _def("ATR 7", "Volatility", "Range", IndicatorSpec("atr", (7,)), "sub", "atr7"),
    _def(
        "Historical Vol 20",
        "Volatility",
        "Range",
        IndicatorSpec("hvol", (20,)),
        "sub",
        "hvol",
        "histvol",
    ),
]


def catalog_categories() -> list[str]:
    seen: list[str] = []
    for d in CATALOG:
        if d.category not in seen:
            seen.append(d.category)
    return seen


def catalog_subcategories(category: str) -> list[str]:
    seen: list[str] = []
    for d in CATALOG:
        if d.category == category and d.subcategory not in seen:
            seen.append(d.subcategory)
    return seen


def catalog_items(category: str, subcategory: str) -> list[IndicatorDef]:
    return [d for d in CATALOG if d.category == category and d.subcategory == subcategory]


def search_catalog(query: str, limit: int = 20) -> list[IndicatorDef]:
    q = query.strip().lower()
    if not q:
        return []
    scored: list[tuple[int, IndicatorDef]] = []
    for d in CATALOG:
        hay = " ".join(
            [
                d.id,
                d.title,
                d.category,
                d.subcategory,
                d.spec.name,
                *d.aliases,
            ]
        ).lower()
        if q == d.id or q in d.aliases or q == d.spec.name:
            scored.append((0, d))
        elif d.title.lower().startswith(q) or d.id.startswith(q):
            scored.append((1, d))
        elif q in hay:
            scored.append((2, d))
    scored.sort(key=lambda x: (x[0], x[1].title))
    # dedupe by id
    out: list[IndicatorDef] = []
    seen: set[str] = set()
    for _, d in scored:
        if d.id in seen:
            continue
        seen.add(d.id)
        out.append(d)
        if len(out) >= limit:
            break
    return out


_SPEC_RE = re.compile(
    r"^(?P<name>[a-z_]+)(?::(?P<p1>\d+)(?:,(?P<p2>\d+)(?:,(?P<p3>\d+))?)?)?$",
    re.I,
)

# Names that accept free-form params beyond catalog presets
_PARAM_KINDS = {
    "sma": (1, (20,)),
    "ema": (1, (20,)),
    "wma": (1, (20,)),
    "rsi": (1, (14,)),
    "macd": (3, (12, 26, 9)),
    "bbands": (2, (20, 2)),
    "bb": (2, (20, 2)),
    "donchian": (1, (20,)),
    "stoch": (2, (14, 3)),
    "cci": (1, (20,)),
    "roc": (1, (12,)),
    "willr": (1, (14,)),
    "vol_sma": (1, (20,)),
    "obv": (0, ()),
    "vwap": (0, ()),
    "cmf": (1, (20,)),
    "atr": (1, (14,)),
    "hvol": (1, (20,)),
}


def _split_indicator_list(raw: str) -> list[str]:
    """Split 'sma:20,rsi,macd:12,26,9' without breaking multi-param keys."""
    chunks = [p.strip() for p in raw.split(",")]
    merged: list[str] = []
    for chunk in chunks:
        if not chunk:
            continue
        # bare numeric fragment → continue previous name:p1,p2,…
        if chunk.isdigit() and merged and ":" in merged[-1]:
            merged[-1] = f"{merged[-1]},{chunk}"
        else:
            merged.append(chunk)
    return merged


def parse_indicators(raw: str | None) -> list[IndicatorSpec]:
    if not raw:
        return []
    out: list[IndicatorSpec] = []
    for part in _split_indicator_list(raw):
        part = part.strip()
        if not part:
            continue
        # catalog id / alias / title match first
        hits = search_catalog(part, limit=5)
        exact = [
            h
            for h in hits
            if part.lower() in (h.id, h.title.lower(), *h.aliases, h.spec.name)
            or part.lower() == h.id
        ]
        if len(exact) == 1:
            out.append(exact[0].spec)
            continue
        if hits and part.lower() == hits[0].id:
            out.append(hits[0].spec)
            continue

        m = _SPEC_RE.match(part)
        if not m:
            raise SystemExit(
                f"Unknown indicator {part!r}. "
                "Try: sma:20, rsi, macd, bbands, atr, stoch — or use the picker."
            )
        name = m.group("name").lower()
        if name == "bb":
            name = "bbands"
        if name not in _PARAM_KINDS:
            # try alias → catalog
            alias_hits = [d for d in CATALOG if name in d.aliases or name == d.spec.name]
            if alias_hits:
                out.append(alias_hits[0].spec)
                continue
            raise SystemExit(f"Unknown indicator {part!r}.")
        nparams, defaults = _PARAM_KINDS[name]
        p1, p2, p3 = m.group("p1"), m.group("p2"), m.group("p3")
        nums = [int(x) for x in (p1, p2, p3) if x]
        if nparams == 0:
            params: tuple[int, ...] = ()
        elif not nums:
            params = defaults
        else:
            # pad with defaults
            merged = list(defaults)
            for i, v in enumerate(nums):
                if i < len(merged):
                    merged[i] = v
                else:
                    merged.append(v)
            params = tuple(merged[: max(nparams, len(nums))])
        out.append(IndicatorSpec(name if name != "bb" else "bbands", params))
    return out


def apply_indicators(df: pd.DataFrame, specs: list[IndicatorSpec]) -> pd.DataFrame:
    if df.empty or not specs:
        return df
    out = df.copy()
    close = out["close"].astype(float)
    high = out["high"].astype(float) if "high" in out.columns else close
    low = out["low"].astype(float) if "low" in out.columns else close
    volume = (
        out["volume"].astype(float)
        if "volume" in out.columns
        else pd.Series(0.0, index=out.index)
    )
    typical = (high + low + close) / 3.0

    for spec in specs:
        name = spec.name
        if name == "sma":
            n = spec.params[0]
            out[f"sma_{n}"] = close.rolling(n, min_periods=n).mean()
        elif name == "ema":
            n = spec.params[0]
            out[f"ema_{n}"] = close.ewm(span=n, adjust=False).mean()
        elif name == "wma":
            n = spec.params[0]
            weights = pd.Series(range(1, n + 1), dtype=float)

            def _wma(x: pd.Series) -> float:
                return float((x * weights).sum() / weights.sum())

            out[f"wma_{n}"] = close.rolling(n, min_periods=n).apply(_wma, raw=False)
        elif name == "rsi":
            n = spec.params[0]
            delta = close.diff()
            gain = delta.clip(lower=0.0)
            loss = -delta.clip(upper=0.0)
            avg_gain = gain.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
            avg_loss = loss.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
            rs = avg_gain / avg_loss.replace(0, pd.NA)
            out[f"rsi_{n}"] = 100 - (100 / (1 + rs))
        elif name == "macd":
            fast, slow, signal = spec.params
            ema_fast = close.ewm(span=fast, adjust=False).mean()
            ema_slow = close.ewm(span=slow, adjust=False).mean()
            macd = ema_fast - ema_slow
            sig = macd.ewm(span=signal, adjust=False).mean()
            tag = f"{fast}_{slow}_{signal}"
            out[f"macd_{tag}"] = macd
            out[f"macd_signal_{tag}"] = sig
            out[f"macd_hist_{tag}"] = macd - sig
            # legacy keys for default 12,26,9
            if (fast, slow, signal) == (12, 26, 9):
                out["macd"] = macd
                out["macd_signal"] = sig
                out["macd_hist"] = macd - sig
        elif name == "bbands":
            n, k = spec.params
            mid = close.rolling(n, min_periods=n).mean()
            std = close.rolling(n, min_periods=n).std()
            out[f"bb_mid_{n}_{k}"] = mid
            out[f"bb_upper_{n}_{k}"] = mid + k * std
            out[f"bb_lower_{n}_{k}"] = mid - k * std
            if (n, k) == (20, 2):
                out[f"bb_mid_{n}"] = mid
                out[f"bb_upper_{n}"] = mid + k * std
                out[f"bb_lower_{n}"] = mid - k * std
        elif name == "donchian":
            n = spec.params[0]
            out[f"dc_upper_{n}"] = high.rolling(n, min_periods=n).max()
            out[f"dc_lower_{n}"] = low.rolling(n, min_periods=n).min()
            out[f"dc_mid_{n}"] = (out[f"dc_upper_{n}"] + out[f"dc_lower_{n}"]) / 2.0
        elif name == "stoch":
            n, k_smooth = spec.params
            lowest = low.rolling(n, min_periods=n).min()
            highest = high.rolling(n, min_periods=n).max()
            k_raw = 100 * (close - lowest) / (highest - lowest).replace(0, pd.NA)
            out[f"stoch_k_{n}"] = k_raw.rolling(k_smooth, min_periods=1).mean()
            out[f"stoch_d_{n}"] = out[f"stoch_k_{n}"].rolling(k_smooth, min_periods=1).mean()
        elif name == "cci":
            n = spec.params[0]
            tp = typical
            sma = tp.rolling(n, min_periods=n).mean()
            mad = tp.rolling(n, min_periods=n).apply(
                lambda x: float((x - x.mean()).abs().mean()), raw=False
            )
            out[f"cci_{n}"] = (tp - sma) / (0.015 * mad.replace(0, pd.NA))
        elif name == "roc":
            n = spec.params[0]
            out[f"roc_{n}"] = close.pct_change(n) * 100.0
        elif name == "willr":
            n = spec.params[0]
            highest = high.rolling(n, min_periods=n).max()
            lowest = low.rolling(n, min_periods=n).min()
            out[f"willr_{n}"] = -100 * (highest - close) / (highest - lowest).replace(
                0, pd.NA
            )
        elif name == "vol_sma":
            n = spec.params[0]
            out[f"vol_sma_{n}"] = volume.rolling(n, min_periods=1).mean()
            out["volume_plot"] = volume
        elif name == "obv":
            direction = close.diff().fillna(0).apply(
                lambda x: 1.0 if x > 0 else (-1.0 if x < 0 else 0.0)
            )
            out["obv"] = (direction * volume).cumsum()
        elif name == "vwap":
            cum_vol = volume.cumsum().replace(0, pd.NA)
            out["vwap"] = (typical * volume).cumsum() / cum_vol
        elif name == "cmf":
            n = spec.params[0]
            mfm = ((close - low) - (high - close)) / (high - low).replace(0, pd.NA)
            mfv = mfm.fillna(0) * volume
            out[f"cmf_{n}"] = (
                mfv.rolling(n, min_periods=n).sum()
                / volume.rolling(n, min_periods=n).sum().replace(0, pd.NA)
            )
        elif name == "atr":
            n = spec.params[0]
            prev_close = close.shift(1)
            tr = pd.concat(
                [
                    (high - low),
                    (high - prev_close).abs(),
                    (low - prev_close).abs(),
                ],
                axis=1,
            ).max(axis=1)
            out[f"atr_{n}"] = tr.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
        elif name == "hvol":
            n = spec.params[0]
            # annualized-ish from log returns std
            logret = (close / close.shift(1)).apply(
                lambda x: float(pd.NA) if pd.isna(x) or x <= 0 else __import__("math").log(x)
            )
            out[f"hvol_{n}"] = logret.rolling(n, min_periods=n).std() * (252**0.5) * 100.0
    return out


def overlay_columns(specs: list[IndicatorSpec]) -> list[str]:
    cols: list[str] = []
    for spec in specs:
        n = spec.name
        p = spec.params
        if n == "sma":
            cols.append(f"sma_{p[0]}")
        elif n == "ema":
            cols.append(f"ema_{p[0]}")
        elif n == "wma":
            cols.append(f"wma_{p[0]}")
        elif n == "bbands":
            period, k = p[0], p[1]
            if (period, k) == (20, 2):
                cols.extend([f"bb_upper_{period}", f"bb_mid_{period}", f"bb_lower_{period}"])
            else:
                cols.extend(
                    [
                        f"bb_upper_{period}_{k}",
                        f"bb_mid_{period}_{k}",
                        f"bb_lower_{period}_{k}",
                    ]
                )
        elif n == "donchian":
            cols.extend([f"dc_upper_{p[0]}", f"dc_mid_{p[0]}", f"dc_lower_{p[0]}"])
        elif n == "vwap":
            cols.append("vwap")
    return cols


def subpane_specs(specs: list[IndicatorSpec]) -> list[IndicatorSpec]:
    overlay_names = {"sma", "ema", "wma", "bbands", "donchian", "vwap"}
    return [s for s in specs if s.name not in overlay_names]


def subpane_kind(spec: IndicatorSpec) -> str:
    return spec.name
