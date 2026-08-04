#!/usr/bin/env bash
#
# Sets Meal Planner's SaleFinder IDs as GitHub Actions *repository Variables*,
# so you don't have to click through Settings -> Secrets and variables -> Actions.
#
# One-time setup:
#   1. Install the GitHub CLI:  https://cli.github.com   (Windows: winget install GitHub.cli)
#   2. Authenticate once:       gh auth login
#   3. Run this:                bash set-catalogue-vars.sh
#
# retailerId + locationId are fixed and never change.
# catalogueId changes WEEKLY — re-run this (or just the two catalogue lines)
# each week with the new IDs from the catalogue's Network tab.

set -euo pipefail

REPO="ianhay/mealplanner"

# --- fixed per store/region (set once, never change) ---
gh variable set COLES_RETAILER_ID    --repo "$REPO" --body "148"
gh variable set COLES_LOCATION_ID    --repo "$REPO" --body "9045"
gh variable set WOOLIES_RETAILER_ID  --repo "$REPO" --body "126"
gh variable set WOOLIES_LOCATION_ID  --repo "$REPO" --body "22287"

# --- changes weekly (update these two each cycle) ---
gh variable set COLES_CATALOGUE_ID   --repo "$REPO" --body "66233"
gh variable set WOOLIES_CATALOGUE_ID --repo "$REPO" --body "66794"   # current as of Aug 2026

echo
echo "Done. Current repository variables:"
gh variable list --repo "$REPO"
