#!/bin/bash

# MCP-Universe Services Launch Script
# NOTE: It is a REFERENCE script and we can not guarantee it will work in all environments!

# This script starts the Blender instance with the MCP addon.
# It also starts a VNC server, and noVNC web interface for debugging.
# It will automatically download and setup Blender and noVNC if not present

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# !!! Change your configuration here !!!
# Configuration
DISPLAY_NUMBER=":99"
DISPLAY_NUM="99"
VNC_PORT="5999"
NOVNC_PORT="6080"
BLENDER_MCP_PORT="9876"
VNC_DIR="novnc"
BLENDER_VERSION="4.4.0"
BLENDER_DOWNLOAD_URL="https://download.blender.org/release/Blender4.4/blender-4.4.0-linux-x64.tar.xz"
BLENDER_INSTALL_DIR="applications"
BLENDER_PATH="$BLENDER_INSTALL_DIR/blender-$BLENDER_VERSION-linux-x64/blender"
BLENDER_ADDON="blender_addon.py"
LOG_DIR="mcp_services_logs"
NOVNC_REPO="https://github.com/novnc/noVNC.git"
# !!! End of configuration !!!

# Create necessary directories
mkdir -p "$LOG_DIR"
mkdir -p "$BLENDER_INSTALL_DIR"
mkdir -p "$VNC_DIR"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}MCP-Universe Services Launch Script${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Function to check if a process is running
check_process() {
    if pgrep -f "$1" > /dev/null; then
        return 0
    else
        return 1
    fi
}

# Function to wait for a port to be available
wait_for_port() {
    local port=$1
    local timeout=30
    local count=0
    
    echo -e "${YELLOW}Waiting for port $port to be available...${NC}"
    while [ $count -lt $timeout ]; do
        if ss -tuln 2>/dev/null | grep -q ":$port " || netstat -tuln 2>/dev/null | grep -q ":$port "; then
            echo -e "${GREEN}✓ Port $port is available${NC}"
            return 0
        fi
        sleep 1
        count=$((count + 1))
    done
    
    echo -e "${RED}✗ Timeout waiting for port $port${NC}"
    return 1
}

# 0. Setup: Download and install dependencies if needed
echo -e "${YELLOW}[0/4] Checking and installing dependencies...${NC}"

# Check and install Blender
if [ ! -f "$BLENDER_PATH" ]; then
    echo -e "${YELLOW}Blender not found. Downloading and installing...${NC}"
    
    cd "$BLENDER_INSTALL_DIR" || exit 1
    
    # Download Blender
    echo -e "${BLUE}Downloading Blender $BLENDER_VERSION...${NC}"
    wget -O blender.tar.xz "$BLENDER_DOWNLOAD_URL" 2>&1 | tee "$LOG_DIR/blender_download.log"
    
    if [ $? -ne 0 ]; then
        echo -e "${RED}✗ Failed to download Blender${NC}"
        exit 1
    fi
    
    # Extract Blender
    echo -e "${BLUE}Extracting Blender...${NC}"
    tar -xf blender.tar.xz
    
    if [ $? -ne 0 ]; then
        echo -e "${RED}✗ Failed to extract Blender${NC}"
        exit 1
    fi
    
    # Clean up
    rm blender.tar.xz
    
    # Verify installation
    if [ -f "$BLENDER_PATH" ]; then
        echo -e "${GREEN}✓ Blender installed successfully at $BLENDER_PATH${NC}"
    else
        echo -e "${RED}✗ Blender installation failed${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}✓ Blender already installed at $BLENDER_PATH${NC}"
fi

# Check and install noVNC
if [ ! -d "$VNC_DIR/noVNC" ]; then
    echo -e "${YELLOW}noVNC not found. Cloning repository...${NC}"
    
    cd "$VNC_DIR" || exit 1
    
    # Clone noVNC
    echo -e "${BLUE}Cloning noVNC...${NC}"
    git clone "$NOVNC_REPO" 2>&1 | tee "$LOG_DIR/novnc_clone.log"
    
    if [ $? -ne 0 ]; then
        echo -e "${RED}✗ Failed to clone noVNC${NC}"
        exit 1
    fi
    
    # Verify installation
    if [ -f "$VNC_DIR/noVNC/utils/novnc_proxy" ]; then
        echo -e "${GREEN}✓ noVNC installed successfully${NC}"
    else
        echo -e "${RED}✗ noVNC installation failed${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}✓ noVNC already installed at $VNC_DIR/noVNC${NC}"
fi

# Verify addon exists
if [ ! -f "$BLENDER_ADDON" ]; then
    echo -e "${RED}✗ Blender addon not found at $BLENDER_ADDON${NC}"
    echo -e "${YELLOW}Please ensure MCP-Universe is cloned to /root/MCP-Universe${NC}"
    exit 1
else
    echo -e "${GREEN}✓ Blender MCP addon found${NC}"
fi

echo ""

# 1. Start VNC Server (provides X display on configured display number)
echo -e "${YELLOW}[1/4] Checking/Starting VNC Server on display $DISPLAY_NUMBER...${NC}"

# Check if Xvfb is running (conflict with VNC)
if check_process "Xvfb $DISPLAY_NUMBER"; then
    echo -e "${YELLOW}Found Xvfb on $DISPLAY_NUMBER, stopping it (VNC required)...${NC}"
    pkill -f "Xvfb $DISPLAY_NUMBER" || true
    sleep 3
fi

# Check if VNC server is already running
if check_process "Xvnc $DISPLAY_NUMBER"; then
    echo -e "${GREEN}✓ VNC Server is already running on $DISPLAY_NUMBER${NC}"
else
    # Kill any existing VNC server
    vncserver -kill $DISPLAY_NUMBER 2>/dev/null || true
    sleep 3
    
    # Start VNC server (provides both X server and VNC access)
    OUTPUT=$(vncserver $DISPLAY_NUMBER -localhost -geometry 1920x1080 -depth 24 2>&1)
    VNC_EXIT_CODE=$?
    echo "$OUTPUT" > "$LOG_DIR/vncserver.log"
    
    # Check if the output indicates success
    if echo "$OUTPUT" | grep -q "New.*server.*on port"; then
        echo -e "${GREEN}✓ VNC Server started successfully on $DISPLAY_NUMBER${NC}"
    elif [ $VNC_EXIT_CODE -ne 0 ]; then
        echo -e "${RED}✗ Failed to start VNC Server${NC}"
        echo -e "${YELLOW}Log output:${NC}"
        echo "$OUTPUT"
        exit 1
    else
        # Wait and verify process is running
        sleep 5
        
        if check_process "Xvnc" || check_process "Xtigervnc"; then
            echo -e "${GREEN}✓ VNC Server started successfully on $DISPLAY_NUMBER${NC}"
        else
            echo -e "${RED}✗ VNC Server process not running${NC}"
            echo "$OUTPUT"
            exit 1
        fi
    fi
fi

export DISPLAY=$DISPLAY_NUMBER
echo -e "${BLUE}DISPLAY set to $DISPLAY_NUMBER (VNC port: $VNC_PORT)${NC}"
echo ""

# 2. Start noVNC
echo -e "${YELLOW}[2/4] Starting noVNC web interface...${NC}"

# Kill existing noVNC processes to avoid duplicates
pkill -f novnc_proxy 2>/dev/null || true
sleep 1

if check_process "novnc_proxy"; then
    echo -e "${YELLOW}noVNC still running, force killing...${NC}"
    pkill -9 -f novnc_proxy 2>/dev/null || true
    sleep 1
fi

cd "$VNC_DIR" || { echo -e "${RED}✗ Cannot access VNC directory${NC}"; exit 1; }

# Check if noVNC exists
if [ ! -f "./noVNC/utils/novnc_proxy" ]; then
    echo -e "${RED}✗ noVNC not found at $VNC_DIR/noVNC${NC}"
    exit 1
fi

# Start noVNC proxy with configured VNC port
echo -e "${BLUE}Starting noVNC with VNC port: $VNC_PORT${NC}"
./noVNC/utils/novnc_proxy --vnc localhost:$VNC_PORT --listen localhost:$NOVNC_PORT > "$LOG_DIR/novnc.log" 2>&1 &
sleep 3

if check_process "novnc_proxy"; then
    echo -e "${GREEN}✓ noVNC started successfully${NC}"
    wait_for_port $NOVNC_PORT || echo -e "${YELLOW}  Warning: Port $NOVNC_PORT check timed out but process is running${NC}"
else
    echo -e "${RED}✗ Failed to start noVNC${NC}"
    cat "$LOG_DIR/novnc.log"
    exit 1
fi

cd - > /dev/null

echo -e "${BLUE}noVNC web interface: http://localhost:$NOVNC_PORT/vnc.html${NC}"
echo ""

# 3. Start Blender with MCP addon
echo -e "${YELLOW}[3/4] Starting Blender with MCP addon...${NC}"

# Kill any existing Blender processes
if check_process "blender"; then
    echo -e "${YELLOW}Stopping existing Blender instances...${NC}"
    pkill -f blender || true
    sleep 2
fi

# Verify Blender exists
if [ ! -f "$BLENDER_PATH" ]; then
    echo -e "${RED}✗ Blender not found at $BLENDER_PATH${NC}"
    exit 1
fi

# Verify addon exists
if [ ! -f "$BLENDER_ADDON" ]; then
    echo -e "${RED}✗ Blender addon not found at $BLENDER_ADDON${NC}"
    exit 1
fi

# Create a startup script that loads the addon and keeps Blender running
cat > /tmp/blender_startup.py << 'STARTUP_EOF'
import bpy
import sys
import time

# Get the addon path from command line arguments
addon_path = sys.argv[-1] if sys.argv[-1].endswith('.py') else None

if addon_path:
    print(f"Loading Blender MCP addon from: {addon_path}")
    
    # Load and execute the addon
    with open(addon_path, 'r') as f:
        addon_code = f.read()
    
    # Execute the addon code in the global namespace
    exec(addon_code, globals())
    
    print("Blender MCP addon loaded successfully")
else:
    print("ERROR: No addon path provided")
    sys.exit(1)

# Keep Blender running with a timer
def keep_alive():
    return 1.0  # Return to be called again in 1 second

bpy.app.timers.register(keep_alive, persistent=True)

print("Blender is now running with MCP addon. Press Ctrl+C in terminal to stop.")
STARTUP_EOF

# Start Blender with the startup script
echo -e "${BLUE}Starting Blender with MCP addon...${NC}"
DISPLAY=$DISPLAY_NUMBER "$BLENDER_PATH" --python /tmp/blender_startup.py -- "$BLENDER_ADDON" > "$LOG_DIR/blender.log" 2>&1 &
BLENDER_PID=$!
echo -e "${BLUE}Started Blender with PID: $BLENDER_PID${NC}"

# Wait for Blender to start
sleep 8

if check_process "blender"; then
    echo -e "${GREEN}✓ Blender is running${NC}"
else
    echo -e "${RED}✗ Blender process not found${NC}"
    echo -e "${YELLOW}Last 30 lines of Blender log:${NC}"
    tail -30 "$LOG_DIR/blender.log"
    exit 1
fi
echo ""

# 4. Verify Blender MCP addon is loaded
echo -e "${YELLOW}[4/4] Verifying Blender MCP addon...${NC}"
sleep 5

# Create a Python verification script
cat > /tmp/verify_blender_addon.py << 'VERIFY_EOF'
#!/usr/bin/env python3
import socket
import json
import time
import sys

def verify_blender_mcp():
    """Verify that the Blender MCP addon is loaded and responding"""
    
    import os
    port = int(os.environ.get('BLENDER_MCP_PORT', '9876'))
    host = 'localhost'
    
    print(f"Checking Blender MCP server on {host}:{port}...")
    
    max_attempts = 15
    for attempt in range(max_attempts):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((host, port))
            
            if result == 0:
                print(f"✓ SUCCESS: Blender MCP server is running on port {port}")
                print(f"✓ The addon is loaded correctly")
                
                # Try to send a test command
                try:
                    test_command = {
                        "jsonrpc": "2.0",
                        "method": "list_tools",
                        "params": {},
                        "id": 1
                    }
                    sock.sendall((json.dumps(test_command) + '\n').encode())
                    sock.settimeout(5)
                    response = sock.recv(4096).decode()
                    
                    if response:
                        print(f"✓ Server responded to test command. (It's fine if the server responded an error - we are only testing connectivity here)")
                        if len(response) > 200:
                            print(f"  Response preview: {response[:200]}...")
                        else:
                            print(f"  Response: {response}")
                    
                except Exception as e:
                    print(f"  Note: Connection successful but command test failed: {e}")
                
                sock.close()
                return True
            else:
                sock.close()
                print(f"  Attempt {attempt + 1}/{max_attempts}: Port not open yet, waiting...")
                time.sleep(3)
                
        except Exception as e:
            print(f"  Attempt {attempt + 1}/{max_attempts}: {e}")
            time.sleep(3)
    
    print(f"✗ FAILED: Could not connect to Blender MCP server on port {port}")
    return False

if __name__ == "__main__":
    success = verify_blender_mcp()
    sys.exit(0 if success else 1)
VERIFY_EOF

chmod +x /tmp/verify_blender_addon.py

# Run the verification script with port as environment variable
if BLENDER_MCP_PORT=$BLENDER_MCP_PORT python3 /tmp/verify_blender_addon.py; then
    echo -e "${GREEN}✓ Blender MCP addon verification successful${NC}"
else
    echo -e "${RED}✗ Blender MCP addon verification failed${NC}"
    echo -e "${YELLOW}Blender log (last 30 lines):${NC}"
    tail -30 "$LOG_DIR/blender.log"
fi
echo ""

# Summary
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Service Launch Summary${NC}"
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}Services Status:${NC}"
echo ""
echo -e "  ${GREEN}✓${NC} VNC Server (Display $DISPLAY_NUMBER) - Running"
echo -e "  ${GREEN}✓${NC} noVNC Web Interface - Running"
echo -e "  ${GREEN}✓${NC} Blender with MCP addon - Running"
echo ""
echo -e "${BLUE}Access Information:${NC}"
echo -e "  • noVNC URL:    ${BLUE}http://localhost:$NOVNC_PORT/vnc.html${NC}"
echo -e "  • Blender MCP:  ${BLUE}localhost:$BLENDER_MCP_PORT${NC}"
echo -e "  • Display:      ${BLUE}$DISPLAY_NUMBER${NC}"
echo ""
echo -e "${BLUE}Log Files:${NC}"
echo -e "  • VNC:      ${BLUE}$LOG_DIR/vncserver.log${NC}"
echo -e "  • noVNC:    ${BLUE}$LOG_DIR/novnc.log${NC}"
echo -e "  • Blender:  ${BLUE}$LOG_DIR/blender.log${NC}"
echo ""
echo -e "${YELLOW}Commands:${NC}"
echo -e "  Stop all:  ${YELLOW}vncserver -kill $DISPLAY_NUMBER && pkill novnc_proxy && pkill blender${NC}"
echo -e "  View logs: ${YELLOW}tail -f $LOG_DIR/blender.log${NC}"
echo -e "${BLUE}========================================${NC}"
