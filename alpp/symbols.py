"""Nasdaq Trader symbol directory — unified JSON cache + live completion."""

from __future__ import annotations

import csv
import io
import json
import re
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

_NON_ALNUM = re.compile(r"[^A-Z0-9]+")
_WORD_SPLIT = re.compile(r"[\s\-/,.&+]+")

# Prefer FTP (HTTPS to this host often times out)
NASDAQ_LISTED_URL = "ftp://ftp.nasdaqtrader.com/symboldirectory/nasdaqlisted.txt"
OTHER_LISTED_URL = "ftp://ftp.nasdaqtrader.com/symboldirectory/otherlisted.txt"

DEFAULT_PATH = Path.home() / "alpp" / "data" / "symbols.json"

# Exchange codes in otherlisted.txt
EXCHANGE_MAP = {
    "A": "NYSE American",
    "N": "NYSE",
    "P": "NYSE Arca",
    "Z": "BATS",
    "V": "IEXG",
}


@dataclass(frozen=True)
class SymbolRow:
    symbol: str
    name: str
    exchange: str
    etf: bool
    test: bool
    source: str  # nasdaqlisted | otherlisted


def symbols_path() -> Path:
    return Path(
        __import__("os").environ.get("ALPP_SYMBOLS_PATH", str(DEFAULT_PATH))
    ).expanduser()


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _fetch(url: str, timeout: int = 60) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "alpp/0.2"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("latin-1", errors="replace")


def _parse_file_date(lines: list[str]) -> str | None:
    """Nasdaq files end with: File Creation Time: mmddyyyyhhmm"""
    for line in reversed(lines[-5:]):
        if "File Creation Time" in line:
            # e.g. File Creation Time: 0708202619:02|...
            part = line.split(":", 1)[-1].strip().split("|")[0].strip()
            return part or None
    return None


def _is_footer(row0: str) -> bool:
    return row0.startswith("File Creation Time") or not row0


def parse_nasdaqlisted(text: str) -> tuple[list[SymbolRow], str | None]:
    lines = text.splitlines()
    file_date = _parse_file_date(lines)
    reader = csv.DictReader(io.StringIO(text), delimiter="|")
    out: list[SymbolRow] = []
    for row in reader:
        sym = (row.get("Symbol") or "").strip().upper()
        if not sym or _is_footer(sym):
            continue
        test = (row.get("Test Issue") or "N").strip().upper() == "Y"
        etf = (row.get("ETF") or "N").strip().upper() == "Y"
        name = (row.get("Security Name") or "").strip()
        out.append(
            SymbolRow(
                symbol=sym,
                name=name,
                exchange="NASDAQ",
                etf=etf,
                test=test,
                source="nasdaqlisted",
            )
        )
    return out, file_date


def parse_otherlisted(text: str) -> tuple[list[SymbolRow], str | None]:
    lines = text.splitlines()
    file_date = _parse_file_date(lines)
    reader = csv.DictReader(io.StringIO(text), delimiter="|")
    out: list[SymbolRow] = []
    for row in reader:
        sym = (row.get("NASDAQ Symbol") or row.get("ACT Symbol") or "").strip().upper()
        if not sym or _is_footer(sym):
            continue
        test = (row.get("Test Issue") or "N").strip().upper() == "Y"
        etf = (row.get("ETF") or "N").strip().upper() == "Y"
        name = (row.get("Security Name") or "").strip()
        ex = (row.get("Exchange") or "").strip().upper()
        exchange = EXCHANGE_MAP.get(ex, ex or "OTHER")
        out.append(
            SymbolRow(
                symbol=sym,
                name=name,
                exchange=exchange,
                etf=etf,
                test=test,
                source="otherlisted",
            )
        )
    return out, file_date


def unify(rows: Iterable[SymbolRow], prefer: str = "nasdaqlisted") -> list[dict]:
    """Dedupe by symbol; prefer nasdaqlisted when both list the same ticker."""
    by: dict[str, SymbolRow] = {}
    for r in rows:
        if r.test:
            continue
        prev = by.get(r.symbol)
        if prev is None:
            by[r.symbol] = r
        elif prev.source != prefer and r.source == prefer:
            by[r.symbol] = r
    # stable sort
    ordered = sorted(by.values(), key=lambda x: x.symbol)
    return [asdict(r) for r in ordered]


def build_catalog(
    nasdaq_text: str,
    other_text: str,
    *,
    updated_at: str | None = None,
) -> dict:
    n_rows, n_date = parse_nasdaqlisted(nasdaq_text)
    o_rows, o_date = parse_otherlisted(other_text)
    symbols = unify([*n_rows, *o_rows])
    return {
        "format": "alpp.symbols.v1",
        "updated_at": updated_at or _now_iso(),
        "sources": {
            "nasdaqlisted": {
                "url": NASDAQ_LISTED_URL,
                "file_creation_time": n_date,
                "raw_count": len(n_rows),
            },
            "otherlisted": {
                "url": OTHER_LISTED_URL,
                "file_creation_time": o_date,
                "raw_count": len(o_rows),
            },
        },
        "count": len(symbols),
        "symbols": symbols,
    }


def save_catalog(catalog: dict, path: Path | None = None) -> Path:
    path = path or symbols_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def load_catalog(path: Path | None = None) -> dict | None:
    path = path or symbols_path()
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def update_symbols(path: Path | None = None) -> dict:
    """Download both lists, unify, write JSON. Returns catalog."""
    nasdaq_text = _fetch(NASDAQ_LISTED_URL)
    other_text = _fetch(OTHER_LISTED_URL)
    catalog = build_catalog(nasdaq_text, other_text)
    save_catalog(catalog, path)
    return catalog


def catalog_status(path: Path | None = None) -> dict:
    path = path or symbols_path()
    cat = load_catalog(path)
    if not cat:
        return {
            "path": str(path),
            "exists": False,
            "updated_at": None,
            "count": 0,
            "age_hours": None,
        }
    updated = cat.get("updated_at")
    age_hours = None
    if updated:
        try:
            ts = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            age_hours = (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0
        except ValueError:
            age_hours = None
    return {
        "path": str(path),
        "exists": True,
        "updated_at": updated,
        "count": cat.get("count") or len(cat.get("symbols") or []),
        "age_hours": age_hours,
        "sources": cat.get("sources"),
    }


def ensure_catalog(max_age_hours: float = 24 * 7, force: bool = False) -> dict:
    """Load catalog; refresh if missing or stale."""
    st = catalog_status()
    if (
        force
        or not st["exists"]
        or st["age_hours"] is None
        or st["age_hours"] > max_age_hours
    ):
        return update_symbols()
    cat = load_catalog()
    assert cat is not None
    return cat


class SymbolIndex:
    """In-memory index for lookup + prefix/fuzzy completion."""

    def __init__(self, catalog: dict):
        self.updated_at: str | None = catalog.get("updated_at")
        self.count: int = catalog.get("count") or 0
        self._by: dict[str, dict] = {}
        self._symbols: list[str] = []
        for row in catalog.get("symbols") or []:
            sym = str(row.get("symbol") or "").upper()
            if not sym:
                continue
            self._by[sym] = row
            self._symbols.append(sym)
        self._symbols.sort()

    @classmethod
    def load(cls, path: Path | None = None) -> SymbolIndex | None:
        cat = load_catalog(path)
        if not cat:
            return None
        return cls(cat)

    def get(self, symbol: str) -> dict | None:
        return self._by.get(symbol.strip().upper())

    def search(
        self,
        query: str,
        limit: int = 12,
        *,
        include_test: bool = False,
    ) -> list[dict]:
        """Ranked ticker search by symbol and company name.

        Scoring (high → low): exact symbol, compact match (BRKB→BRK.B),
        symbol prefix, name word prefix, multi-token name AND, name substring,
        symbol substring. Common stock slightly preferred over leveraged clutter.
        """
        raw = query.strip()
        if not raw:
            return []

        q_up = raw.upper()
        q_lo = raw.lower()
        q_compact = _NON_ALNUM.sub("", q_up)
        tokens = [t for t in _WORD_SPLIT.split(q_lo) if t and t not in ("inc", "corp", "the", "and", "of", "co")]

        scored: list[tuple[float, str, dict]] = []
        for sym, row in self._by.items():
            if not include_test and row.get("test"):
                continue
            name = row.get("name") or ""
            name_lo = name.lower()
            sym_compact = _NON_ALNUM.sub("", sym)
            score = 0.0

            if sym == q_up:
                score = 1000.0
            elif q_compact and sym_compact == q_compact:
                score = 980.0
            elif sym.startswith(q_up):
                score = 850.0 - min(len(sym), 40) * 0.5
            elif q_compact and len(q_compact) >= 2 and sym_compact.startswith(q_compact):
                score = 820.0 - min(len(sym_compact), 40) * 0.5
            elif tokens and all(
                any(w.startswith(tok) or tok in w for w in _WORD_SPLIT.split(name_lo))
                for tok in tokens
            ):
                # all query tokens hit some name word (e.g. "advanced micro")
                score = 700.0
                if name_lo.startswith(tokens[0]):
                    score += 40.0
            elif q_lo and any(
                w.startswith(q_lo) for w in _WORD_SPLIT.split(name_lo) if w
            ):
                score = 650.0
            elif q_lo and q_lo in name_lo:
                # earlier in name → better
                score = 500.0 - min(name_lo.find(q_lo), 80) * 0.5
            elif len(q_up) >= 2 and q_up in sym:
                score = 350.0
            elif q_compact and len(q_compact) >= 2 and q_compact in sym_compact:
                score = 320.0
            else:
                continue

            # Prefer plain equities / simple names over product soup
            if re.search(r"\bCommon Stock\b|\bCommon Shares\b", name, re.I):
                score += 25.0
            elif re.search(r"\bETF\b|\bETN\b", name, re.I):
                score -= 5.0
            if re.search(
                r"\b(2[Xx]|3[Xx]|-2[Xx]|-3[Xx]|Leveraged|Inverse|Bull|Bear|"
                r"Daily Target|Option Income|WeeklyPay)\b",
                name,
                re.I,
            ):
                score -= 35.0
            if row.get("etf") and score < 900:
                score -= 3.0

            scored.append((score, sym, row))

        scored.sort(key=lambda t: (-t[0], t[1]))
        return [row for _, _, row in scored[:limit]]


def make_completer(index: SymbolIndex):
    """prompt_toolkit completer: live suggestions while typing."""
    from prompt_toolkit.completion import Completer, Completion

    class TickerCompleter(Completer):
        def get_completions(self, document, complete_event):
            text = document.text_before_cursor.strip()
            if not text:
                return
            for row in index.search(text, limit=20):
                sym = row["symbol"]
                name = (row.get("name") or "")[:55]
                ex = row.get("exchange") or ""
                etf = " · ETF" if row.get("etf") else ""
                meta = f"{ex}{etf}  {name}".strip()
                yield Completion(
                    sym,
                    start_position=-len(document.text_before_cursor),
                    display=sym,
                    display_meta=meta,
                )

    return TickerCompleter()


def prompt_ticker_live(
    index: SymbolIndex | None,
    *,
    message: str = "Ticker",
    default: str = "",
) -> str:
    """
    Interactive ticker entry with ajax-style completions while typing.
    Falls back to plain input if prompt_toolkit unavailable or no index.
    """
    if index is None:
        from rich.prompt import Prompt

        return Prompt.ask(f"[bold cyan]{message}[/]", default=default).strip()

    try:
        from prompt_toolkit import prompt
        from prompt_toolkit.formatted_text import HTML
        from prompt_toolkit.shortcuts import CompleteStyle
    except ImportError:
        from rich.prompt import Prompt

        return Prompt.ask(f"[bold cyan]{message}[/]", default=default).strip()

    completer = make_completer(index)
    updated = index.updated_at or "unknown"
    result = prompt(
        HTML(
            f"<ansicyan><b>{message}</b></ansicyan> "
            f"<ansibrightblack>(type name or symbol · tab · {updated})</ansibrightblack>: "
        ),
        completer=completer,
        complete_while_typing=True,
        complete_style=CompleteStyle.COLUMN,
        default=default,
    )
    return result.strip()

