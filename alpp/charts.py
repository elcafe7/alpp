"""Saved HTML chart gallery: scan dirs + natively parse ticker/indicator labels."""

from __future__ import annotations

import html as html_lib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .indicators import IndicatorSpec, parse_indicators
from .timeframes import ALIASES

# Plotly embeds titles as JSON strings (sometimes with \\u00b7 for ·)
_META_RE = re.compile(
    r"<!--\s*alpp-meta\s*:\s*(\{.*?\})\s*-->",
    re.DOTALL | re.IGNORECASE,
)
_TEXT_RE = re.compile(r'"text"\s*:\s*"((?:[^"\\]|\\.)*)"')
_NAME_RE = re.compile(r'"name"\s*:\s*"((?:[^"\\]|\\.)*)"')
_FILENAME_RE = re.compile(
    r"^(?P<sym>[A-Za-z0-9.\-]+)_"
    r"(?P<tf>[A-Za-z0-9]+)_"
    r"(?P<stamp>\d{8}-\d{6})\.html$",
    re.I,
)

# Chart style tokens that appear in titles / subtitles
_STYLES = {
    "candle",
    "hollow",
    "bar",
    "ohlc",
    "line",
    "area",
    "heikin",
    "heikin ashi",
    "fib",
    "fib candle",
    "fib hollow",
    "markers",
    "line+markers",
}

# Subpane indicator label patterns (from IndicatorSpec.label())
_IND_LABEL_RE = re.compile(
    r"^(?P<name>SMA|EMA|WMA|RSI|MACD|BBANDS|BB|DONCHIAN|STOCH|CCI|ROC|WILLR|"
    r"VOL_SMA|OBV|VWAP|CMF|ATR|HVOL)"
    r"(?::(?P<params>[\d,]+))?$",
    re.I,
)
_OVERLAY_COL_RE = re.compile(
    r"^(?P<name>SMA|EMA|WMA|VWAP|BB\s*(?:UPPER|MID|LOWER)|DC\s*(?:UPPER|MID|LOWER))"
    r"(?:\s+(?P<p>[\d\s]+))?$",
    re.I,
)


@dataclass
class ChartInfo:
    """Parsed view of a saved HTML chart for CLI display / re-run."""

    path: Path
    symbol: str = ""
    name: str = ""
    compare: str | None = None
    timeframe: str | None = None
    indicators: list[str] = field(default_factory=list)
    chart_style: str | None = None
    change_display: str | None = None
    mtime: float = 0.0
    source: str = ""  # meta | title | filename

    def label(self) -> str:
        """Native CLI label: tickers + range + indicators + style."""
        head = self.symbol or self.path.stem
        if self.compare:
            head = f"{head} vs {self.compare}"
        bits = [head]
        if self.timeframe:
            bits.append(self.timeframe.upper())
        if self.indicators:
            bits.append(", ".join(i.upper() for i in self.indicators))
        if self.chart_style and self.chart_style not in ("candle", "candles"):
            bits.append(self.chart_style.replace("_", " "))
        return " · ".join(bits)

    def indicator_specs(self) -> list[IndicatorSpec]:
        if not self.indicators:
            return []
        try:
            return parse_indicators(",".join(self.indicators))
        except SystemExit:
            return []

    def age_label(self) -> str:
        if not self.mtime:
            return "—"
        try:
            return datetime.fromtimestamp(self.mtime).strftime("%b %d %H:%M")
        except (OSError, ValueError, OverflowError):
            return "—"


def default_chart_dirs() -> list[Path]:
    """Locations where alpp (and local clones) drop HTML charts."""
    dirs: list[Path] = []
    env = os.environ.get("ALPP_OUT", "").strip()
    if env:
        dirs.append(Path(env).expanduser())
    dirs.append(Path.home() / "alpp" / "out")
    # repo / cwd conventions
    for rel in ("out", "html", "charts"):
        dirs.append(Path.cwd() / rel)
    # de-dupe preserving order
    seen: set[str] = set()
    out: list[Path] = []
    for d in dirs:
        try:
            key = str(d.resolve())
        except OSError:
            key = str(d)
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out


def scan_chart_dirs(
    dirs: Iterable[Path] | None = None,
    *,
    limit: int = 40,
) -> list[ChartInfo]:
    roots = list(dirs) if dirs is not None else default_chart_dirs()
    files: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        if not root.is_dir():
            continue
        try:
            candidates = sorted(
                root.glob("*.html"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            continue
        for p in candidates:
            try:
                key = str(p.resolve())
            except OSError:
                key = str(p)
            if key in seen:
                continue
            seen.add(key)
            files.append(p)
            if len(files) >= limit * 2:
                break

    charts = [parse_chart_file(p) for p in files]
    charts.sort(key=lambda c: c.mtime, reverse=True)
    return charts[:limit]


def parse_chart_file(path: Path) -> ChartInfo:
    path = Path(path).expanduser()
    info = ChartInfo(path=path)
    try:
        st = path.stat()
        info.mtime = st.st_mtime
    except OSError:
        pass

    # filename first (always available)
    _apply_filename(info, path.name)

    try:
        # titles live near the end of plotly HTML; read tail + head cheaply
        raw = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return info

    meta = _parse_meta_comment(raw)
    if meta:
        _apply_meta(info, meta)
        info.source = "meta"
        return info

    texts = _extract_plotly_texts(raw)
    names = _extract_plotly_names(raw)
    if texts:
        _apply_title_texts(info, texts)
        info.source = "title" if info.symbol else info.source or "filename"
    if names:
        _apply_trace_names(info, names)
        if not info.source:
            info.source = "title"
    elif not info.source:
        info.source = "filename"
    return info


def _parse_meta_comment(raw: str) -> dict[str, Any] | None:
    m = _META_RE.search(raw)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _apply_meta(info: ChartInfo, meta: dict[str, Any]) -> None:
    if meta.get("symbol"):
        info.symbol = str(meta["symbol"]).upper()
    if meta.get("name"):
        info.name = str(meta["name"])
    if meta.get("compare"):
        info.compare = str(meta["compare"]).upper()
    if meta.get("timeframe"):
        info.timeframe = str(meta["timeframe"]).lower()
    inds = meta.get("indicators") or []
    if isinstance(inds, str):
        inds = [x.strip() for x in inds.split(",") if x.strip()]
    info.indicators = [str(x) for x in inds]
    if meta.get("chart_style"):
        info.chart_style = str(meta["chart_style"]).lower()
    if meta.get("change_display"):
        info.change_display = str(meta["change_display"])


def _apply_filename(info: ChartInfo, name: str) -> None:
    m = _FILENAME_RE.match(name)
    if not m:
        # still try SYMBOL_tf_...
        parts = name.rsplit(".", 1)[0].split("_")
        if parts:
            info.symbol = parts[0].upper()
            if len(parts) >= 2 and (
                parts[1].lower() in ALIASES or _looks_like_tf(parts[1])
            ):
                info.timeframe = ALIASES.get(parts[1].lower(), parts[1].lower())
        return
    info.symbol = m.group("sym").upper()
    tf = m.group("tf").lower()
    info.timeframe = ALIASES.get(tf, tf)
    info.source = "filename"


def _looks_like_tf(s: str) -> bool:
    t = s.lower()
    return t in ALIASES or bool(re.fullmatch(r"\d+[dmyw]|ytd|max", t))


def _decode_plotly_str(s: str) -> str:
    try:
        s = json.loads(f'"{s}"')
    except json.JSONDecodeError:
        s = (
            s.replace("\\u00b7", "·")
            .replace("\\u003c", "<")
            .replace("\\u003e", ">")
            .replace("\\/", "/")
            .replace("\\n", "\n")
            .replace("<br>", "\n")
        )
    s = html_lib.unescape(s)
    s = s.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _extract_plotly_texts(raw: str) -> list[str]:
    out: list[str] = []
    for m in _TEXT_RE.finditer(raw):
        s = _decode_plotly_str(m.group(1))
        if len(s) >= 2:
            out.append(s)
    return out


def _extract_plotly_names(raw: str) -> list[str]:
    """Trace legend names (SMA 20, RSI, price symbol, compare symbol)."""
    out: list[str] = []
    for m in _NAME_RE.finditer(raw):
        s = _decode_plotly_str(m.group(1))
        if len(s) >= 2:
            out.append(s)
    return out


def _apply_trace_names(info: ChartInfo, names: list[str]) -> None:
    """Pull overlay / subpane indicator keys from Plotly trace names."""
    skip = {
        "volume",
        "hist",
        "signal",
        "%k",
        "%d",
        "macd",
        "open",
        "high",
        "low",
        "close",
    }
    for name in names:
        n = name.strip()
        if not n:
            continue
        low = n.lower()
        if low in skip:
            continue
        # price series named after the ticker itself
        if info.symbol and n.upper() == info.symbol.upper():
            continue
        if info.compare and n.upper() == info.compare.upper():
            continue
        if re.fullmatch(r"[A-Z0-9.\-]{1,12}", n.upper()) and n.upper() == n:
            # bare ticker in legend (compare pane) — not an indicator
            continue
        before = len(info.indicators)
        _parse_overlay_tokens(info, n)
        # also try ind label form
        compact = n.replace(" ", "")
        m = _IND_LABEL_RE.match(compact)
        if m:
            key = _normalize_ind_key(m.group("name"), m.group("params"))
            if key and key.lower() not in {x.lower() for x in info.indicators}:
                info.indicators.append(key)
        elif len(info.indicators) == before:
            # "SMA 20" style already handled by overlay tokens
            pass

    # dedupe
    seen: set[str] = set()
    deduped: list[str] = []
    for i in info.indicators:
        k = i.lower()
        if k in seen:
            continue
        seen.add(k)
        deduped.append(i)
    info.indicators = deduped


def _apply_title_texts(info: ChartInfo, texts: list[str]) -> None:
    """
    Understand plotly titles natively.

    Main title forms:
      SYMBOL · Company Name
      SYMBOL · Company · style
      SYMBOL · Company\\n TF · change · last $ · overlays · bar · style

    Subplot titles:
      SYMBOL · style | MACD:12,26,9 | RSI:14 | SYMBOL vs COMPARE
    """
    main = _pick_main_title(texts)
    if main:
        _parse_main_title(info, main)

    for t in texts:
        _parse_subplot_or_vs(info, t)
        _parse_overlay_tokens(info, t)

    # dedupe indicators preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for i in info.indicators:
        k = i.lower()
        if k in seen:
            continue
        seen.add(k)
        deduped.append(i)
    info.indicators = deduped


def _pick_main_title(texts: list[str]) -> str | None:
    # Prefer long titles with · and a company-ish second part
    scored: list[tuple[int, str]] = []
    for t in texts:
        if "·" not in t and " vs " not in t.lower():
            continue
        score = len(t)
        if re.search(r"\b(YTD|1D|5D|1M|3M|6M|1Y|2Y|5Y|MAX)\b", t, re.I):
            score += 200
        if "last $" in t.lower() or "+$" in t or "-$" in t:
            score += 100
        if " vs " in t.lower():
            score += 40
        scored.append((score, t))
    if not scored:
        # fallback: first SYMBOL · something short (subplot header)
        for t in texts:
            if "·" in t:
                return t
        return texts[0] if texts else None
    scored.sort(key=lambda x: -x[0])
    return scored[0][1]


def _parse_main_title(info: ChartInfo, title: str) -> None:
    # Split primary line vs subtitle if both present
    # After tag strip, often: "SYM · Name TF · rest" or "SYM · Name · style TF · rest"
    # Filename already set symbol; refine from head.
    head, *rest = [p.strip() for p in title.split("·")]
    if head:
        # "AAPL" or "AAPL vs SPY" unlikely in main head
        m = re.match(r"^([A-Z0-9.\-]{1,12})\b", head.upper())
        if m:
            info.symbol = m.group(1)

    # company name = second chunk if not a style / tf / change
    if len(rest) >= 1:
        maybe_name = rest[0]
        if not _is_style(maybe_name) and not _looks_like_tf(maybe_name.split()[0] if maybe_name else ""):
            if not re.search(r"[%$]|last\s*\$", maybe_name, re.I):
                # may include style as third: Name still ok if long
                if len(maybe_name) > 2 and not _IND_LABEL_RE.match(maybe_name):
                    info.name = maybe_name

    # scan all · segments
    for part in [head, *rest]:
        _ingest_segment(info, part)

    # full-string TF
    for m in re.finditer(r"\b(YTD|MAX|1D|5D|1M|3M|6M|1Y|2Y|5Y|\d+[DWMY])\b", title, re.I):
        info.timeframe = ALIASES.get(m.group(1).lower(), m.group(1).lower())
        break

    # vs COMPARE in subtitle change bit
    m = re.search(r"\bvs\s+([A-Z0-9.\-]{1,12})\b", title, re.I)
    if m:
        info.compare = m.group(1).upper()


def _parse_subplot_or_vs(info: ChartInfo, text: str) -> None:
    t = text.strip()
    # "AAPL vs SPY" or "% rebased · AAPL vs SPY" or "AAPL vs SPY"
    m = re.search(r"\b([A-Z0-9.\-]{1,12})\s+vs\s+([A-Z0-9.\-]{1,12})\b", t, re.I)
    if m:
        if not info.symbol:
            info.symbol = m.group(1).upper()
        info.compare = m.group(2).upper()
        return

    # subplot indicator title e.g. MACD:12,26,9
    m = _IND_LABEL_RE.match(t.replace(" ", ""))
    if m:
        key = _normalize_ind_key(m.group("name"), m.group("params"))
        if key:
            info.indicators.append(key)
        return

    # "SYMBOL · line" price pane title
    if "·" in t:
        left, right = [x.strip() for x in t.split("·", 1)]
        if re.fullmatch(r"[A-Za-z0-9.\-]{1,12}", left):
            if not info.symbol:
                info.symbol = left.upper()
            if _is_style(right):
                info.chart_style = _norm_style(right)


def _parse_overlay_tokens(info: ChartInfo, text: str) -> None:
    # subtitle overlay list: "SMA 20, EMA 50" or "SMA_20"
    for part in re.split(r"[,·|]", text):
        part = part.strip()
        if not part:
            continue
        compact = part.replace(" ", "_").upper()
        m = re.match(
            r"^(SMA|EMA|WMA|VWAP|ATR|RSI|OBV|CMF|CCI|ROC|WILLR|HVOL)_?(\d+(?:_\d+)*)?$",
            compact,
            re.I,
        )
        if m:
            key = _normalize_ind_key(m.group(1), (m.group(2) or "").replace("_", ","))
            if key and key not in {x.lower() for x in info.indicators}:
                # store canonical lower keys like sma:20
                info.indicators.append(key)
            continue
        m = re.match(r"^(BB|BBANDS|DONCHIAN|DC|STOCH|MACD)_?([\d,_]+)?$", compact, re.I)
        if m:
            name = m.group(1)
            if name.upper() == "DC":
                name = "donchian"
            if name.upper() == "BB":
                name = "bbands"
            key = _normalize_ind_key(name, (m.group(2) or "").replace("_", ","))
            if key:
                info.indicators.append(key)


def _ingest_segment(info: ChartInfo, part: str) -> None:
    p = part.strip()
    if not p:
        return
    if _is_style(p):
        info.chart_style = _norm_style(p)
        return
    # "1Day" / "5Min" bar size — ignore
    if re.fullmatch(r"\d+\s*(Day|Min|Hour|Week|Month)s?", p, re.I):
        return
    if re.fullmatch(r"last\s*\$[\d,.]+", p, re.I):
        return
    if re.search(r"[%$]", p) and re.search(r"\d", p):
        return
    # overlay blob "SMA 20, EMA 50"
    if re.search(r"\b(SMA|EMA|WMA|VWAP|RSI|MACD|ATR)\b", p, re.I):
        _parse_overlay_tokens(info, p)


def _is_style(s: str) -> bool:
    key = s.strip().lower().replace("-", " ").replace("_", " ")
    return key in _STYLES or key.replace(" ", "_") in {
        "fib_hollow",
        "fib_candle",
        "heikin_ashi",
    }


def _norm_style(s: str) -> str:
    key = s.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "ohlc": "bar",
        "heikin_ashi": "heikin",
        "fib_candle": "fib",
        "line+markers": "markers",
        "line_markers": "markers",
    }
    return aliases.get(key, key)


def _normalize_ind_key(name: str, params: str | None) -> str | None:
    n = name.lower().replace(" ", "_")
    aliases = {
        "bb": "bbands",
        "dc": "donchian",
        "donchian": "donchian",
        "volsma": "vol_sma",
        "volume_sma": "vol_sma",
        "histvol": "hvol",
        "williams": "willr",
        "stochastic": "stoch",
    }
    n = aliases.get(n, n)
    # strip band side prefixes wrongly captured
    if n.startswith("bb_"):
        n = "bbands"
    if n.startswith("dc_"):
        n = "donchian"
    params = (params or "").strip(" ,")
    if params:
        # bb upper mid lower are not separate indicators — map to bbands
        if n in ("bb_upper", "bb_mid", "bb_lower"):
            n = "bbands"
        return f"{n}:{params}" if ":" not in n else n
    defaults = {
        "rsi": "rsi:14",
        "sma": "sma:20",
        "ema": "ema:20",
        "wma": "wma:20",
        "macd": "macd:12,26,9",
        "bbands": "bbands:20,2",
        "donchian": "donchian:20",
        "stoch": "stoch:14,3",
        "atr": "atr:14",
        "cci": "cci:20",
        "roc": "roc:12",
        "willr": "willr:14",
        "vol_sma": "vol_sma:20",
        "cmf": "cmf:20",
        "hvol": "hvol:20",
        "obv": "obv",
        "vwap": "vwap",
    }
    return defaults.get(n, n)


def meta_comment(
    *,
    symbol: str,
    name: str = "",
    timeframe: str = "ytd",
    indicators: list[str] | None = None,
    compare: str | None = None,
    chart_style: str = "candle",
    change_display: str = "both",
) -> str:
    """HTML comment embedded after write so future scans are exact."""
    payload = {
        "symbol": symbol.upper(),
        "name": name,
        "timeframe": timeframe.lower(),
        "indicators": list(indicators or []),
        "compare": compare.upper() if compare else None,
        "chart_style": chart_style,
        "change_display": change_display,
        "alpp": True,
    }
    return f"<!-- alpp-meta: {json.dumps(payload, separators=(',', ':'))} -->\n"
