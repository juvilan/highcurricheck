#!/bin/bash
# highcurricheck Flask 실행 (PM2용)
cd "$(dirname "$0")" || exit 1
export PORT=4001
exec .venv/bin/python server.py
