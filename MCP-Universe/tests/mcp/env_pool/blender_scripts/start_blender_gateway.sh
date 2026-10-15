#!/bin/bash
# Start Blender MCP environment: Xvfb + Blender addon + MCP Gateway
#
# Architecture:
#   1. Xvfb (virtual display :99) + LIBGL_ALWAYS_SOFTWARE=1
#   2. Blender normal mode with addon (socket server on $BLENDER_ADDON_PORT)
#   3. MCP Gateway (SSE on $MCP_GATEWAY_PORT)
#
# The MCP server (mcpuniverse.mcp.servers.blender) connects to the addon
# socket server, and the Gateway exposes it via SSE.

set -e

export DISPLAY=${DISPLAY:-:99}
export LIBGL_ALWAYS_SOFTWARE=1
BLENDER_ADDON_PORT=${BLENDER_ADDON_PORT:-9876}
MCP_GATEWAY_PORT=${MCP_GATEWAY_PORT:-8000}
MCP_GATEWAY_MODE=${MCP_GATEWAY_MODE:-sse}
MCP_SERVERS=${MCP_SERVERS:-blender}

echo "=== Blender MCP Environment ==="
echo "Display:     $DISPLAY"
echo "Addon port:  $BLENDER_ADDON_PORT"
echo "Gateway:     $MCP_GATEWAY_MODE on port $MCP_GATEWAY_PORT"
echo "Servers:     $MCP_SERVERS"
echo "LIBGL:       $LIBGL_ALWAYS_SOFTWARE"
echo "==============================="

# 1. Start Xvfb
echo "Starting Xvfb on $DISPLAY..."
Xvfb $DISPLAY -screen 0 1024x768x24 -ac +extension GLX +render -noreset &
XVFB_PID=$!
sleep 2

# Verify Xvfb is running
if ! kill -0 $XVFB_PID 2>/dev/null; then
    echo "ERROR: Xvfb failed to start" >&2
    exit 1
fi
echo "Xvfb started (PID $XVFB_PID)"

# 2. Start Blender with addon
echo "Starting Blender with MCP addon..."
python /app/start_blender_addon.py &
BLENDER_PID=$!

# Wait for addon socket server to be ready
echo "Waiting for Blender addon socket server on port $BLENDER_ADDON_PORT..."
for i in $(seq 1 60); do
    if nc -z localhost $BLENDER_ADDON_PORT 2>/dev/null; then
        echo "Blender addon ready on port $BLENDER_ADDON_PORT"
        break
    fi
    if ! kill -0 $BLENDER_PID 2>/dev/null; then
        echo "ERROR: Blender process exited unexpectedly" >&2
        exit 1
    fi
    sleep 2
done

if ! nc -z localhost $BLENDER_ADDON_PORT 2>/dev/null; then
    echo "ERROR: Blender addon not ready after 120s" >&2
    exit 1
fi

# 3. Start MCP Gateway
echo "Starting MCP Gateway..."
exec python -m mcpuniverse.mcp.gateway \
    --port $MCP_GATEWAY_PORT \
    --mode $MCP_GATEWAY_MODE \
    --servers $MCP_SERVERS
