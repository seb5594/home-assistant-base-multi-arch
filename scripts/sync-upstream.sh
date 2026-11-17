#!/usr/bin/env bash
# Merge the upstream Home Assistant base image repository into this fork.
#
# Files listed in OWNED_FILES were rewritten on purpose in this fork. Upstream
# changes to them are not merged, our version always wins. Python directories
# that were generated here (see resolve_versions.py) are dropped as soon as
# upstream ships them. Any other conflict aborts the merge and exits with 2, so
# a human can resolve it.
#
# Exit codes: 0 merged or already up to date, 2 conflicts that need a human.

set -euo pipefail

UPSTREAM_REPO="${UPSTREAM_REPO:-home-assistant/docker-base}"
UPSTREAM_BRANCH="${UPSTREAM_BRANCH:-master}"
UPSTREAM_REF="upstream/${UPSTREAM_BRANCH}"
if [[ -n "${UPSTREAM_RELEASE:-}" ]]; then
  UPSTREAM_REF="refs/upstream/releases/${UPSTREAM_RELEASE}"
fi

OWNED_FILES=(
  .github/release-drafter.yml
  .github/workflows/build-base-image.yml
  .github/workflows/builder.yml
  .github/workflows/release-drafter.yml
  .github/workflows/update.yml
  README.md
)

ensure_upstream_remote() {
  if ! git remote get-url upstream > /dev/null 2>&1; then
    git remote add upstream "https://github.com/${UPSTREAM_REPO}.git"
  fi
  if [[ -n "${UPSTREAM_RELEASE:-}" ]]; then
    git fetch --quiet --no-tags upstream "refs/tags/${UPSTREAM_RELEASE}:${UPSTREAM_REF}"
  else
    git fetch --quiet upstream "${UPSTREAM_BRANCH}"
  fi
}

# Remove generated Python directories that upstream provides itself now.
drop_adopted_python_dirs() {
  local marker dir
  for marker in python/*/.auto-generated; do
    [[ -e "${marker}" ]] || continue
    dir="$(dirname "${marker}")"
    if git cat-file -e "${UPSTREAM_REF}:${dir}/Dockerfile" 2> /dev/null; then
      echo "Upstream ships ${dir} now, dropping the generated copy"
      git rm -r --quiet "${dir}"
      git commit --quiet -m "Drop generated ${dir}, upstream provides it now"
    fi
  done
}

restore_owned_files() {
  local file
  for file in "${OWNED_FILES[@]}"; do
    if git cat-file -e "HEAD:${file}" 2>/dev/null; then
      git checkout HEAD -- "${file}"
    else
      git rm --quiet --force --ignore-unmatch -- "${file}"
    fi
  done
}

ensure_upstream_remote

if git merge-base --is-ancestor "${UPSTREAM_REF}" HEAD; then
  echo "Already up to date with ${UPSTREAM_REPO}@${UPSTREAM_RELEASE:-${UPSTREAM_BRANCH}}"
  exit 0
fi

drop_adopted_python_dirs

upstream_sha="$(git rev-parse --short "${UPSTREAM_REF}")"
if ! git merge --no-ff --no-commit "${UPSTREAM_REF}"; then
  git rev-parse --verify --quiet MERGE_HEAD > /dev/null || exit 1
fi
restore_owned_files

unresolved="$(git diff --name-only --diff-filter=U)"
if [[ -n "${unresolved}" ]]; then
  git merge --abort
  echo "Merge needs manual resolution, conflicting files:" >&2
  echo "${unresolved}" >&2
  exit 2
fi

git commit --quiet -m "Merge ${UPSTREAM_REPO} ${upstream_sha}"
echo "Merged ${UPSTREAM_REPO}@${upstream_sha}"
