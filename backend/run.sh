#!/bin/sh
# Serwer HALO -> Arcade.  ./backend/run.sh --install  (raz: środowisko)  |  ./backend/run.sh  (start)
set -e
cd "$(dirname "$0")/.."
if [ "$1" = "--install" ] || [ ! -x backend/.venv/bin/python ]; then
  PY=$(command -v python3.13 || command -v python3)
  "$PY" -m venv backend/.venv
  backend/.venv/bin/pip install -q -r backend/requirements.txt
  [ "$1" = "--install" ] && exit 0
fi
exec backend/.venv/bin/python -m backend "$@"
