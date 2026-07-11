# alpp

Alpaca chart CLI with Rich UI, live ticker autocomplete, and HTML charts.

- BYOK from [Alpaca](https://alpaca.markets/)
- Charts + tech analysis of one or more tickers using the Alpaca api.

## Screenies

### main
<img width="488" height="93" alt="Screenshot 2026-07-11 at 12 07 28 PM" src="https://github.com/user-attachments/assets/7bd2ad6a-3758-4f2a-83d1-b8dd3e31c683" />

### adding a ticker (ajax-style load)
<img width="780" height="173" alt="Screenshot 2026-07-11 at 12 07 37 PM" src="https://github.com/user-attachments/assets/39c81887-e233-413d-9971-825d54a590fa" />

     - grabs latest tickers on initial load from:
          - NASDAQ: ftp://ftp.nasdaqtrader.com/symboldirectory/nasdaqlisted.txt
          - NYSE, Arca, etc: ftp://ftp.nasdaqtrader.com/symboldirectory/otherlisted.txt 
### cross compare tickers (eg. VOO vs QQQ)
<img width="859" height="423" alt="Screenshot 2026-07-11 at 12 07 52 PM" src="https://github.com/user-attachments/assets/91e3c869-b23b-466a-b95b-317726551b57" />

### lots of custom specs....
<img width="474" height="227" alt="Screenshot 2026-07-11 at 12 08 14 PM" src="https://github.com/user-attachments/assets/8aadb58d-dd64-4a5f-9794-4f8257997093" />
<img width="765" height="284" alt="Screenshot 2026-07-11 at 12 08 27 PM" src="https://github.com/user-attachments/assets/d5841982-fd30-4e2d-bf0f-5b15b76db328" />
<img width="488" height="208" alt="Screenshot 2026-07-11 at 12 09 04 PM" src="https://github.com/user-attachments/assets/ba71897b-5a53-4d1d-a5d8-1ef52b3e988d" />

### chart export to html
<img width="1254" height="704" alt="Screenshot 2026-07-11 at 12 09 27 PM" src="https://github.com/user-attachments/assets/c2ffe5ca-2d28-4d01-97ec-e692116943e8" />

### remembers your previous tickers, and charts
<img width="854" height="151" alt="Screenshot 2026-07-11 at 12 19 13 PM" src="https://github.com/user-attachments/assets/b7bec4bf-4635-4dbc-b08c-d47b889b611d" />
<img width="871" height="266" alt="Screenshot 2026-07-11 at 12 19 28 PM" src="https://github.com/user-attachments/assets/04e19d53-4514-4ed9-9092-96721a65bb76" />


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

**Symbol directory:** the Homebrew install script **auto-fetches** Nasdaq’s public
ticker lists into `~/alpp/data/symbols.json` (best-effort — FTP/network failure does
**not** fail install). The first `alpp` run also tries if the cache is missing/stale.
Manual refresh: `alpp symbols update`.

### Homebrew Python (macOS)

If `python3` / `pip3` are from Homebrew (`/opt/homebrew/bin/python3`), use
`python3 -m pip` and prefer `--user`.

Install script (detects **Python X.Y** for PATH; uses the **published repo URL** —
installers do not enter a GitHub username). After pip, it pulls the Nasdaq list:

```bash
curl -fsSL https://raw.githubusercontent.com/elcafe7/alpp/main/scripts/install-homebrew.sh | bash
```

Or manually:

```bash
python3 -m pip install --user git+https://github.com/elcafe7/alpp.git
export PATH="$HOME/Library/Python/$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')/bin:$PATH"
python3 -c 'from alpp.symbols import bootstrap_symbols; bootstrap_symbols()'  # optional
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
alpp                    # interactive rich UI (ticker complete)
alpp AAPL ytd --ind sma:20,rsi --vs SPY --html --open
alpp AAPL ytd -p paper
alpp history            # same as typing history in interactive
alpp history tickers
alpp history charts
alpp history charts open 1
alpp history charts regenerate 1
```

### History command (ajax)

Start is the **simple ticker prompt** (no history preload). Type a symbol for live
directory complete, or type **`history`** — routes appear below as you type:

| Route | What |
|-------|------|
| **history › tickers** | Prior sessions (lazy-loaded) — pick one to re-run |
| **history › charts** | Saved HTML in `~/alpp/out` — then **existing** (open file) or **regenerate** (same params, fresh data) |

History lists load only after you enter the command. New HTML embeds `<!-- alpp-meta: … -->`.

Symbol cache is a single **JSON** file (not SQL): easy to inspect, ~one weekly refresh,
prefix search is fine for ~10–15k tickers. Includes `updated_at` plus each source’s
`file_creation_time` from Nasdaq Trader.

## Publish checklist (maintainer)

1. Create public repo and push `main`.
2. Set `REPO_SLUG` in `scripts/install-homebrew.sh` if not `elcafe7/alpp`.
3. Users run the Homebrew install script or `pip install git+https://github.com/…/alpp.git`.
