#!/usr/bin/env bash
# Sync TauricResearch/TradingAgents -> lichenq fork main -> integrate branch.
# Keeps results/ at fork main baseline (never merges local results artifacts).
#
# Usage:
#   ./scripts/sync_fork.sh
#   INTEGRATE_BRANCH=integrate/other ./scripts/sync_fork.sh
#
# Env (defaults):
#   UPSTREAM_REMOTE=origin      TauricResearch
#   FORK_REMOTE=lichenq         your fork
#   UPSTREAM_MAIN=main
#   FORK_MAIN=main
#   INTEGRATE_BRANCH=integrate/mvp1-20260603

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

UPSTREAM_REMOTE="${UPSTREAM_REMOTE:-origin}"
FORK_REMOTE="${FORK_REMOTE:-lichenq}"
UPSTREAM_MAIN="${UPSTREAM_MAIN:-main}"
FORK_MAIN="${FORK_MAIN:-main}"
INTEGRATE_BRANCH="${INTEGRATE_BRANCH:-integrate/mvp1-20260603}"
RESULTS_DIR="results"

die() { echo "error: $*" >&2; exit 1; }

git rev-parse --git-dir >/dev/null 2>&1 || die "not a git repository"
git remote get-url "$UPSTREAM_REMOTE" >/dev/null 2>&1 || die "missing remote: $UPSTREAM_REMOTE"
git remote get-url "$FORK_REMOTE" >/dev/null 2>&1 || die "missing remote: $FORK_REMOTE"

if git status --porcelain | awk '{print $2}' | grep -v "^${RESULTS_DIR}" | grep -q .; then
  die "working tree has changes outside ${RESULTS_DIR}/; commit or stash first"
fi

ORIG_BRANCH="$(git branch --show-current)"
STASHED=0

stash_results() {
  if git status --porcelain -- "$RESULTS_DIR" | grep -q .; then
    echo "Stashing local changes under ${RESULTS_DIR}/"
    git stash push -u -m "sync_fork: ${RESULTS_DIR} $(date +%Y%m%d%H%M%S)" -- "$RESULTS_DIR/"
    STASHED=1
  fi
}

pop_stash() {
  if [[ "$STASHED" -eq 1 ]]; then
    git stash pop || echo "warn: stash pop failed — check git stash list"
    STASHED=0
  fi
}

restore_results_from_fork() {
  if git ls-tree -r --name-only "$FORK_REMOTE/$FORK_MAIN" -- "$RESULTS_DIR" 2>/dev/null | grep -q .; then
    git restore --source="$FORK_REMOTE/$FORK_MAIN" --staged --worktree "$RESULTS_DIR/" || true
  else
    git rm -rf --cached "$RESULTS_DIR/" 2>/dev/null || true
    rm -rf "$RESULTS_DIR/" 2>/dev/null || true
  fi
}

trap 'pop_stash; [[ -n "${ORIG_BRANCH:-}" ]] && git checkout "$ORIG_BRANCH" 2>/dev/null || true' EXIT

stash_results

echo "==> Fetch ${UPSTREAM_REMOTE}/${UPSTREAM_MAIN} and ${FORK_REMOTE}"
git fetch "$UPSTREAM_REMOTE" "$UPSTREAM_MAIN"
git fetch "$FORK_REMOTE" "$FORK_MAIN" "$INTEGRATE_BRANCH"

echo "==> ${FORK_REMOTE}/${FORK_MAIN} <- ${UPSTREAM_REMOTE}/${UPSTREAM_MAIN}"
git checkout -B "$FORK_MAIN" "$FORK_REMOTE/$FORK_MAIN"
if git merge "$UPSTREAM_REMOTE/$UPSTREAM_MAIN" -m "chore: sync ${UPSTREAM_REMOTE}/${UPSTREAM_MAIN}"; then
  :
else
  die "conflicts syncing fork main — resolve, commit, then re-run"
fi
git push "$FORK_REMOTE" "$FORK_MAIN"

echo "==> ${INTEGRATE_BRANCH} <- ${FORK_REMOTE}/${FORK_MAIN} (exclude ${RESULTS_DIR}/)"
git checkout "$INTEGRATE_BRANCH"
git fetch "$FORK_REMOTE" "$FORK_MAIN"

set +e
MERGE_MSG="$(git merge "$FORK_REMOTE/$FORK_MAIN" --no-commit --no-ff 2>&1)"
MERGE_CODE=$?
set -e

if [[ "$MERGE_CODE" -ne 0 ]]; then
  if echo "$MERGE_MSG" | grep -qi "already up to date"; then
    echo "integrate branch already up to date with ${FORK_REMOTE}/${FORK_MAIN}"
  else
    CONFLICTS="$(git diff --name-only --diff-filter=U 2>/dev/null || true)"
    if echo "$CONFLICTS" | grep -v "^${RESULTS_DIR}/" | grep -q .; then
      die "merge conflicts outside ${RESULTS_DIR}/ — resolve manually, then re-run"
    fi
    if [[ -n "$CONFLICTS" ]]; then
      git checkout --theirs -- "$RESULTS_DIR/" 2>/dev/null || true
      git add -- "$RESULTS_DIR/" 2>/dev/null || true
    else
      die "merge failed: ${MERGE_MSG}"
    fi
  fi
fi

restore_results_from_fork

if git diff --name-only --diff-filter=U | grep -v "^${RESULTS_DIR}/" | grep -q .; then
  die "unresolved conflicts outside ${RESULTS_DIR}/"
fi

if git diff --cached --quiet && git diff --quiet; then
  echo "no integrate commit needed"
else
  git commit -m "chore: merge ${FORK_REMOTE}/${FORK_MAIN} into ${INTEGRATE_BRANCH}

Keep ${RESULTS_DIR}/ aligned with ${FORK_REMOTE}/${FORK_MAIN}; exclude local artifacts."
fi

git push "$FORK_REMOTE" "$INTEGRATE_BRANCH"
echo "==> Done: ${FORK_REMOTE}/${FORK_MAIN} and ${FORK_REMOTE}/${INTEGRATE_BRANCH} updated"
