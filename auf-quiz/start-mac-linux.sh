#!/bin/sh
# Port 80 needs administrator rights on macOS/Linux; without them the server uses port 8000.
cd "$(dirname "$0")" && exec python3 server.py "$@"
