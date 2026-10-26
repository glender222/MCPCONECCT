#!/bin/bash
export DISPLAY="${DISPLAY:-:1}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Check if dashboard backend is running on port 8765
if ! ss -tulpn 2>/dev/null | grep -q ":8765\b"; then
    echo "Iniciando backend API de MCPCONECCT en segundo plano (puerto 8765)..."
    nohup "$DIR/venv/bin/python" "$DIR/run_dashboard.py" --port 8765 > /dev/null 2>&1 &
    sleep 1.5
fi

echo "Iniciando MCPCONECCT Desktop App en DISPLAY=${DISPLAY}..."
exec "$DIR/desktop_app/target/debug/mcpconecct-desktop" "$@"
