"""alpp CLI — rich interface with ticker name confirmation + live symbol complete."""

from __future__ import annotations

import argparse
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from . import __version__
from .creds import (
    ensure_credentials,
    import_alpaca_profiles,
    login_interactive,
    logout_profile,
    print_status,
    set_default_profile,
)
from .data import (
    AssetInfo,
    fetch_bars,
    fetch_market_context,
    normalize_compare,
    period_stats,
    resolve_asset,
    set_active_credentials,
)
from .chart_picker import DEFAULT_CHART, normalize_chart, prompt_chart_style
from .ind_picker import prompt_indicators
from .indicators import apply_indicators, parse_indicators
from .render import console, print_asset_confirm, print_banner, print_cli, write_html

CHANGE_DISPLAY_CHOICES = ("pct", "nominal", "both")
from .symbols import (
    SymbolIndex,
    catalog_status,
    ensure_catalog,
    prompt_ticker_live,
    symbols_path,
    update_symbols,
)
from .tf_picker import prompt_timeframe
from .timeframes import resolve_range


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="alpp",
        description=(
            "Alpaca chart CLI: TICKER + TIMEFRAME, optional indicators / comparison. "
            "Live ticker complete from Nasdaq lists; confirms semantic name."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  alpp                              # interactive (ticker complete + TF picker)
  alpp AAPL ytd
  alpp AAPL ytd --ind sma:20,rsi --vs SPY --html --open
  alpp AAPL ytd --html --chart hollow
  alpp symbols update               # refresh nasdaqlisted + otherlisted → JSON
  alpp symbols status
  alpp auth login                   # save keys to system keychain
  alpp auth import-alpaca           # one-time import from Alpaca CLI yaml
  alpp auth status

timeframes (interactive): ↑↓/jk · 0-9 hotkeys · or type ytd/1d/…
  1=1d 2=5d 3=1m 4=3m 5=6m 6=ytd 7=1y 8=2y 9=5y 0=max
compare: after ticker confirm · Compare vs another ticker? y/n · or --vs SPY
indicators: prompt Overlay indicators? y/n · Miller picker if y · or --ind sma:20,rsi
chart styles (--html): ↑↓ · 1-9 · type  candle|hollow|bar|line|area|heikin|fib|…
HTML change label: pct | nominal | both  (or --change)
""",
    )
    p.add_argument("ticker", nargs="?", default=None, help="Symbol, e.g. AAPL")
    p.add_argument(
        "timeframe",
        nargs="?",
        default=None,
        help="Range preset (default: ytd)",
    )
    p.add_argument(
        "-i",
        "--ind",
        "--indicator",
        dest="indicator",
        default=None,
        help="Comma-separated indicators",
    )
    p.add_argument(
        "--vs",
        "--compare",
        dest="compare",
        default=None,
        help="Comparison symbol (%% rebased), e.g. SPY",
    )
    p.add_argument(
        "--html",
        nargs="?",
        const="AUTO",
        default=None,
        help="Write HTML chart (optional path; default ~/alpp/out/)",
    )
    p.add_argument(
        "--chart",
        default=None,
        help=(
            "HTML chart style: candle, hollow, bar, line, area, heikin, "
            "fib, fib_hollow, markers (prompts if --html and omitted on TTY)"
        ),
    )
    p.add_argument(
        "--change",
        dest="change_display",
        choices=["pct", "percent", "nominal", "dollar", "both", "$", "%"],
        default=None,
        help="HTML title change label: pct | nominal | both (prompts with --html on TTY)",
    )
    p.add_argument("--open", action="store_true", help="Open HTML in browser")
    p.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip interactive ticker confirmation",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress summary table (still confirms unless -y)",
    )
    p.add_argument(
        "--refresh-symbols",
        action="store_true",
        help="Force-refresh symbol list before running",
    )
    p.add_argument(
        "-p",
        "--profile",
        default=None,
        help="Credential profile: paper, live, or custom name (default: saved default)",
    )
    p.add_argument("--version", action="version", version=f"alpp {__version__}")
    return p


def default_html_path(symbol: str, tf: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path.home() / "alpp" / "out" / f"{symbol.upper()}_{tf}_{stamp}.html"


def _load_index(force_refresh: bool = False) -> SymbolIndex | None:
    try:
        cat = ensure_catalog(max_age_hours=24 * 7, force=force_refresh)
        return SymbolIndex(cat)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]Symbol list unavailable:[/] {exc}")
        return SymbolIndex.load()


def _prompt_ticker(index: SymbolIndex | None) -> str:
    while True:
        raw = prompt_ticker_live(index, message="Ticker")
        if raw:
            return raw
        console.print("[yellow]Enter a symbol, e.g. AAPL (type to filter)[/]")


def _prompt_timeframe(default: str = "ytd") -> str:
    """Type, arrow-nav, or 0-9 hotkeys."""
    return prompt_timeframe(default=default, console=console)


def _normalize_change_display(raw: str | None) -> str:
    if not raw:
        return "both"
    key = raw.strip().lower()
    if key in ("pct", "percent", "%"):
        return "pct"
    if key in ("nominal", "dollar", "$", "usd"):
        return "nominal"
    if key in ("both", "all"):
        return "both"
    raise SystemExit(f"Unknown change display {raw!r}. Use: pct, nominal, both")


def _prompt_change_display(default: str = "both") -> str:
    """Ask how to show window performance on the HTML chart."""
    console.print(
        "[bold cyan]HTML change label[/]  "
        "[dim][1] percent ±%  ·  [2] nominal ±$  ·  [3] both[/]"
    )
    raw = Prompt.ask(
        "Show window change as",
        choices=["1", "2", "3", "pct", "percent", "%", "nominal", "dollar", "$", "both"],
        default="3" if default == "both" else ("1" if default == "pct" else "2"),
        show_choices=False,
    ).strip().lower()
    if raw in ("1", "pct", "percent", "%"):
        return "pct"
    if raw in ("2", "nominal", "dollar", "$"):
        return "nominal"
    return "both"


def confirm_asset(
    symbol: str,
    role: str = "ticker",
    auto_yes: bool = False,
    index: SymbolIndex | None = None,
) -> AssetInfo:
    # Local directory hint first (fast)
    local = index.get(symbol) if index else None
    if local:
        console.print(
            f"  [dim]list[/]  [bold]{local['symbol']}[/]  —  {local.get('name','')}  "
            f"[dim]({local.get('exchange','')}"
            f"{' · ETF' if local.get('etf') else ''})[/]"
        )

    with console.status(f"[cyan]Resolving {symbol.upper()} via Alpaca…[/]", spinner="dots"):
        asset = resolve_asset(symbol)
    print_asset_confirm(asset, role=role)

    if local and local.get("name") and local["name"] != asset.name:
        console.print(
            f"  [dim]note[/]  directory name differs from Alpaca: [cyan]{local['name']}[/]"
        )

    if auto_yes:
        return asset
    label = "Use this ticker?" if role == "ticker" else "Use this comparison?"
    if not Confirm.ask(label, default=True):
        raise SystemExit("Aborted.")
    return asset


def cmd_auth(argv: list[str]) -> int:
    """alpp auth login|status|logout|use"""
    print_banner()
    sub = argv[0] if argv else "status"
    if sub in ("-h", "--help", "help"):
        console.print(
            "Usage: [bold]alpp auth login[/] | [bold]import-alpaca[/] | "
            "[bold]status[/] | [bold]logout[/] | [bold]use PROFILE[/]"
        )
        return 0

    if sub in ("import-alpaca", "import", "import_alpaca"):
        return import_alpaca_profiles(console=console)

    if sub == "login":
        profile = "paper"
        i = 1
        while i < len(argv):
            arg = argv[i]
            if arg in ("--paper",):
                profile = "paper"
            elif arg in ("--live",):
                profile = "live"
            elif arg in ("--profile", "-p") and i + 1 < len(argv):
                i += 1
                profile = argv[i]
            elif not arg.startswith("-"):
                profile = arg
            i += 1
        login_interactive(profile=profile, console=console)
        return 0

    if sub in ("status", "info", "show"):
        return print_status(console=console)

    if sub in ("logout", "clear", "remove"):
        profile = None
        if len(argv) > 1 and not argv[1].startswith("-"):
            profile = argv[1]
        logout_profile(profile, console=console)
        return 0

    if sub in ("use", "switch", "default"):
        if len(argv) < 2:
            raise SystemExit("Usage: alpp auth use paper|live|PROFILE")
        set_default_profile(argv[1], console=console)
        return 0

    console.print(f"[red]Unknown auth subcommand:[/] {sub}")
    console.print(
        "Use: alpp auth login | import-alpaca | status | logout | use PROFILE"
    )
    return 2


def cmd_symbols(argv: list[str]) -> int:
    """alpp symbols update|status"""
    print_banner()
    sub = argv[0] if argv else "status"
    if sub in ("-h", "--help", "help"):
        console.print(
            "Usage: [bold]alpp symbols update[/] | [bold]alpp symbols status[/]"
        )
        return 0
    if sub == "update":
        with console.status(
            "[cyan]Downloading nasdaqlisted.txt + otherlisted.txt…[/]",
            spinner="dots",
        ):
            cat = update_symbols()
        _print_status_from_catalog(cat)
        console.print(f"[green]Updated[/] {symbols_path()}")
        return 0
    if sub in ("status", "info", "ls"):
        st = catalog_status()
        _print_status(st)
        return 0 if st["exists"] else 1
    console.print(f"[red]Unknown symbols subcommand:[/] {sub}")
    console.print("Use: alpp symbols update | alpp symbols status")
    return 2


def _print_status(st: dict) -> None:
    if not st["exists"]:
        console.print(
            Panel(
                f"[yellow]No symbol cache[/]\npath: {st['path']}\n"
                "Run: [bold]alpp symbols update[/]",
                border_style="yellow",
            )
        )
        return
    tbl = Table(show_header=False, box=None, padding=(0, 1))
    tbl.add_column(style="dim")
    tbl.add_column()
    tbl.add_row("path", st["path"])
    tbl.add_row("updated_at", str(st["updated_at"]))
    age = st.get("age_hours")
    if age is not None:
        tbl.add_row("age", f"{age:.1f} hours")
    tbl.add_row("symbols", str(st["count"]))
    sources = st.get("sources") or {}
    for key, meta in sources.items():
        fct = (meta or {}).get("file_creation_time") or "—"
        raw = (meta or {}).get("raw_count", "—")
        tbl.add_row(key, f"file_time={fct}  raw_rows={raw}")
    console.print(Panel(tbl, title="[bold]Symbol directory[/]", border_style="cyan"))


def _print_status_from_catalog(cat: dict) -> None:
    _print_status(
        {
            "path": str(symbols_path()),
            "exists": True,
            "updated_at": cat.get("updated_at"),
            "count": cat.get("count"),
            "age_hours": 0.0,
            "sources": cat.get("sources"),
        }
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # Subcommands
    if argv and argv[0] in ("auth", "login", "credentials", "creds"):
        return cmd_auth(argv[1:])

    if argv and argv[0] in ("symbols", "symbol", "tickers", "sym"):
        return cmd_symbols(argv[1:])

    args = build_parser().parse_args(argv)
    print_banner()

    creds = ensure_credentials(profile=args.profile, console=console)
    set_active_credentials(creds)
    if creds.backend != "environment":
        mode = "paper" if creds.paper else "live"
        console.print(
            f"  [dim]auth[/]  {creds.profile} ({mode})  "
            f"[dim]· {creds.backend}[/]"
        )

    interactive = args.ticker is None
    force = args.refresh_symbols

    if interactive or force:
        with console.status("[cyan]Loading symbol directory…[/]", spinner="dots"):
            index = _load_index(force_refresh=force)
    else:
        index = SymbolIndex.load()

    if index:
        age = ""
        st = catalog_status()
        if st.get("updated_at"):
            age = f"  ·  updated {st['updated_at']}"
        console.print(f"  [dim]directory[/]  {index.count:,} symbols{age}")

    ticker_raw = args.ticker or _prompt_ticker(index)
    asset = confirm_asset(ticker_raw, role="ticker", auto_yes=args.yes, index=index)

    compare_asset: AssetInfo | None = None
    compare_raw = args.compare
    if interactive and not compare_raw and sys.stdin.isatty():
        console.print()
        if Confirm.ask("Compare vs another ticker?", default=False):
            compare_raw = prompt_ticker_live(index, message="Compare vs") or None
            if compare_raw == "":
                compare_raw = None
    if compare_raw:
        compare_asset = confirm_asset(
            compare_raw, role="compare", auto_yes=args.yes, index=index
        )
        if compare_asset.symbol == asset.symbol:
            raise SystemExit("Comparison symbol must differ from ticker")
        console.print(
            f"  [dim]compare[/]  [bold]{compare_asset.symbol}[/]  —  {compare_asset.name}"
        )

    tf_raw = args.timeframe
    if not tf_raw:
        # Always offer picker when TF omitted (type / arrows / 0-9)
        if sys.stdin.isatty():
            tf_raw = _prompt_timeframe("ytd")
        else:
            tf_raw = "ytd"

    rng = resolve_range(tf_raw)
    console.print(
        f"  [dim]range[/]  [bold]{rng.label.upper()}[/]  →  {rng.bar}  ({rng.description})"
    )

    if args.indicator is not None:
        # Explicit --ind: use as-is (empty string => none)
        indicators = parse_indicators(args.indicator)
    elif interactive and sys.stdin.isatty():
        console.print()
        # Default path is clean price chart; only open Miller picker if requested
        if Confirm.ask("Overlay indicators?", default=False):
            indicators = prompt_indicators(console=console)
            if indicators:
                console.print(
                    f"  [dim]inds[/]  {', '.join(s.label() for s in indicators)}"
                )
            else:
                console.print("  [dim]inds[/]  (none)")
        else:
            indicators = []
            console.print("  [dim]inds[/]  (price only)")
    else:
        indicators = []

    with console.status(
        f"[cyan]Fetching {asset.symbol} bars + profile…[/]", spinner="dots"
    ):
        df = fetch_bars(asset.symbol, rng)
        df = apply_indicators(df, indicators)
        stats = period_stats(df)
        context = fetch_market_context(asset.symbol)

    compare_df = None
    compare_stats = None
    compare_context = None
    rel = None
    if compare_asset:
        with console.status(
            f"[cyan]Fetching {compare_asset.symbol} bars + profile…[/]",
            spinner="dots",
        ):
            compare_df = fetch_bars(compare_asset.symbol, rng)
            compare_stats = period_stats(compare_df)
            rel = normalize_compare(df, compare_df)
            compare_context = fetch_market_context(compare_asset.symbol)

    if not args.quiet:
        print_cli(
            asset,
            rng,
            stats,
            indicators,
            compare_asset,
            compare_stats,
            rel,
            context=context,
            compare_context=compare_context,
        )

    # HTML decision after the performance / profile tables
    html_opt = args.html
    if interactive and html_opt is None and sys.stdin.isatty():
        if Confirm.ask("Write HTML chart?", default=False):
            html_opt = "AUTO"

    chart_style = DEFAULT_CHART
    change_display = "both"
    if html_opt is not None:
        if args.chart:
            chart_style = normalize_chart(args.chart)
        elif sys.stdin.isatty() and not args.yes:
            console.print()
            chart_style = prompt_chart_style(DEFAULT_CHART, console=console)
            console.print(f"  [dim]chart[/]  [bold]{chart_style}[/]")
        elif args.chart is None and args.yes:
            chart_style = DEFAULT_CHART

        if args.change_display:
            change_display = _normalize_change_display(args.change_display)
        elif sys.stdin.isatty() and not args.yes:
            console.print()
            change_display = _prompt_change_display("both")
            console.print(f"  [dim]change[/]  [bold]{change_display}[/]")
        else:
            change_display = "both"

    if html_opt is not None:
        path = (
            default_html_path(asset.symbol, rng.label)
            if html_opt == "AUTO"
            else Path(html_opt)
        )
        with console.status(
            f"[cyan]Rendering HTML ({chart_style}, {change_display})…[/]",
            spinner="dots",
        ):
            written = write_html(
                path,
                asset,
                rng,
                df,
                stats,
                indicators,
                compare_asset,
                compare_df,
                rel,
                compare_stats,
                chart_style=chart_style,
                change_display=change_display,
            )
        console.print(
            f"  [bold]html[/]     [link=file://{written.resolve()}]{written}[/]  "
            f"[dim]({chart_style} · {change_display})[/]"
        )
        if args.open or (interactive and Confirm.ask("Open in browser?", default=True)):
            webbrowser.open(written.resolve().as_uri())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
