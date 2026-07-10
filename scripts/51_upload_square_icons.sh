#!/usr/bin/env bash
# Additive backfill of square app icons to the c.ff.hr CDN (R2 bucket c-ff-hr).
#
# Uploads data/club_square/{slug}.png        -> club_square/{slug}.png
#         data/club_square/maskable/{slug}.png -> club_square/maskable/{slug}.png
#
# Conventions from LOGOS.md "CDN operations":
#   - per-object `wrangler r2 object put` over the existing wrangler OAuth
#     login (no R2 API token), CLOUDFLARE_ACCOUNT_ID = ff.hr account
#   - ~4 parallel workers to stay under API rate limits
#   - keys under club_square/ are NEW -> additive, no edge-cache staleness
#   - verify via public URLs, not `wrangler r2 bucket info` (it lags)
#
# Skip logic: an object is skipped when `wrangler r2 object get --pipe` HEADs
# fine AND --force is not set. Default run only uploads missing keys, so
# re-runs after an interrupted batch are cheap. Use --force to overwrite
# (remember the 30-day edge cache on already-fetched URLs).
#
# Usage: scripts/51_upload_square_icons.sh [--force] [slug ...]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
SRC_DIR="$ROOT/data/club_square"
BUCKET="c-ff-hr"
export CLOUDFLARE_ACCOUNT_ID="${CLOUDFLARE_ACCOUNT_ID:-3fa39143e7155266b2ee5b9cb06e755f}"  # ff.hr account
WORKERS=4
CACHE="public, max-age=2592000"

FORCE=0
SLUGS=()
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    *) SLUGS+=("$arg") ;;
  esac
done

upload_one() {
  local file="$1" key="$2"
  if [[ "$FORCE" != 1 ]]; then
    if npx --yes wrangler r2 object get "$BUCKET/$key" --remote --pipe >/dev/null 2>&1; then
      echo "skip  $key"
      return 0
    fi
  fi
  npx --yes wrangler r2 object put "$BUCKET/$key" \
    --file "$file" --remote \
    --content-type image/png \
    --cache-control "$CACHE" >/dev/null
  echo "put   $key"
}
export -f upload_one
export BUCKET FORCE CACHE

list_pairs() {
  local slug base
  for f in "$SRC_DIR"/*.png; do
    base="$(basename "$f")"
    slug="${base%.png}"
    if [[ ${#SLUGS[@]} -gt 0 ]] && ! printf '%s\n' "${SLUGS[@]}" | grep -qx "$slug"; then
      continue
    fi
    printf '%s\t%s\n' "$f" "club_square/$base"
    if [[ -f "$SRC_DIR/maskable/$base" ]]; then
      printf '%s\t%s\n' "$SRC_DIR/maskable/$base" "club_square/maskable/$base"
    fi
  done
}

TOTAL=$(list_pairs | wc -l | tr -d ' ')
echo "==> uploading $TOTAL objects to $BUCKET (workers=$WORKERS, force=$FORCE)"
list_pairs | xargs -P "$WORKERS" -n 2 bash -c 'upload_one "$0" "$1"'
echo "==> done. Spot-check: https://c.ff.hr/club_square/dinamo-zagreb.png"
