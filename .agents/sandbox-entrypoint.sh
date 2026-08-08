#!/bin/bash
# Sandbox entrypoint
# Copies per-dispatch opencode.json and plugin file from workspace to
# config dir, then starts the opencode server.

CONFIG_DIR="/root/.config/opencode"
WORKSPACE="/data/workspace"

for i in $(seq 1 30); do
    if [ -f "$WORKSPACE/opencode.json" ]; then
        cp "$WORKSPACE/opencode.json" "$CONFIG_DIR/opencode.json"
        echo "[entrypoint] applied workspace config"
        # Copy plugin files referenced in the plugin array
        for f in "$WORKSPACE"/*.ts "$WORKSPACE"/.opencode/plugins/*.ts; do
            [ -f "$f" ] && cp "$f" "$CONFIG_DIR/" && echo "[entrypoint] copied plugin $f"
        done
        break
    fi
    sleep 1
done

exec "$@"