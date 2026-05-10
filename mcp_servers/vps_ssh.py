#!/usr/bin/env python3
"""MCP server: SSH tools for the personal assistant VPS.

Register with Claude Code:
    claude mcp add vps-ssh python C:\Users\surgi\personal-assistant\mcp_servers\vps_ssh.py

SSH key auth must be set up (password prompts are not supported in batch mode).
To use a specific key set VPS_SSH_KEY=/path/to/key in the MCP server env.
"""

import os
import subprocess

from mcp.server.fastmcp import FastMCP

VPS_HOST = os.getenv("VPS_HOST", "187.77.215.152")
VPS_USER = os.getenv("VPS_USER", "root")
VPS_DIR = os.getenv("VPS_DIR", "~/personal-assistant")
SSH_KEY = os.getenv("VPS_SSH_KEY", "")

mcp = FastMCP("vps-ssh")


def _ssh(command: str, timeout: int = 60) -> str:
    args = [
        "ssh",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=10",
        "-o", "BatchMode=yes",
    ]
    if SSH_KEY:
        args += ["-i", SSH_KEY]
    args += [f"{VPS_USER}@{VPS_HOST}", command]

    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        out = result.stdout
        if result.stderr:
            out += ("\n" if out else "") + f"[stderr]\n{result.stderr}"
        return out.strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return f"[error: timed out after {timeout}s]"
    except FileNotFoundError:
        return "[error: ssh not found — install OpenSSH Client via Windows Settings]"
    except Exception as exc:
        return f"[error: {exc}]"


@mcp.tool()
def vps_run(command: str) -> str:
    """Run any shell command on the VPS and return stdout + stderr."""
    return _ssh(command)


@mcp.tool()
def vps_logs(service: str = "", tail: int = 100) -> str:
    """
    Fetch docker compose logs from the VPS.

    Args:
        service: container name, e.g. 'bot'. Leave empty for all services.
        tail: number of recent lines to return (default 100).
    """
    svc = service.strip()
    cmd = f"cd {VPS_DIR} && docker compose logs --tail={tail} --no-color {svc} 2>&1"
    return _ssh(cmd, timeout=30)


@mcp.tool()
def vps_status() -> str:
    """Show docker compose service status on the VPS."""
    return _ssh(f"cd {VPS_DIR} && docker compose ps 2>&1")


@mcp.tool()
def vps_restart(service: str = "") -> str:
    """
    Restart docker compose services on the VPS.

    Args:
        service: service name to restart, e.g. 'bot'. Leave empty to restart all.
    """
    svc = service.strip()
    return _ssh(f"cd {VPS_DIR} && docker compose restart {svc} 2>&1", timeout=60)


@mcp.tool()
def vps_deploy() -> str:
    """Pull latest code, rebuild, and restart the bot on the VPS."""
    cmd = (
        f"cd {VPS_DIR} && "
        "git pull && "
        "docker compose build --no-cache bot && "
        "docker compose up -d"
    )
    return _ssh(cmd, timeout=300)


if __name__ == "__main__":
    mcp.run()
