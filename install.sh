#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
BIN_DIR=${CODEX_HOME:-"$HOME/.codex"}/bin
SKILL_DIR=${CODEX_HOME:-"$HOME/.codex"}/skills

mkdir -p "$BIN_DIR"
mkdir -p "$SKILL_DIR"
ln -sfn "$ROOT/bootstrap/trellis-embedded-init" "$BIN_DIR/trellis-embedded-init"
ln -sfn "$ROOT/bootstrap/trellis-branch" "$BIN_DIR/trellis-branch"

case "$(uname -s)" in
  Darwin)
    RUNTIME_ADAPTER="$ROOT/runtime/mac/bin/embedded-agent"
    ;;
  Linux)
    if grep -qi microsoft /proc/sys/kernel/osrelease 2>/dev/null; then
      RUNTIME_ADAPTER="$ROOT/runtime/wsl/bin/embedded-agent"
    else
      printf 'Unsupported Linux host: the embedded-agent Adapter requires WSL.\n' >&2
      exit 2
    fi
    ;;
  *)
    printf 'Unsupported host for embedded-agent Adapter: %s\n' "$(uname -s)" >&2
    exit 2
    ;;
esac
ln -sfn "$RUNTIME_ADAPTER" "$BIN_DIR/embedded-agent"

for skill_source in "$ROOT"/skills/*; do
  [ -f "$skill_source/SKILL.md" ] || continue
  skill_name=$(basename "$skill_source")
  skill_target="$SKILL_DIR/$skill_name"
  if [ ! -e "$skill_target" ] && [ ! -L "$skill_target" ]; then
    ln -s "$skill_source" "$skill_target"
  elif [ -L "$skill_target" ] && [ "$(readlink "$skill_target")" = "$skill_source" ]; then
    :
  else
    printf 'Skipped existing skill: %s\n' "$skill_target" >&2
  fi
done

printf 'Installed:\n  %s\n  %s\n  %s\nSkills source:\n  %s\n' \
  "$BIN_DIR/trellis-embedded-init" \
  "$BIN_DIR/trellis-branch" \
  "$BIN_DIR/embedded-agent" \
  "$SKILL_DIR"
