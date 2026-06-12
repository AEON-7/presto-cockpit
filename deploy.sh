#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

MPREMOTE="${MPREMOTE:-}"
[ -n "$MPREMOTE" ] || MPREMOTE="$(command -v mpremote 2>/dev/null || true)"
if [ -z "$MPREMOTE" ]; then
  for c in "$HOME"/Library/Python/*/bin/mpremote "$HOME"/.local/bin/mpremote; do
    [ -x "$c" ] && { MPREMOTE="$c"; break; }
  done
fi
[ -n "$MPREMOTE" ] || { echo "mpremote not found; pip3 install --user mpremote" >&2; exit 1; }

./gen-secrets.sh

DEV="${PRESTO_DEV:-auto}"
if [ "$DEV" = "auto" ]; then
  DEV="$("$MPREMOTE" devs 2>/dev/null | awk '/usbmodem/ {print $1; exit}')"
fi
if [ -z "$DEV" ]; then
  echo "no Presto found; plug in USB-C and try again" >&2
  exit 1
fi
echo "deploying to $DEV"

mk() { "$MPREMOTE" connect "$DEV" exec "import os; os.mkdir('$1')" 2>/dev/null || true; }
push() { echo "  $1 -> :$2"; "$MPREMOTE" connect "$DEV" cp "$1" ":$2"; }

mk app
for d in hw net screens lights; do mk "app/$d"; done
mk images

push secrets.json /secrets.json
push boot.py      /boot.py
push main.py      /main.py

for f in app/*.py app/hw/*.py app/net/*.py app/screens/*.py app/lights/*.py; do
  [ -f "$f" ] && push "$f" "/$f"
done

if compgen -G "images/*.jpg" > /dev/null; then
  for f in images/*.jpg; do push "$f" "/images/$(basename "$f")"; done
fi

echo "soft-resetting..."
"$MPREMOTE" connect "$DEV" soft-reset
echo "done. live REPL: mpremote connect $DEV repl"
