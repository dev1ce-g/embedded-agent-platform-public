#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
BIN_DIR=${EMBEDDED_PLATFORM_BIN_DIR:-"${HOME}/.local/bin"}
SKILL_DIR=${EMBEDDED_PLATFORM_SKILL_DIR:-"${HOME}/.local/share/embedded-agent-platform/skills"}

mkdir -p "$BIN_DIR"
mkdir -p "$SKILL_DIR"

install_managed_link() {
  source_path=$1
  target_path=$2
  managed_prefix=$3
  if [ -L "$target_path" ]; then
    current_target=$(readlink "$target_path")
    case "$current_target" in
      "$managed_prefix"/*) ln -sfn "$source_path" "$target_path" ;;
      *)
        printf 'Refusing to replace unmanaged symlink: %s -> %s\n' "$target_path" "$current_target" >&2
        exit 2
        ;;
    esac
  elif [ -e "$target_path" ]; then
    printf 'Refusing to replace existing path: %s\n' "$target_path" >&2
    exit 2
  else
    ln -s "$source_path" "$target_path"
  fi
}

install_managed_link "$ROOT/bootstrap/embedded-project" "$BIN_DIR/embedded-project" "$ROOT/bootstrap"
install_managed_link "$ROOT/bootstrap/embedded-agent-branch" "$BIN_DIR/embedded-agent-branch" "$ROOT/bootstrap"

for legacy_link in "$BIN_DIR/trellis-embedded-init" "$BIN_DIR/trellis-branch"; do
  if [ -L "$legacy_link" ]; then
    case "$(readlink "$legacy_link")" in
      "$ROOT"/bootstrap/*) rm -f "$legacy_link" ;;
    esac
  fi
done

case "$(uname -s)" in
  Darwin)
    RUNTIME_ADAPTER="$ROOT/runtime/mac/bin/embedded-agent"
    ;;
  Linux)
    if grep -qi microsoft /proc/sys/kernel/osrelease 2>/dev/null; then
      RUNTIME_ADAPTER="$ROOT/runtime/wsl/bin/embedded-agent"
    else
      RUNTIME_ADAPTER="$ROOT/runtime/mac/bin/embedded-agent"
    fi
    ;;
  *)
    printf 'Unsupported host for embedded-agent Adapter: %s\n' "$(uname -s)" >&2
    exit 2
    ;;
esac
install_managed_link "$RUNTIME_ADAPTER" "$BIN_DIR/embedded-agent" "$ROOT/runtime"

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
  "$BIN_DIR/embedded-project" \
  "$BIN_DIR/embedded-agent-branch" \
  "$BIN_DIR/embedded-agent" \
  "$SKILL_DIR"

case ":${PATH:-}:" in
  *":$BIN_DIR:"*) ;;
  *) printf 'Add %s to PATH before using the installed commands.\n' "$BIN_DIR" >&2 ;;
esac
printf 'Keep this checkout in place; installed commands and Skills link to %s.\n' "$ROOT"
