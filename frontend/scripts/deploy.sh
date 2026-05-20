#!/usr/bin/env bash
# Deploy klubovi.domovina.ai to Cloudflare Pages.
#
# Steps:
#   1. Refresh static data from SQLite (40_export_static.py)
#   2. Refresh sitemap + robots (41_export_sitemap.py)
#   3. Type-check + Vite build
#   4. wrangler pages deploy dist --project-name=klubovi-domovina
#
# Requirements:
#   - CLOUDFLARE_ACCOUNT_ID is D.O.M. account: 7dc7167b7e2e00923bfa7cd697df14e4
#   - wrangler must be logged in (wrangler login) under that account
#   - uv + node installed
#
# Custom domain klubovi.domovina.ai is attached manually in the CF dashboard.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$(dirname "$SCRIPT_DIR")"
REPO_ROOT="$(dirname "$FRONTEND_DIR")"

CF_ACCOUNT_ID="${CLOUDFLARE_ACCOUNT_ID:-7dc7167b7e2e00923bfa7cd697df14e4}"
PROJECT_NAME="klubovi-domovina"
BRANCH="${1:-main}"

cd "$REPO_ROOT"

echo "==> 1/4 Exporting static data from SQLite"
uv run python scripts/40_export_static.py

echo "==> 2/4 Generating sitemap + robots.txt"
uv run python scripts/41_export_sitemap.py

cd "$FRONTEND_DIR"

echo "==> 3/4 Building frontend (vite)"
npm run build

echo "==> 4/4 Deploying to Cloudflare Pages → ${PROJECT_NAME} (branch=${BRANCH})"
CLOUDFLARE_ACCOUNT_ID="$CF_ACCOUNT_ID" \
  npx --yes wrangler pages deploy dist \
    --project-name="$PROJECT_NAME" \
    --branch="$BRANCH"

echo "✓ Deployed. Aliases: https://${PROJECT_NAME}.pages.dev/"
echo "  Custom domain: https://klubovi.domovina.ai/ (attach manually in CF dashboard)"
