#!/usr/bin/env bash
# Homebrew Python install for alpp (public users — no GitHub username prompt).
set -euo pipefail

# Canonical published repo (same for every installer).
REPO_SLUG="${ALPP_REPO:-elcafe7/alpp}"

pip_install() {
  if python3 -m pip install --user "$@"; then
    return 0
  fi
  echo "Retrying with --break-system-packages (Homebrew Python)…" >&2
  python3 -m pip install --break-system-packages "$@"
}

if [[ -f pyproject.toml ]] && grep -q 'name = "alpp"' pyproject.toml 2>/dev/null; then
  echo "Installing from local tree…"
  pip_install .
else
  url="git+https://github.com/${REPO_SLUG}.git"
  echo "Installing ${url} …"
  pip_install "$url"
fi

# Best-effort Nasdaq symbol directory (ajax ticker complete). FTP can fail;
# install still succeeds — user can run `alpp symbols update` later.
echo
echo "Fetching Nasdaq symbol directory (best-effort)…"
if python3 - <<'PY'
from alpp.symbols import bootstrap_symbols, catalog_status, symbols_path

cat = bootstrap_symbols()
st = catalog_status()
if cat and st.get("count"):
    print(f"  ok  {st['count']:,} symbols → {symbols_path()}")
    raise SystemExit(0)
print("  skipped  FTP/network unavailable (ok — install finished)")
print("  later:   alpp symbols update")
raise SystemExit(0)
PY
then
  :
else
  echo "  skipped  could not import alpp yet; later: alpp symbols update" >&2
fi

pyver="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
bindir="${HOME}/Library/Python/${pyver}/bin"
echo
echo "Add to PATH if needed:"
echo "  export PATH=\"${bindir}:\$PATH\""
echo
echo "Then: alpp auth login"