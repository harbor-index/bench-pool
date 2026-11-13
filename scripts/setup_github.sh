#!/bin/sh
# One-time setup of the GitHub side, run from the repository root after the first push:
#   - copies the keys in .env to repository secrets (values are never printed)
#   - switches GitHub Pages on, published by the "daily" workflow
#
#   sh scripts/setup_github.sh            # do it
#   sh scripts/setup_github.sh --dry-run  # only say what would be set
#
# Needs the GitHub CLI (gh), logged in with admin rights on the repository.
set -eu
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
DRY=${1:-}
[ -f .env ] || { echo "no .env here; run from the repository root"; exit 1; }

# GITHUB_TOKEN is not copied: Actions provides its own.
for NAME in OPENAI_BASE_URL OPENAI_API_KEY OPENAI_MODEL OPENAI_MAX_TOKENS OPENAI_THINKING HF_TOKEN S2_API_KEY; do
  VALUE=$(grep -E "^$NAME=" .env | head -1 | cut -d= -f2- || true)
  if [ -z "$VALUE" ]; then echo "skip   $NAME (empty in .env)"; continue; fi
  case "$VALUE" in
    *127.0.0.1*|*localhost*) echo "STOP   $NAME points at this machine; GitHub cannot reach it. Put the hosted endpoint in .env first."; exit 1;;
  esac
  if [ "$DRY" = "--dry-run" ]; then echo "would set $NAME (${#VALUE} characters)"; continue; fi
  printf '%s' "$VALUE" | gh secret set "$NAME" --repo "$REPO"
  echo "set    $NAME"
done

if [ "$DRY" = "--dry-run" ]; then echo "would switch Pages on for $REPO (source: GitHub Actions)"; exit 0; fi
gh api -X POST "repos/$REPO/pages" -f build_type=workflow >/dev/null 2>&1 \
  || gh api -X PUT "repos/$REPO/pages" -f build_type=workflow >/dev/null
echo "Pages is on for $REPO. Start the first run with:  gh workflow run daily --repo $REPO"
