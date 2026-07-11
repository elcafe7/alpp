# alpp

Alpaca chart CLI with Rich UI, live ticker autocomplete, and HTML charts.


## Install

Requires Python 3.11+.

**From GitHub** (no PyPI account needed):

```bash
pip install git+https://github.com/elcafe7/alpp.git
```

Or clone and install locally:

```bash
git clone https://github.com/elcafe7/alpp.git
cd alpp
pip install .
```

That installs the `alpp` command and all dependencies.

### Homebrew Python (macOS)

If `python3` / `pip3` are from Homebrew (`/opt/homebrew/bin/python3`), use
`python3 -m pip` and prefer `--user`.

Install script (detects **Python X.Y** for PATH; uses the **published repo URL** —
installers do not enter a GitHub username):

```bash
curl -fsSL https://raw.githubusercontent.com/elcafe7/alpp/main/scripts/install-homebrew.sh | bash
```

Or manually:

```bash
python3 -m pip install --user git+https://github.com/elcafe7/alpp.git
export PATH="$HOME/Library/Python/$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')/bin:$PATH"
alpp auth login
```

Clone + local install also works:

```bash
git clone https://github.com/elcafe7/alpp.git && cd alpp && bash scripts/install-homebrew.sh
```

## Credentials

Secrets go in the **system keychain** (via `keyring`). `~/.config/alpp/config.json`
holds only profile metadata (mode `0600`). Environment variables override everything.

```bash
alpp auth login              # paper keys → keychain (recommended)
alpp auth login --live       # live keys (requires typing LIVE)
alpp auth import-alpaca      # one-time import from Alpaca CLI yaml files
alpp auth status             # active profile + backend (keys masked)
alpp auth use paper          # switch default profile
alpp auth logout             # remove saved keys
```

Legacy plaintext entries in `config.json` are **auto-migrated** to keychain on first use.

If paper credentials are missing but live exists, `alpp` **prompts** before switching —
it never auto-selects live.

Or export env vars (CI, ephemeral shells):

```bash
export ALPACA_API_KEY='your-key-id'
export ALPACA_SECRET_KEY='your-secret'
```

Free paper keys: https://app.alpaca.markets/paper/dashboard/overview

## Usage

```bash
alpp symbols update     # fetch nasdaqlisted + otherlisted → ~/alpp/data/symbols.json
alpp symbols status
alpp                    # interactive: recent history + saved charts + ticker complete
alpp AAPL ytd --ind sma:20,rsi --vs SPY --html --open
alpp AAPL ytd -p paper  # explicit profile
alpp history            # recent tickers / overlay sets (~/.config/alpp/history.json)
alpp charts             # browse HTML in ~/alpp/out (and ./out) with parsed labels
alpp charts open 1      # open newest saved chart in browser
```

### History & saved charts

Each session records the **ticker**, **compare**, **timeframe**, and **indicators** so the
next `alpp` launch can re-run them (`#1`, `#2`, … at the ticker prompt).

HTML charts written to `~/alpp/out/` (or `./out`) show up under **saved charts**. The CLI
reads titles natively (`SYMBOL · … · YTD · SMA 20 · vs SPY`) and, for new files, an
`<!-- alpp-meta: … -->` tag. Shortcuts: **`sN`** open chart N, **`rN`** re-run that setup.

Symbol cache is a single **JSON** file (not SQL): easy to inspect, ~one weekly refresh,
prefix search is fine for ~10–15k tickers. Includes `updated_at` plus each source’s
`file_creation_time` from Nasdaq Trader.

## Publish checklist (maintainer)

1. Create public repo and push `main`.
2. Set `REPO_SLUG` in `scripts/install-homebrew.sh` if not `elcafe7/alpp`.
3. Users run the Homebrew install script or `pip install git+https://github.com/…/alpp.git`.
