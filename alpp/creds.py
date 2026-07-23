"""Alpaca credential resolution — keychain-first with auto-migration."""

from __future__ import annotations

import json
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

CONFIG_DIR = Path.home() / ".config" / "alpp"
CONFIG_FILE = CONFIG_DIR / "config.json"
ALPACA_PROFILES_DIR = Path.home() / ".config" / "alpaca" / "profiles"
KEYRING_SERVICE = "alpp"

_ENV_KEY_NAMES = ("ALPACA_API_KEY", "ALPACA_API_KEY_ID")
_ENV_SECRET_NAMES = ("ALPACA_SECRET_KEY", "ALPACA_API_SECRET_KEY")


@dataclass(frozen=True)
class Credentials:
    api_key: str
    secret_key: str
    profile: str
    source: str
    backend: str
    paper: bool


def _mask(secret: str, *, visible: int = 4) -> str:
    if not secret:
        return "—"
    if len(secret) <= visible:
        return "*" * len(secret)
    return f"{'*' * (len(secret) - visible)}{secret[-visible:]}"


def _parse_simple_yaml(path: Path) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key == "live_trade":
            out[key] = value.lower() in ("1", "true", "yes")
        else:
            out[key] = value
    return out


def _profile_from_env() -> str | None:
    explicit = os.environ.get("ALPACA_PROFILE", "").strip()
    if explicit:
        return explicit
    if os.environ.get("ALPACA_LIVE_TRADE", "").lower() in ("1", "true", "yes"):
        return "live"
    if os.environ.get("ALPACA_PAPER_TRADE", "").lower() in ("0", "false", "no"):
        return "live"
    if os.environ.get("ALPACA_PAPER", "").lower() in ("0", "false", "no"):
        return "live"
    return None


def _keyring_module():
    try:
        import keyring  # noqa: PLC0415

        return keyring
    except ImportError:
        return None


def keyring_available() -> bool:
    """Return whether keyring has a backend that can actually store secrets.

    ``keyring.get_keyring()`` succeeds even when it selects its fail backend,
    which otherwise turns a harmless ``auth status`` into a traceback on
    headless Linux hosts.
    """
    kr = _keyring_module()
    if kr is None:
        return False
    try:
        backend = kr.get_keyring()
        return float(backend.priority) > 0
    except Exception:
        return False


def _keyring_get(profile: str) -> tuple[str, str, bool] | None:
    kr = _keyring_module()
    if kr is None or not keyring_available():
        return None
    try:
        raw = kr.get_password(KEYRING_SERVICE, profile)
    except Exception:
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    key = str(data.get("api_key") or "").strip()
    secret = str(data.get("secret_key") or "").strip()
    if not key or not secret:
        return None
    live = bool(data.get("live_trade", profile == "live"))
    return key, secret, live


def _keyring_set(profile: str, api_key: str, secret_key: str, *, live_trade: bool) -> None:
    kr = _keyring_module()
    if kr is None or not keyring_available():
        raise SystemExit(
            _keyring_unavailable_message()
        )
    payload = json.dumps(
        {"api_key": api_key, "secret_key": secret_key, "live_trade": live_trade}
    )
    try:
        kr.set_password(KEYRING_SERVICE, profile, payload)
    except Exception as exc:
        raise SystemExit(_keyring_unavailable_message()) from exc


def _keyring_unavailable_message() -> str:
    return (
        "No usable system keyring backend is available.\n\n"
        "On a headless host, keep credentials out of alpp's config and set them "
        "for the command instead:\n"
        "  export ALPACA_API_KEY='your-key'\n"
        "  export ALPACA_SECRET_KEY='your-secret'\n"
        "  alpp AAPL ytd\n\n"
        "To save a persistent alpp profile, install and unlock a system keyring "
        "backend, then rerun `alpp auth login`."
    )


def _keyring_delete(profile: str) -> None:
    kr = _keyring_module()
    if kr is None:
        return
    try:
        kr.delete_password(KEYRING_SERVICE, profile)
    except Exception:
        pass


def _env_credentials() -> Credentials | None:
    key = next((os.environ.get(name, "").strip() for name in _ENV_KEY_NAMES if os.environ.get(name)), "")
    secret = next(
        (os.environ.get(name, "").strip() for name in _ENV_SECRET_NAMES if os.environ.get(name)),
        "",
    )
    if not key or not secret:
        return None
    profile = _profile_from_env() or "env"
    paper = profile != "live" and not (
        os.environ.get("ALPACA_LIVE_TRADE", "").lower() in ("1", "true", "yes")
    )
    return Credentials(
        api_key=key,
        secret_key=secret,
        profile=profile,
        source="environment variables",
        backend="environment",
        paper=paper,
    )


def _load_config_raw() -> dict[str, Any]:
    if not CONFIG_FILE.is_file():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid alpp config: {CONFIG_FILE} ({exc})") from exc


def _save_config(data: dict[str, Any]) -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    CONFIG_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return CONFIG_FILE


def _migrate_plaintext_to_keychain(
    data: dict[str, Any],
    *,
    console: Console | None = None,
) -> dict[str, Any]:
    """Move legacy plaintext api_key/secret_key entries into the system keychain."""
    if not keyring_available():
        return data
    profiles = dict(data.get("profiles") or {})
    migrated: list[str] = []
    for name, entry in profiles.items():
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("api_key") or "").strip()
        secret = str(entry.get("secret_key") or "").strip()
        if not key or not secret:
            continue
        live = bool(entry.get("live_trade", name == "live"))
        _keyring_set(name, key, secret, live_trade=live)
        profiles[name] = {"backend": "keychain", "live_trade": live}
        migrated.append(name)
    if migrated:
        data["version"] = 2
        data["profiles"] = profiles
        _save_config(data)
        if console:
            names = ", ".join(migrated)
            console.print(
                f"[green]Migrated[/] {names} credential(s) to system keychain "
                f"[dim](secrets removed from {CONFIG_FILE})[/]"
            )
    return data


def _load_config(*, console: Console | None = None, migrate: bool = True) -> dict[str, Any]:
    data = _load_config_raw()
    if migrate and data:
        data = _migrate_plaintext_to_keychain(data, console=console)
    return data


def _profile_meta(profile: str, data: dict[str, Any]) -> dict[str, Any] | None:
    entry = (data.get("profiles") or {}).get(profile)
    return entry if isinstance(entry, dict) else None


def _profile_is_live(profile: str, meta: dict[str, Any] | None) -> bool:
    if meta and "live_trade" in meta:
        return bool(meta["live_trade"])
    return profile == "live"


def _credentials_from_keyring(profile: str, meta: dict[str, Any] | None) -> Credentials | None:
    stored = _keyring_get(profile)
    if not stored:
        return None
    key, secret, live = stored
    paper = not live
    return Credentials(
        api_key=key,
        secret_key=secret,
        profile=profile,
        source="system keychain",
        backend="keychain",
        paper=paper,
    )


def _credentials_from_plaintext(
    profile: str,
    meta: dict[str, Any],
    *,
    source: str,
) -> Credentials | None:
    key = str(meta.get("api_key") or "").strip()
    secret = str(meta.get("secret_key") or "").strip()
    if not key or not secret:
        return None
    paper = not _profile_is_live(profile, meta)
    return Credentials(
        api_key=key,
        secret_key=secret,
        profile=profile,
        source=source,
        backend="plaintext",
        paper=paper,
    )


def profile_available(profile: str) -> bool:
    data = _load_config(migrate=False)
    meta = _profile_meta(profile, data)
    if meta and meta.get("backend") == "keychain":
        return _keyring_get(profile) is not None
    if meta and meta.get("api_key") and meta.get("secret_key"):
        return True
    return _keyring_get(profile) is not None


def _resolve_profile(profile: str, data: dict[str, Any]) -> Credentials | None:
    meta = _profile_meta(profile, data)
    if meta and meta.get("backend") == "keychain":
        return _credentials_from_keyring(profile, meta)
    if meta:
        creds = _credentials_from_plaintext(profile, meta, source=str(CONFIG_FILE))
        if creds:
            return creds
    # Keychain entry without config metadata (edge case)
    return _credentials_from_keyring(profile, meta)


def _prompt_live_fallback(
    chosen: str,
    *,
    console: Console,
) -> str | None:
    """If paper (or chosen profile) is missing but live exists, ask — never auto-switch."""
    if chosen == "live":
        return None
    if not profile_available("live"):
        return None
    console.print(
        f"[yellow]No {chosen} credentials found.[/] "
        "[bold red]Live credentials are available[/] (real-money account)."
    )
    if Confirm.ask(f"Use live profile instead of {chosen}?", default=False, console=console):
        return "live"
    return None


def resolve_credentials(
    profile: str | None = None,
    *,
    console: Console | None = None,
    allow_profile_prompt: bool = False,
    ignore_env: bool = False,
) -> Credentials | None:
    """Resolve credentials without setup prompts.

    When ``ignore_env`` is True (or an explicit ``profile`` is given), skip
    environment variable credentials and load the named keychain/config profile.
    Explicit profile always wins over env so tools can force paper/live.
    """
    # Env only when no explicit profile and not forced off — env often pins paper.
    use_env = not ignore_env and not (profile and str(profile).strip())
    if use_env:
        env = _env_credentials()
        if env:
            return env

    data = _load_config(console=console)
    chosen = (
        (str(profile).strip() if profile else "")
        or (None if ignore_env else _profile_from_env())
        or str(data.get("default_profile") or "").strip()
        or "paper"
    ).strip()

    creds = _resolve_profile(chosen, data)
    if creds:
        return creds

    if allow_profile_prompt and console is not None and sys.stdin.isatty():
        alt = _prompt_live_fallback(chosen, console=console)
        if alt:
            return _resolve_profile(alt, data)

    return None


def require_credentials(
    profile: str | None = None,
    *,
    console: Console | None = None,
    allow_profile_prompt: bool = False,
    ignore_env: bool = False,
) -> Credentials:
    creds = resolve_credentials(
        profile=profile,
        console=console,
        allow_profile_prompt=allow_profile_prompt,
        ignore_env=ignore_env,
    )
    if creds:
        return creds
    raise SystemExit(_missing_credentials_message(profile))


def _missing_credentials_message(profile: str | None = None) -> str:
    hint = f" for profile {profile!r}" if profile else ""
    return (
        f"Missing Alpaca credentials{hint}.\n\n"
        "Quick setup:\n"
        "  alpp auth login\n"
        "  alpp auth import-alpaca   # one-time import from Alpaca CLI profiles\n\n"
        "Or set environment variables:\n"
        "  export ALPACA_API_KEY='your-key'\n"
        "  export ALPACA_SECRET_KEY='your-secret'\n\n"
        f"Config metadata: {CONFIG_FILE}"
    )


def ensure_credentials(
    *,
    profile: str | None = None,
    console: Console | None = None,
    interactive: bool | None = None,
    ignore_env: bool = False,
) -> Credentials:
    """Return credentials; prompt for setup or live fallback on a TTY when missing."""
    if interactive is None:
        interactive = sys.stdin.isatty()
    console = console or Console()

    # Explicit profile → keychain/config for that name (bypass env paper pin).
    if profile and str(profile).strip():
        ignore_env = True

    creds = resolve_credentials(
        profile=profile,
        console=console,
        allow_profile_prompt=interactive and not ignore_env,
        ignore_env=ignore_env,
    )
    if creds:
        return creds

    if not interactive:
        raise SystemExit(_missing_credentials_message(profile))

    console.print(
        Panel(
            "No Alpaca API credentials found.\n"
            "Get free paper keys: https://app.alpaca.markets/paper/dashboard/overview",
            title="[bold yellow]alpp setup[/]",
            border_style="yellow",
        )
    )
    if Confirm.ask("Configure credentials now?", default=True, console=console):
        login_interactive(profile=profile or "paper", console=console)
        creds = resolve_credentials(
            profile=profile, console=console, ignore_env=bool(profile)
        )
        if creds:
            return creds
    raise SystemExit(_missing_credentials_message(profile))


def _confirm_live(console: Console) -> None:
    console.print("[bold red]Live profile uses real-money Alpaca credentials.[/]")
    typed = Prompt.ask("Type LIVE to confirm", console=console).strip()
    if typed != "LIVE":
        raise SystemExit("Aborted — live profile not confirmed.")


def _store_profile(
    profile: str,
    api_key: str,
    secret_key: str,
    *,
    live_trade: bool,
    data: dict[str, Any],
) -> None:
    if not keyring_available():
        raise SystemExit(_keyring_unavailable_message())
    _keyring_set(profile, api_key, secret_key, live_trade=live_trade)
    backend = "keychain"
    profiles = dict(data.get("profiles") or {})
    entry: dict[str, Any] = {"backend": backend, "live_trade": live_trade}
    profiles[profile] = entry
    data["version"] = 2
    data["profiles"] = profiles


def login_interactive(
    *,
    profile: str = "paper",
    console: Console | None = None,
    api_key: str | None = None,
    secret_key: str | None = None,
) -> Path:
    console = console or Console()
    profile = profile.strip() or "paper"
    if not keyring_available():
        raise SystemExit(_keyring_unavailable_message())
    live_trade = profile == "live"
    if live_trade:
        _confirm_live(console)
    console.print(
        f"[bold]Profile[/] [cyan]{profile}[/]  "
        f"[dim](paper = sandbox · live = real money)[/]"
    )
    key = (api_key or Prompt.ask("API key", console=console)).strip()
    secret = (secret_key or Prompt.ask("Secret key", password=True, console=console)).strip()
    if not key or not secret:
        raise SystemExit("API key and secret are required.")

    data = _load_config(console=console)
    _store_profile(profile, key, secret, live_trade=live_trade, data=data)
    data["default_profile"] = profile
    path = _save_config(data)
    backend = (data["profiles"][profile].get("backend") or "unknown")
    console.print(
        f"[green]Saved[/] {profile} → {backend}  "
        f"[dim](metadata: {path})[/]"
    )
    return path


def import_alpaca_profiles(*, console: Console | None = None) -> int:
    """One-time import from ~/.config/alpaca/profiles/{paper,live}.yaml into keychain."""
    console = console or Console()
    if not keyring_available():
        raise SystemExit(_keyring_unavailable_message())
    if not ALPACA_PROFILES_DIR.is_dir():
        raise SystemExit(f"No Alpaca CLI profiles at {ALPACA_PROFILES_DIR}")

    data = _load_config(console=console)
    imported: list[str] = []
    for name in ("paper", "live"):
        path = ALPACA_PROFILES_DIR / f"{name}.yaml"
        parsed = _parse_simple_yaml(path)
        key = str(parsed.get("api_key") or "").strip()
        secret = str(parsed.get("secret_key") or "").strip()
        if not key or not secret:
            continue
        live_trade = bool(parsed.get("live_trade", name == "live"))
        _store_profile(name, key, secret, live_trade=live_trade, data=data)
        imported.append(name)

    if not imported:
        raise SystemExit(f"No api_key/secret_key pairs found under {ALPACA_PROFILES_DIR}")

    if "default_profile" not in data:
        data["default_profile"] = "paper" if "paper" in imported else imported[0]
    _save_config(data)
    console.print(
        f"[green]Imported[/] {', '.join(imported)} from Alpaca CLI → "
        f"{data['profiles'][imported[0]].get('backend', 'stored')}"
    )
    console.print(
        "[dim]alpp no longer reads Alpaca yaml at runtime; credentials are in your keychain/metadata.[/]"
    )
    return 0


def set_default_profile(profile: str, *, console: Console | None = None) -> None:
    profile = profile.strip()
    if not profile:
        raise SystemExit("Profile name required.")
    if not profile_available(profile):
        raise SystemExit(
            f"Unknown profile {profile!r}. Run: alpp auth login --profile {profile}"
        )
    data = _load_config()
    data["version"] = data.get("version") or 2
    data["default_profile"] = profile
    _save_config(data)
    console = console or Console()
    console.print(f"[green]Default profile[/] → [cyan]{profile}[/]")


def logout_profile(profile: str | None = None, *, console: Console | None = None) -> None:
    data = _load_config(migrate=False)
    profiles = dict(data.get("profiles") or {})
    names = [profile] if profile else list(profiles)
    if not names and not profile:
        raise SystemExit(f"No saved alpp credentials at {CONFIG_FILE}")

    for name in names:
        profiles.pop(name, None)
        _keyring_delete(name)

    if profiles:
        data["profiles"] = profiles
        if data.get("default_profile") not in profiles:
            data["default_profile"] = next(iter(profiles))
        _save_config(data)
    elif CONFIG_FILE.is_file():
        CONFIG_FILE.unlink()

    console = console or Console()
    if profile:
        console.print(f"[green]Removed[/] profile [cyan]{profile}[/]")
    else:
        console.print(f"[green]Removed[/] saved credentials[/]")


def _scan_profile(name: str, data: dict[str, Any]) -> dict[str, Any] | None:
    meta = _profile_meta(name, data)
    entry: dict[str, Any] = {"configured": False}

    if meta and meta.get("backend") == "keychain":
        stored = _keyring_get(name)
        if stored:
            key, _, live = stored
            entry.update(
                {
                    "configured": True,
                    "backend": "keychain",
                    "api_key": _mask(key),
                    "live_trade": live,
                }
            )
            return entry

    if meta and meta.get("api_key") and meta.get("secret_key"):
        entry.update(
            {
                "configured": True,
                "backend": "plaintext",
                "api_key": _mask(str(meta["api_key"])),
                "live_trade": _profile_is_live(name, meta),
            }
        )
        return entry

    stored = _keyring_get(name)
    if stored:
        key, _, live = stored
        entry.update(
            {
                "configured": True,
                "backend": "keychain",
                "api_key": _mask(key),
                "live_trade": live,
            }
        )
        return entry

    alpaca_path = ALPACA_PROFILES_DIR / f"{name}.yaml"
    if alpaca_path.is_file():
        parsed = _parse_simple_yaml(alpaca_path)
        key = str(parsed.get("api_key") or "")
        if key and parsed.get("secret_key"):
            entry.update(
                {
                    "configured": True,
                    "backend": "alpaca_cli (not imported)",
                    "api_key": _mask(key),
                    "live_trade": bool(parsed.get("live_trade", name == "live")),
                    "import_hint": True,
                }
            )
            return entry
    return None


def status_report() -> dict[str, Any]:
    env = _env_credentials()
    data = _load_config(migrate=False)
    default_profile = str(data.get("default_profile") or "paper").strip()
    active = resolve_credentials()
    profiles: dict[str, dict[str, Any]] = {}

    names = set((data.get("profiles") or {}).keys()) | {"paper", "live"}
    for name in sorted(names):
        scanned = _scan_profile(name, data)
        if scanned:
            profiles[name] = scanned

    alpaca_importable = any(p.get("import_hint") for p in profiles.values())
    return {
        "config_file": str(CONFIG_FILE),
        "config_exists": CONFIG_FILE.is_file(),
        "keyring": keyring_available(),
        "default_profile": default_profile,
        "active": active,
        "env_override": env is not None,
        "profiles": profiles,
        "alpaca_importable": alpaca_importable,
    }


def print_status(*, console: Console | None = None) -> int:
    console = console or Console()
    report = status_report()
    tbl = Table(show_header=False, box=None, padding=(0, 1))
    tbl.add_column(style="dim")
    tbl.add_column()

    cfg = report["config_file"]
    if not report.get("config_exists"):
        cfg = f"{cfg} [dim](not created yet)[/]"
    tbl.add_row("config", cfg)
    tbl.add_row(
        "keyring",
        "available" if report["keyring"] else "[yellow]no usable backend[/]",
    )
    tbl.add_row("default", report["default_profile"])
    if report["env_override"]:
        tbl.add_row("override", "[yellow]environment variables[/]")
    active = report["active"]
    if active:
        mode = "paper" if active.paper else "live"
        tbl.add_row("active", f"{active.profile} ({mode})")
        tbl.add_row("backend", active.backend)
        tbl.add_row("source", active.source)
        tbl.add_row("api key", _mask(active.api_key))
    else:
        tbl.add_row("active", "[red]not configured[/]")

    console.print(Panel(tbl, title="[bold]alpp auth[/]", border_style="cyan"))

    profiles = report["profiles"]
    if profiles:
        pt = Table("Profile", "Key", "Mode", "Backend")
        for name, meta in profiles.items():
            mode = "live" if meta.get("live_trade") else "paper"
            star = " *" if name == report["default_profile"] else ""
            pt.add_row(
                f"{name}{star}",
                meta.get("api_key", "—"),
                mode,
                meta.get("backend", "—"),
            )
        console.print(pt)

    if report.get("alpaca_importable"):
        console.print(
            "[yellow]Alpaca CLI profile files detected but not imported.[/] "
            "Run: [bold]alpp auth import-alpaca[/]"
        )
    elif not profiles:
        if report["env_override"]:
            console.print("[green]Using environment credentials for this process.[/]")
        elif report["keyring"]:
            console.print("[yellow]No saved profiles.[/] Run: [bold]alpp auth login[/]")
        else:
            console.print(
                "[yellow]No saved profiles.[/] On this host, use "
                "[bold]ALPACA_API_KEY[/] + [bold]ALPACA_SECRET_KEY[/] in the environment."
            )
    return 0 if active else 1
