"""Interactive timeframe picker: type, arrows, or number hotkeys."""

from __future__ import annotations

from dataclasses import dataclass

# Canonical menu order → hotkey digit (0 = max)
TIMEFRAME_MENU: list[tuple[str, str, str]] = [
    # (key, label, blurb)
    ("1", "1d", "today · 5-minute bars"),
    ("2", "5d", "5 sessions · 15-minute bars"),
    ("3", "1m", "1 month · hourly bars"),
    ("4", "3m", "3 months · daily bars"),
    ("5", "6m", "6 months · daily bars"),
    ("6", "ytd", "year-to-date · daily bars"),
    ("7", "1y", "1 year · daily bars"),
    ("8", "2y", "2 years · daily bars"),
    ("9", "5y", "5 years · weekly bars"),
    ("0", "max", "max history · weekly bars"),
]

DEFAULT_TF = "ytd"


@dataclass
class _PickerState:
    index: int
    typed: str = ""
    done: bool = False
    cancelled: bool = False
    result: str | None = None


def _default_index(default: str = DEFAULT_TF) -> int:
    default = default.lower().strip()
    for i, (_, label, _) in enumerate(TIMEFRAME_MENU):
        if label == default:
            return i
    return 5  # ytd


def _match_typed(typed: str) -> int | None:
    """Resolve typed text to a menu index, or None if incomplete/ambiguous."""
    from .timeframes import ALIASES

    t = typed.strip().lower()
    if not t:
        return None
    if t in ALIASES:
        label = ALIASES[t]
        for i, (_, lab, _) in enumerate(TIMEFRAME_MENU):
            if lab == label:
                return i
        return None
    # unique prefix on labels
    hits = [i for i, (_, lab, _) in enumerate(TIMEFRAME_MENU) if lab.startswith(t)]
    if len(hits) == 1:
        return hits[0]
    return None


def prompt_timeframe(
    default: str = DEFAULT_TF,
    *,
    console=None,
) -> str:
    """
    Pick a timeframe via:
      • ↑/↓ or j/k  navigate
      • 0-9         hotkeys
      • type        ytd, 1d, 6m, …
      • Enter       confirm selection (or accept unique typed match)
      • Esc/Ctrl-C  cancel → default
    """
    try:
        return _prompt_timeframe_pt(default)
    except Exception:
        # Fallback: rich prompt with printed menu
        return _prompt_timeframe_fallback(default, console=console)


def _prompt_timeframe_fallback(default: str = DEFAULT_TF, *, console=None) -> str:
    from rich.prompt import Prompt

    lines = ["[bold cyan]Timeframe[/]  [dim]number hotkey or type[/]"]
    for key, label, blurb in TIMEFRAME_MENU:
        mark = "·" if label != default else "★"
        lines.append(f"  [bold]{key}[/] {mark} [bold]{label:<4}[/]  [dim]{blurb}[/]")
    text = "\n".join(lines)
    if console is not None:
        console.print(text)
    else:
        from rich.console import Console

        Console().print(text)

    raw = Prompt.ask("Timeframe", default=default).strip().lower()
    # digit hotkey
    for key, label, _ in TIMEFRAME_MENU:
        if raw == key:
            return label
    from .timeframes import normalize_tf

    return normalize_tf(raw or default)


def _prompt_timeframe_pt(default: str = DEFAULT_TF) -> str:
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import HSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.styles import Style

    state = _PickerState(index=_default_index(default))

    def _select(i: int) -> None:
        state.index = i
        state.result = TIMEFRAME_MENU[i][1]
        state.done = True
        app.exit(result=state.result)

    def _render() -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        out.append(
            (
                "class:title",
                "Timeframe  ",
            )
        )
        out.append(
            (
                "class:hint",
                "↑↓/jk  ·  0-9 hotkey  ·  type  ·  Enter  ·  Esc=default\n",
            )
        )
        for i, (key, label, blurb) in enumerate(TIMEFRAME_MENU):
            selected = i == state.index
            prefix = "❯ " if selected else "  "
            style = "class:selected" if selected else "class:item"
            star = " ★" if label == default and not selected else ""
            out.append((style, f"{prefix}[{key}] {label:<4}  "))
            out.append(("class:meta" if not selected else "class:selected_meta", f"{blurb}{star}\n"))
        if state.typed:
            out.append(("class:typed", f"\n  type: {state.typed}_"))
            m = _match_typed(state.typed)
            if m is not None:
                out.append(("class:hint", f"  → {TIMEFRAME_MENU[m][1]}"))
            out.append(("", "\n"))
        else:
            out.append(("class:hint", f"\n  selected: {TIMEFRAME_MENU[state.index][1]}\n"))
        return out

    kb = KeyBindings()

    @kb.add("up")
    @kb.add("k")
    def _up(event) -> None:
        state.index = (state.index - 1) % len(TIMEFRAME_MENU)
        state.typed = ""

    @kb.add("down")
    @kb.add("j")
    def _down(event) -> None:
        state.index = (state.index + 1) % len(TIMEFRAME_MENU)
        state.typed = ""

    @kb.add("enter")
    def _enter(event) -> None:
        if state.typed:
            m = _match_typed(state.typed)
            if m is not None:
                _select(m)
                return
            # try normalize even if not in prefix set
            try:
                from .timeframes import normalize_tf

                label = normalize_tf(state.typed)
                for i, (_, lab, _) in enumerate(TIMEFRAME_MENU):
                    if lab == label:
                        _select(i)
                        return
            except SystemExit:
                state.typed = ""
                return
        _select(state.index)

    @kb.add("escape")
    @kb.add("c-c")
    def _esc(event) -> None:
        state.cancelled = True
        app.exit(result=default)

    # Number hotkeys
    for key, label, _ in TIMEFRAME_MENU:
        def _make(i_label: str, i_key: str):
            @kb.add(i_key)
            def _hot(event, lab=i_label) -> None:
                for i, (_, l, _) in enumerate(TIMEFRAME_MENU):
                    if l == lab:
                        _select(i)
                        return

            return _hot

        _make(label, key)

    # Typing letters / printable for text entry (not digits — those are hotkeys)
    @kb.add("<any>")
    def _any(event) -> None:
        data = event.data
        if not data or len(data) != 1:
            return
        # digits already bound as hotkeys
        if data.isdigit():
            return
        if data == "\x7f" or data == "\x08":  # handled below
            return
        if data.isalpha() or data in (".", "-", "_"):
            state.typed += data.lower()
            m = _match_typed(state.typed)
            if m is not None:
                state.index = m

    @kb.add("backspace")
    def _bs(event) -> None:
        if state.typed:
            state.typed = state.typed[:-1]
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

    control = FormattedTextControl(_render, focusable=True)
    window = Window(content=control, always_hide_cursor=True)
    layout = Layout(HSplit([window]))

    app = Application(
        layout=layout,
        key_bindings=kb,
        style=style,
        full_screen=False,
        mouse_support=False,
    )

    result = app.run()
    return result or default
