#!/usr/bin/env sh
# GIS 多智能体 Web 控制台（macOS / Linux）
set -e
cd "$(dirname "$0")"
export PYTHONIOENCODING=utf-8
exec python server/app.py --open "$@"
