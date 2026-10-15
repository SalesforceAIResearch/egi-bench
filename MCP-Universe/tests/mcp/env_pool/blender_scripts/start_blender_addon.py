"""Launch Blender with MCP addon socket server.

Runs Blender in normal mode (using Xvfb virtual display) so addon operators
work correctly. The addon opens a socket server on BLENDER_ADDON_PORT.

Requires:
    - Xvfb running on $DISPLAY (started by start_blender_gateway.sh)
    - LIBGL_ALWAYS_SOFTWARE=1 for software OpenGL rendering
    - Addon source at /app/blender_addon/addon.py

Usage (called by start_blender_gateway.sh):
    python start_blender_addon.py
"""

import os
import shutil
import subprocess
import sys
import time

ADDON_SRC = "/app/blender_addon/addon.py"
ADDON_PORT = int(os.environ.get("BLENDER_ADDON_PORT", "9876"))

BLENDER_ADDONS_DIR = os.path.expanduser(
    "~/.config/blender/4.0/scripts/addons"
)


def install_addon():
    """Install addon.py into Blender's addons directory."""
    addon_dir = os.path.join(BLENDER_ADDONS_DIR, "blender_mcp")
    os.makedirs(addon_dir, exist_ok=True)

    init_path = os.path.join(addon_dir, "__init__.py")
    shutil.copy2(ADDON_SRC, init_path)
    print(f"Addon installed to {init_path}")


def start_blender():
    """Start Blender with addon enabled via Xvfb display."""
    # Script that Blender will execute on startup.
    # Uses a timer to start the socket server AFTER Blender is fully initialized,
    # avoiding operator context issues.
    enable_script = f"""
import bpy
import addon_utils
import sys
import traceback

def _start_addon_server():
    \"\"\"Enable addon and start socket server via timer callback.\"\"\"
    try:
        addon_utils.enable("blender_mcp", default_set=True)
        print("Addon enabled, starting server...", flush=True)

        # Try operator approach first (needs VIEW_3D area context)
        started = False
        try:
            for area in bpy.context.screen.areas:
                if area.type == 'VIEW_3D':
                    with bpy.context.temp_override(area=area):
                        bpy.ops.blender_mcp.start_server(port={ADDON_PORT})
                        started = True
                        break
            if not started:
                bpy.ops.blender_mcp.start_server(port={ADDON_PORT})
                started = True
        except Exception as e:
            print(f"Operator approach failed: {{e}}", flush=True)

        # Fallback: start server directly from addon module
        if not started:
            print("Trying direct server start...", flush=True)
            import blender_mcp
            # Look for server class or start function
            for attr_name in dir(blender_mcp):
                obj = getattr(blender_mcp, attr_name)
                if isinstance(obj, type) and 'server' in attr_name.lower():
                    try:
                        srv = obj()
                        if hasattr(srv, 'start'):
                            srv.start()
                            started = True
                            print(f"Started server via {{attr_name}}", flush=True)
                            break
                    except Exception:
                        pass
            if not started and hasattr(blender_mcp, 'start_server'):
                blender_mcp.start_server(port={ADDON_PORT})
                started = True

        if not started:
            print("FATAL: Could not start addon server", flush=True)
            sys.exit(1)

    except Exception as e:
        print(f"FATAL: Addon start error: {{e}}", flush=True)
        traceback.print_exc()
        sys.exit(1)

    print("BLENDER_ADDON_READY", flush=True)
    return None  # Don't repeat timer

# Register timer to run after Blender finishes initialization
bpy.app.timers.register(_start_addon_server, first_interval=2.0)
"""

    script_path = "/tmp/enable_addon.py"
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(enable_script)

    # Run Blender in NORMAL mode (not --background) with Xvfb providing display.
    # --factory-startup ensures clean state (no user prefs that could interfere).
    # LIBGL_ALWAYS_SOFTWARE=1 forces software OpenGL rendering (no GPU needed).
    cmd = [
        "blender",
        "--factory-startup",
        "--python", script_path,
    ]

    env = os.environ.copy()
    env["LIBGL_ALWAYS_SOFTWARE"] = "1"

    display = env.get("DISPLAY", "?")
    print(f"Starting Blender (DISPLAY={display}, "
          f"LIBGL_ALWAYS_SOFTWARE={env.get('LIBGL_ALWAYS_SOFTWARE', '?')}) "
          f"with addon on port {ADDON_PORT}...")

    proc = subprocess.Popen(  # pylint: disable=consider-using-with
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )

    # Wait for addon to be ready
    deadline = time.time() + 120  # Blender GUI init can be slow
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                print(f"Blender exited with code {proc.returncode}",
                      file=sys.stderr)
                sys.exit(1)
            continue
        line = line.rstrip()
        print(f"[blender] {line}")
        if "BLENDER_ADDON_READY" in line:
            print("Blender addon is ready")
            return proc

    print("Timed out waiting for Blender addon (120s)", file=sys.stderr)
    proc.kill()
    sys.exit(1)


if __name__ == "__main__":
    install_addon()
    blender_proc = start_blender()

    # Keep running, relay Blender output
    try:
        for output_line in blender_proc.stdout:
            print(f"[blender] {output_line.rstrip()}")
        blender_proc.wait()
    except KeyboardInterrupt:
        blender_proc.terminate()
        blender_proc.wait()
