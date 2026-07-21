#!/usr/bin/env bash
# Additive backfill of iOS PWA splash screens to the c.ff.hr CDN (bucket c-ff-hr).
#
# Uploads data/club_splash/{W}x{H}/{slug}.png -> club_splash/{W}x{H}/{slug}.png
# (~12 sizes x ~1014 clubs ~= 12k objects). Pattern from 51_upload_square_icons.sh.
#
# Conventions from LOGOS.md "CDN operations":
#   - per-object `wrangler r2 object put` over the existing wrangler OAuth
#     login (no R2 API token), CLOUDFLARE_ACCOUNT_ID = ff.hr account
#   - keys under club_splash/ are NEW -> additive, no edge-cache staleness
#   - verify via public URLs AFTER upload (never curl-probe before upload:
#     a 404 gets negative-cached at the edge)
#
# Rate-limit coordination (global CF API limit 1200 req / 5 min):
#   - at 12k objects a per-key `r2 object get` existence probe (51's skip
#     logic) would DOUBLE the API calls; instead successful puts are appended
#     to data/club_splash/.uploaded.log and skipped on re-run (resume-safe)
#   - worker count is re-evaluated per chunk: while another `r2 object put`
#     job (e.g. the club_square backfill) is running -> 4 workers, else 8
#
# Upload order (so demos work first):
#   1. ALL sizes for the priority slugs (pilot/demo clubs)
#   2. then size-by-size (modern devices first), clubs alphabetically
#
# Usage: scripts/53_upload_splash.sh [--force]   (--force ignores .uploaded.log)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
SRC_DIR="$ROOT/data/club_splash"
BUCKET="c-ff-hr"
export CLOUDFLARE_ACCOUNT_ID="${CLOUDFLARE_ACCOUNT_ID:-3fa39143e7155266b2ee5b9cb06e755f}"  # ff.hr account
CACHE="public, max-age=2592000"
DONE_LOG="$SRC_DIR/.uploaded.log"
CHUNK=200

PRIORITY_SLUGS=(lomnica lukavec croatia-zmijavci mladost-okic-klinca-sela
                bsk-zmaj obilic mladost-1930 zrinski-ozalj)
# modern devices first
SIZE_ORDER=(1179x2556 1290x2796 1170x2532 1284x2778 1206x2622 1320x2868
            1125x2436 828x1792 1242x2688 750x1334 1242x2208 640x1136)

FORCE=0
[[ "${1:-}" == "--force" ]] && FORCE=1
touch "$DONE_LOG"

upload_one() {
  local file="$1" key="$2"
  if npx --yes wrangler r2 object put "$BUCKET/$key" \
      --file "$file" --remote \
      --content-type image/png \
      --cache-control "$CACHE" >/dev/null 2>&1; then
    echo "$key" >> "$DONE_LOG"
    echo "put   $key"
  else
    echo "FAIL  $key" >&2
    return 0  # keep the batch going; re-run resumes via .uploaded.log
  fi
}
export -f upload_one
export BUCKET CACHE DONE_LOG

# 4 workers while another r2 upload job runs, 8 once we own the rate budget
current_workers() {
  if ps aux | grep "r2 object put" | grep -v "club_splash" | grep -vq grep; then
    echo 4
  else
    echo 8
  fi
}

list_keys() {  # priority slugs first (all sizes), then size-major alphabetical
  local slug size
  for slug in "${PRIORITY_SLUGS[@]}"; do
    for size in "${SIZE_ORDER[@]}"; do
      [[ -f "$SRC_DIR/$size/$slug.png" ]] && echo "club_splash/$size/$slug.png"
    done
  done
  for size in "${SIZE_ORDER[@]}"; do
    for f in "$SRC_DIR/$size"/*.png; do
      slug="$(basename "$f" .png)"
      printf '%s\n' "${PRIORITY_SLUGS[@]}" | grep -qx "$slug" && continue
      echo "club_splash/$size/$slug.png"
    done
  done
}

PENDING="$(mktemp)"
if [[ "$FORCE" == 1 ]]; then
  list_keys > "$PENDING"
else
  list_keys | grep -vxFf "$DONE_LOG" > "$PENDING" || true
fi
TOTAL=$(wc -l < "$PENDING" | tr -d ' ')
echo "==> uploading $TOTAL objects to $BUCKET (done so far: $(wc -l < "$DONE_LOG" | tr -d ' '))"

CHUNK_DIR="$(mktemp -d)"
split -l "$CHUNK" "$PENDING" "$CHUNK_DIR/batch."
UPLOADED=0
for batch in "$CHUNK_DIR"/batch.*; do
  [[ -f "$batch" ]] || continue
  W="$(current_workers)"
  while IFS= read -r key; do
    printf '%s\t%s\n' "$SRC_DIR/${key#club_splash/}" "$key"
  done < "$batch" | xargs -P "$W" -n 2 bash -c 'upload_one "$0" "$1"'
  UPLOADED=$((UPLOADED + $(wc -l < "$batch")))
  echo "==> chunk done ($UPLOADED/$TOTAL sent, workers=$W)"
done
rm -rf "$CHUNK_DIR" "$PENDING"
echo "==> done. Spot-check: https://c.ff.hr/club_splash/1179x2556/lomnica.png"
