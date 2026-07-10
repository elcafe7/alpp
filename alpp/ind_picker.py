"""
Miller-column indicator picker (category | subcategory | indicator)
+ ajax-style typeahead jump.

Official-ish name: Miller columns / cascading column browser.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .indicators import (
    CATALOG,
    IndicatorDef,
    IndicatorSpec,
    catalog_categories,
    catalog_items,
    catalog_subcategories,
    search_catalog,
)


@dataclass
class _State:
    col: int = 0  # 0 category, 1 sub, 2 item, 3 type mode focus still 2
    cat_i: int = 0
    sub_i: int = 0
    item_i: int = 0
    typed: str = ""
    selected: list[IndicatorDef] = field(default_factory=list)
    filter_hits: list[IndicatorDef] = field(default_factory=list)
    filter_i: int = 0


def prompt_indicators(
    existing: list[IndicatorSpec] | None = None,
    *,
    console=None,
) -> list[IndicatorSpec]:
    """
    Interactive multi-select:
      ←/→     columns (category → sub → indicator)
      ↑/↓/jk  move within column
      Enter / → on leaf  toggle add
      Space    toggle leaf
      type     ajax filter → jump to matches
      Tab      jump to type/filter list
      d / Del  remove last selected
      Enter on empty type + no focus change when done?  → Ctrl-D or 'q' finish
      Ctrl-D / q / Esc(with none typed)  finish
    """
    try:
        return _prompt_pt(existing)
    except Exception:
        return _prompt_fallback(existing, console=console)


def _specs_from_defs(defs: list[IndicatorDef]) -> list[IndicatorSpec]:
    # preserve order, dedupe by key
    out: list[IndicatorSpec] = []
    seen: set[str] = set()
    for d in defs:
        k = d.spec.key()
        if k in seen:
            continue
        seen.add(k)
        out.append(d.spec)
    return out


def _defs_from_specs(specs: list[IndicatorSpec] | None) -> list[IndicatorDef]:
    if not specs:
        return []
    out: list[IndicatorDef] = []
    for s in specs:
        match = next((d for d in CATALOG if d.spec == s or d.spec.key() == s.key()), None)
        if match:
            out.append(match)
        else:
            out.append(
                IndicatorDef(
                    id=s.key(),
                    title=s.label(),
                    category="Custom",
                    subcategory="Parsed",
                    spec=s,
                    pane="sub",
                )
            )
    return out


def _prompt_fallback(
    existing: list[IndicatorSpec] | None,
    *,
    console=None,
) -> list[IndicatorSpec]:
    from rich.prompt import Prompt

    c = console
    if c is None:
        from rich.console import Console

        c = Console()
    c.print(
        "[bold cyan]Indicators[/]  [dim]type ids (sma:20,rsi,macd) comma-separated · empty skip[/]"
    )
    cats = catalog_categories()
    for cat in cats:
        subs = catalog_subcategories(cat)
        c.print(f"  [bold]{cat}[/]")
        for sub in subs:
            items = ", ".join(d.id for d in catalog_items(cat, sub))
            c.print(f"    [dim]{sub}:[/] {items}")
    raw = Prompt.ask("Indicators", default="").strip()
    if not raw:
        return list(existing or [])
    from .indicators import parse_indicators

    return parse_indicators(raw)


def _prompt_pt(existing: list[IndicatorSpec] | None) -> list[IndicatorSpec]:
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.styles import Style

    cats = catalog_categories()
    state = _State(selected=_defs_from_specs(existing))

    def _subs() -> list[str]:
        if not cats:
            return []
        return catalog_subcategories(cats[state.cat_i])

    def _items() -> list[IndicatorDef]:
        subs = _subs()
        if not subs:
            return []
        return catalog_items(cats[state.cat_i], subs[state.sub_i])

    def _clamp() -> None:
        state.cat_i = max(0, min(state.cat_i, len(cats) - 1))
        subs = _subs()
        state.sub_i = max(0, min(state.sub_i, max(len(subs) - 1, 0)))
        items = _items()
        state.item_i = max(0, min(state.item_i, max(len(items) - 1, 0)))
        if state.filter_hits:
            state.filter_i = max(0, min(state.filter_i, len(state.filter_hits) - 1))

    def _toggle(defn: IndicatorDef) -> None:
        ids = {d.id for d in state.selected}
        if defn.id in ids:
            state.selected = [d for d in state.selected if d.id != defn.id]
        else:
            state.selected.append(defn)

    def _jump_to_def(defn: IndicatorDef) -> None:
        try:
            state.cat_i = cats.index(defn.category)
        except ValueError:
            return
        subs = catalog_subcategories(defn.category)
        try:
            state.sub_i = subs.index(defn.subcategory)
        except ValueError:
            state.sub_i = 0
        items = catalog_items(defn.category, defn.subcategory)
        for i, it in enumerate(items):
            if it.id == defn.id:
                state.item_i = i
                break
        state.col = 2

    def _apply_type() -> None:
        state.filter_hits = search_catalog(state.typed, limit=12) if state.typed else []
        state.filter_i = 0
        if len(state.filter_hits) == 1:
            _jump_to_def(state.filter_hits[0])

    def _render() -> list[tuple[str, str]]:
        _clamp()
        out: list[tuple[str, str]] = []
        out.append(("class:title", "Indicators  "))
        out.append(
            (
                "class:hint",
                "Miller columns · ←/→ cols · ↑↓ · Space/Enter toggle · type to jump · q done · Esc clear type\n",
            )
        )

        # columns
        subs = _subs()
        items = _items()
        col_w = 18
        mid_w = 20
        right_w = 28

        # header
        h0 = "CATEGORY".ljust(col_w)
        h1 = "GROUP".ljust(mid_w)
        h2 = "INDICATOR".ljust(right_w)
        out.append(("class:header", f"  {h0} {h1} {h2}\n"))

        max_rows = max(len(cats), len(subs), len(items), 1)
        for row in range(max_rows):
            # category cell
            if row < len(cats):
                mark = "❯" if state.col == 0 and row == state.cat_i else " "
                sel = state.col == 0 and row == state.cat_i
                st = "class:sel" if sel else "class:cell"
                cell0 = f"{mark}{cats[row]}"[:col_w].ljust(col_w)
            else:
                st, cell0 = "class:cell", " " * col_w
            out.append((st if row < len(cats) else "class:cell", f"  {cell0} "))

            # sub cell
            if row < len(subs):
                mark = "❯" if state.col == 1 and row == state.sub_i else " "
                sel = state.col == 1 and row == state.sub_i
                st = "class:sel" if sel else "class:cell"
                cell1 = f"{mark}{subs[row]}"[:mid_w].ljust(mid_w)
            else:
                st, cell1 = "class:cell", " " * mid_w
            out.append((st if row < len(subs) else "class:cell", f"{cell1} "))

            # item cell
            if row < len(items):
                it = items[row]
                check = "✓" if any(s.id == it.id for s in state.selected) else " "
                mark = "❯" if state.col == 2 and row == state.item_i and not state.typed else " "
                sel = state.col == 2 and row == state.item_i and not state.filter_hits
                st = "class:sel" if sel else "class:cell"
                cell2 = f"{mark}{check}{it.title}"[:right_w].ljust(right_w)
                out.append((st, cell2))
            else:
                out.append(("class:cell", " " * right_w))
            out.append(("", "\n"))

        # typeahead panel
        if state.typed or state.filter_hits:
            out.append(("class:typed", f"\n  type: {state.typed}_\n"))
            if state.filter_hits:
                out.append(("class:hint", "  matches:\n"))
                for i, hit in enumerate(state.filter_hits):
                    st = "class:sel" if i == state.filter_i else "class:cell"
                    path = f"{hit.category} › {hit.subcategory} › {hit.title}"
                    check = "✓" if any(s.id == hit.id for s in state.selected) else " "
                    out.append((st, f"    {check}{hit.id:<16} {path}\n"))
            elif state.typed:
                out.append(("class:hint", "  (no matches)\n"))

        # selected strip
        if state.selected:
            names = ", ".join(d.title for d in state.selected)
            out.append(("class:picked", f"\n  selected: {names}\n"))
        else:
            out.append(("class:hint", "\n  selected: (none — skip with q)\n"))

        out.append(
            (
                "class:hint",
                "  [Space/Enter] toggle  [→] into column  [←] back  [q] done  [-] remove last\n",
            )
        )
        return out

    kb = KeyBindings()

    def _finish(event) -> None:
        app.exit(result=_specs_from_defs(state.selected))

    @kb.add("q")
    @kb.add("c-d")
    def _q(event) -> None:
        if state.typed:
            state.typed = ""
            state.filter_hits = []
            return
        _finish(event)

    @kb.add("escape")
    def _esc(event) -> None:
        if state.typed:
            state.typed = ""
            state.filter_hits = []
            return
        _finish(event)

    @kb.add("left")
    @kb.add("h")
    def _left(event) -> None:
        if state.filter_hits:
            state.filter_hits = []
            state.typed = ""
            return
        state.col = max(0, state.col - 1)

    @kb.add("right")
    @kb.add("l")
    def _right(event) -> None:
        if state.filter_hits:
            hit = state.filter_hits[state.filter_i]
            _jump_to_def(hit)
            state.typed = ""
            state.filter_hits = []
            return
        if state.col < 2:
            state.col += 1
            _clamp()
        else:
            # on leaf: toggle
            items = _items()
            if items:
                _toggle(items[state.item_i])

    @kb.add("up")
    @kb.add("k")
    def _up(event) -> None:
        if state.filter_hits:
            state.filter_i = (state.filter_i - 1) % len(state.filter_hits)
            return
        if state.col == 0:
            state.cat_i = (state.cat_i - 1) % len(cats)
            state.sub_i = 0
            state.item_i = 0
        elif state.col == 1:
            subs = _subs()
            if subs:
                state.sub_i = (state.sub_i - 1) % len(subs)
                state.item_i = 0
        else:
            items = _items()
            if items:
                state.item_i = (state.item_i - 1) % len(items)

    @kb.add("down")
    @kb.add("j")
    def _down(event) -> None:
        if state.filter_hits:
            state.filter_i = (state.filter_i + 1) % len(state.filter_hits)
            return
        if state.col == 0:
            state.cat_i = (state.cat_i + 1) % len(cats)
            state.sub_i = 0
            state.item_i = 0
        elif state.col == 1:
            subs = _subs()
            if subs:
                state.sub_i = (state.sub_i + 1) % len(subs)
                state.item_i = 0
        else:
            items = _items()
            if items:
                state.item_i = (state.item_i + 1) % len(items)

    @kb.add("enter")
    @kb.add(" ")
    def _toggle_key(event) -> None:
        if state.filter_hits:
            hit = state.filter_hits[state.filter_i]
            _toggle(hit)
            _jump_to_def(hit)
            return
        if state.col < 2:
            state.col += 1
            _clamp()
            return
        items = _items()
        if items:
            _toggle(items[state.item_i])

    @kb.add("-")
    @kb.add("delete")
    def _pop(event) -> None:
        if state.selected:
            state.selected.pop()

    @kb.add("backspace")
    def _bs(event) -> None:
        if state.typed:
            state.typed = state.typed[:-1]
            _apply_type()

    @kb.add("<any>")
    def _any(event) -> None:
        data = event.data
        if not data or len(data) != 1:
            return
        # reserved single-key commands
        if data in ("q", "h", "j", "k", "l", "-", " "):
            return
        if data.isprintable() and (data.isalnum() or data in ":_."):
            state.typed += data.lower()
            _apply_type()

    style = Style.from_dict(
        {
            "title": "bold ansicyan",
            "hint": "ansibrightblack",
            "header": "bold ansibrightblack",
            "cell": "",
            "sel": "reverse bold ansicyan",
            "typed": "ansiyellow",
            "picked": "bold ansigreen",
        }
    )

    control = FormattedTextControl(_render, focusable=True)
    app = Application(
        layout=Layout(Window(content=control, always_hide_cursor=True)),
        key_bindings=kb,
        style=style,
        full_screen=False,
        mouse_support=False,
    )
    result = app.run()
    return result if result is not None else _specs_from_defs(state.selected)
