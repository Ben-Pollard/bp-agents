#!/bin/bash
# Sandbox entrypoint
# Waits for per-dispatch opencode.json from workspace, copies to config dir,
# then starts the opencode server.

CONFIG_SRC="/data/workspace/opencode.json"
CONFIG_DST="/root/.config/opencode/opencode.json"

# Poll for config file (written by dispatch after container creation)
for i in $(seq 1 30); do
    if [ -f "$CONFIG_SRC" ]; then
        cp "$CONFIG_SRC" "$CONFIG_DST"
        echo "[entrypoint] applied workspace config"
        break
    fi
    sleep 1
done

exec "$@"