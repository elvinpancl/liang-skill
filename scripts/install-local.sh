#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CLAUDE_ROOT="${CLAUDE_SKILLS_ROOT:-$HOME/.claude/skills}"
CODEX_ROOT="${CODEX_SKILLS_ROOT:-$HOME/.codex/skills}"
APPLY=false
RETIRED_SKILLS=(
  liang-money
  liang-money-intake
  liang-money-scout
  liang-money-vet
  liang-money-pledge
  liang-money-settle
  liang-career
  liang-career-intake
  liang-career-scan
  liang-career-plan
  liang-career-coach
)

if [[ "${1:-}" == "--apply" ]]; then
  APPLY=true
elif [[ -n "${1:-}" ]]; then
  echo "usage: $0 [--apply]" >&2
  exit 2
fi

mapfile_compat() {
  while IFS= read -r line; do
    SKILL_DIRS+=("$line")
  done
}

SKILL_DIRS=()
mapfile_compat < <(find "$REPO_ROOT/skills" -mindepth 2 -maxdepth 2 -name SKILL.md -print | sed 's#/SKILL.md$##' | sort)

if [[ ${#SKILL_DIRS[@]} -eq 0 ]]; then
  echo "no top-level skills found under $REPO_ROOT/skills" >&2
  exit 1
fi

link_one() {
  local source_dir="$1"
  local target_root="$2"
  local name target existing
  name="$(basename "$source_dir")"
  target="$target_root/$name"

  if [[ -e "$target" && ! -L "$target" ]]; then
    echo "refusing to replace non-symlink: $target" >&2
    return 1
  fi

  if [[ -L "$target" ]]; then
    existing="$(readlink "$target")"
    if [[ "$existing" == "$source_dir" ]]; then
      printf 'ok      %s -> %s\n' "$target" "$source_dir"
      return 0
    fi
  fi

  if [[ "$APPLY" == true ]]; then
    ln -sfn "$source_dir" "$target"
    printf 'linked  %s -> %s\n' "$target" "$source_dir"
  else
    printf 'would   %s -> %s\n' "$target" "$source_dir"
  fi
}

retire_one() {
  local target_root="$1"
  local name="$2"
  local target expected existing
  target="$target_root/$name"
  expected="$REPO_ROOT/skills/$name"

  if [[ ! -L "$target" ]]; then
    if [[ -e "$target" ]]; then
      echo "refusing to remove non-symlink retired skill: $target" >&2
      return 1
    fi
    return 0
  fi

  existing="$(readlink "$target")"
  if [[ "$existing" != "$expected" ]]; then
    echo "refusing to remove unrelated symlink: $target -> $existing" >&2
    return 1
  fi

  if [[ "$APPLY" == true ]]; then
    unlink "$target"
    printf 'retired %s\n' "$target"
  else
    printf 'would retire %s\n' "$target"
  fi
}

if [[ "$APPLY" == true ]]; then
  mkdir -p "$CLAUDE_ROOT" "$CODEX_ROOT"
else
  echo "dry-run; pass --apply to create or refresh links"
fi

for skill_dir in "${SKILL_DIRS[@]}"; do
  link_one "$skill_dir" "$CLAUDE_ROOT"
  link_one "$skill_dir" "$CODEX_ROOT"
done

for name in "${RETIRED_SKILLS[@]}"; do
  retire_one "$CLAUDE_ROOT" "$name"
  retire_one "$CODEX_ROOT" "$name"
done

printf 'skills=%d hosts=2 apply=%s\n' "${#SKILL_DIRS[@]}" "$APPLY"
