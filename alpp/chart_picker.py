"""Chart style picker for HTML output: type, number hotkeys, or arrows+Enter."""

from __future__ import annotations

from dataclasses import dataclass

# (hotkey, id, title, blurb)
CHART_MENU: list[tuple[str, str, str, str]] = [
    ("1", "candle", "Candle", "filled candlesticks (default)"),
    ("2", "hollow", "Hollow candle", "empty-body candles · classic charting"),
    ("3", "bar", "OHLC bar", "open-high-low-close bars"),
    ("4", "line", "Line", "close price line"),
    ("5", "area", "Area", "close price filled area"),
    ("6", "heikin", "Heikin-Ashi", "HA smoothed candles"),
    ("7", "fib", "Fib candle", "candles + Fibonacci retracements"),
    ("8", "fib_hollow", "Fib hollow", "hollow candles + Fibonacci"),
    ("9", "markers", "Line+markers", "close line with markers"),
]

DEFAULT_CHART = "candle"

ALIASES: dict[str, str] = {
    "c": "candle",
    "candle": "candle",
    "candles": "candle",
    "candlestick": "candle",
    "filled": "candle",
    "h": "hollow",
    "hollow": "hollow",
    "empty": "hollow",
    "empty_candle": "hollow",
    "empty-candle": "hollow",
    "ohlc": "bar",
    "bar": "bar",
    "bars": "bar",
    "l": "line",
    "line": "line",
    "a": "area",
    "area": "area",
    "ha": "heikin",
    "heikin": "heikin",
    "heiken": "heikin",
    "heikinashi": "heikin",
    "heikin-ashi": "heikin",
    "fib": "fib",
    "fibo": "fib",
    "fibonacci": "fib",
    "fib_candle": "fib",
    "fib-candle": "fib",
    "fib_hollow": "fib_hollow",
    "fibhollow": "fib_hollow",
    "markers": "markers",
    "line_markers": "markers",
    "dots": "markers",
}


@dataclass
class _State:
    index: int
    typed: str = ""


def normalize_chart(raw: str) -> str:
    key = raw.strip().lower().replace(" ", "_")
    if key in ALIASES:
        return ALIASES[key]
    # unique prefix on ids/titles
    hits = [
        cid
        for _, cid, title, _ in CHART_MENU
        if cid.startswith(key) or title.lower().startswith(key)
    ]
    if len(hits) == 1:
        return hits[0]
    ids = ", ".join(cid for _, cid, _, _ in CHART_MENU)
    raise SystemExit(f"Unknown chart style {raw!r}. Use: {ids}")


def _default_index(default: str = DEFAULT_CHART) -> int:
    try:
        want = normalize_chart(default)
    except SystemExit:
        want = DEFAULT_CHART
    for i, (_, cid, _, _) in enumerate(CHART_MENU):
        if cid == want:
            return i
    return 0


def _match_typed(typed: str) -> int | None:
    t = typed.strip().lower().replace(" ", "_")
    if not t:
        return None
    if t in ALIASES:
        want = ALIASES[t]
        for i, (_, cid, _, _) in enumerate(CHART_MENU):
            if cid == want:
                return i
    hits = [
        i
        for i, (_, cid, title, _) in enumerate(CHART_MENU)
        if cid.startswith(t) or title.lower().replace(" ", "_").startswith(t)
    ]
    if len(hits) == 1:
        return hits[0]
    # digit hotkey typed
    for i, (key, _, _, _) in enumerate(CHART_MENU):
        if t == key:
            return i
    return None


def prompt_chart_style(
    default: str = DEFAULT_CHART,
    *,
    console=None,
) -> str:
    """Pick chart style: ↑↓ · 1-9 hotkey · type · Enter."""
    try:
        return _prompt_pt(default)
    except Exception:
        return _prompt_fallback(default, console=console)


def _prompt_fallback(default: str = DEFAULT_CHART, *, console=None) -> str:
    from rich.prompt import Prompt

    lines = ["[bold cyan]Chart style[/]  [dim]number · type · or default[/]"]
    for key, cid, title, blurb in CHART_MENU:
        mark = "★" if cid == default else "·"
        lines.append(f"  [bold]{key}[/] {mark} [bold]{title:<14}[/]  [dim]{blurb}[/]")
    text = "\n".join(lines)
    if console is not None:
        console.print(text)
    else:
        from rich.console import Console

        Console().print(text)
    raw = Prompt.ask("Chart", default=default).strip()
    for key, cid, _, _ in CHART_MENU:
        if raw == key:
            return cid
    return normalize_chart(raw or default)


def _prompt_pt(default: str = DEFAULT_CHART) -> str:
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.styles import Style

    state = _State(index=_default_index(default))

    def _select(i: int) -> None:
        app.exit(result=CHART_MENU[i][1])

    def _render() -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        out.append(("class:title", "Chart style  "))
        out.append(
            (
                "class:hint",
                "↑↓/jk  ·  1-9 hotkey  ·  type  ·  Enter  ·  Esc=default\n",
            )
        )
        for i, (key, cid, title, blurb) in enumerate(CHART_MENU):
            selected = i == state.index
            prefix = "❯ " if selected else "  "
            style = "class:selected" if selected else "class:item"
            star = " ★" if cid == default and not selected else ""
            out.append((style, f"{prefix}[{key}] {title:<14}  "))
            out.append(
                (
                    "class:selected_meta" if selected else "class:meta",
                    f"{blurb}{star}\n",
                )
            )
        if state.typed:
            out.append(("class:typed", f"\n  type: {state.typed}_"))
            m = _match_typed(state.typed)
            if m is not None:
                out.append(("class:hint", f"  → {CHART_MENU[m][2]}"))
            out.append(("", "\n"))
        else:
            out.append(
                ("class:hint", f"\n  selected: {CHART_MENU[state.index][2]}\n")
            )
        return out

    kb = KeyBindings()

    @kb.add("up")
    @kb.add("k")
    def _up(event) -> None:
        state.index = (state.index - 1) % len(CHART_MENU)
        state.typed = ""

    @kb.add("down")
    @kb.add("j")
    def _down(event) -> None:
        state.index = (state.index + 1) % len(CHART_MENU)
        state.typed = ""

    @kb.add("enter")
    def _enter(event) -> None:
        if state.typed:
            m = _match_typed(state.typed)
            if m is not None:
                _select(m)
                return
            try:
                want = normalize_chart(state.typed)
                for i, (_, cid, _, _) in enumerate(CHART_MENU):
                    if cid == want:
                        _select(i)
                        return
            except SystemExit:
                state.typed = ""
                return
        _select(state.index)

    @kb.add("escape")
    @kb.add("c-c")
    def _esc(event) -> None:
        app.exit(result=default)

    for key, cid, _, _ in CHART_MENU:

        def _make(lab: str, k: str):
            @kb.add(k)
            def _hot(event, target=lab) -> None:
                for i, (_, c, _, _) in enumerate(CHART_MENU):
                    if c == target:
                        _select(i)
                        return

            return _hot

        _make(cid, key)

    @kb.add("backspace")
    def _bs(event) -> None:
        if state.typed:
            state.typed = state.typed[:-1]
            m = _match_typed(state.typed)
            if m is not None:
                state.index = m

    @kb.add("<any>")
    def _any(event) -> None:
        data = event.data
        if not data or len(data) != 1 or data.isdigit():
            return
        if data.isalpha() or data in ("_", "-", " "):
            state.typed += data.lower() if data != " " else "_"
            m = _match_typed(state.typed)
            if m is not None:
                state.index = m

    style = Style.from_dict(
        {
            "title": "bold ansicyan",
            "hint": "ansibrightblack",
            "item": "",
            "selected": "reverse bold ansicyan",
            "selected_meta": "reverse ansicyan",
            "meta": "ansibrightblack",
            "typed": "ansiyellow",
        }
    )

    app = Application(
        layout=Layout(
            Window(
                content=FormattedTextControl(_render, focusable=True),
                always_hide_cursor=True,
            )
        ),
        key_bindings=kb,
        style=style,
        full_screen=False,
        mouse_support=False,
    )
    return app.run() or default
