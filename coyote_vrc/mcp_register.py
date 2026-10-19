"""Registers the Coyote MCP server in the Claude Desktop app (claude_desktop_config.json).

Why it exists: `claude mcp add` only registers the server for Claude Code in the terminal. The Claude app
(and the chats tied to it) reads a different file, claude_desktop_config.json. This module adds the
"coyote" entry to that file WITHOUT removing what is already there:
  * if the file has a JSON error, it is left untouched and the problem is reported;
  * before any change, a copy is kept (.bak-DATE-TIME);
  * it writes to a temporary file and swaps it in, so the file is never left half-written.
The API token is NOT written here: coyote_mcp.py reads it from the app's settings.json, as always.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

SERVER_NAME = "coyote"
CONFIG_NAME = "claude_desktop_config.json"


class ConfigError(Exception):
    pass


@dataclass
class Result:
    path: Path
    action: str            # "created" | "updated" | "unchanged" | "error"
    backup: Optional[Path] = None
    error: str = ""


def python_for_mcp(exe: Optional[str] = None) -> str:
    """Python that will run the MCP server (the app's own; pythonw does not work for stdio)."""
    p = Path(exe or sys.executable)
    if p.name.lower() == "pythonw.exe":
        p = p.with_name("python.exe")
    return str(p)


def server_entry(python: str, script: str) -> dict:
    return {"command": str(python), "args": [str(script)]}


def mcp_launcher(script: Optional[str] = None) -> tuple:
    """(command, args) that Claude has to run for the MCP server: `python coyote_mcp.py` from source, or the packaged
    CoyoteVRChat.exe itself with --mcp."""
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable)), ["--mcp"]
    return python_for_mcp(), [str(script)]


def candidate_paths(environ=None) -> list:
    """Where Claude Desktop usually keeps its config on Windows (regular installer and Store version)."""
    env = os.environ if environ is None else environ
    paths = []
    if env.get("APPDATA"):
        paths.append(Path(env["APPDATA"]) / "Claude" / CONFIG_NAME)
    if env.get("LOCALAPPDATA"):
        paths.extend(sorted(Path(env["LOCALAPPDATA"]).glob(f"Packages/Claude_*/LocalCache/Roaming/Claude/{CONFIG_NAME}")))
    return paths


def merge_config(text: Optional[str], entry: dict, name: str = SERVER_NAME):
    """Puts `entry` in mcpServers[name]. Returns (new_text, action). Raises ConfigError if the file looks wrong."""
    if text is None or not text.strip():
        data: dict = {}
    else:
        try:
            data = json.loads(text.lstrip("﻿"))
        except ValueError as exc:
            raise ConfigError(f"the file is not valid JSON ({exc}); left it untouched") from exc
        if not isinstance(data, dict):
            raise ConfigError("the file is not a JSON object; left it untouched")
    servers = data.get("mcpServers")
    if servers is None:
        servers = {}
    elif not isinstance(servers, dict):
        raise ConfigError("'mcpServers' in the file is not an object; left it untouched")
    old = servers.get(name)
    action = "unchanged" if old == entry else ("created" if old is None else "updated")
    servers[name] = entry
    data["mcpServers"] = servers
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n", action


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def register_one(path: Path, entry: dict) -> Result:
    try:
        old_text = path.read_text(encoding="utf-8") if path.exists() else None
        new_text, action = merge_config(old_text, entry)
        if action == "unchanged":
            return Result(path, "unchanged")
        backup = None
        if old_text is not None:
            backup = path.with_name(path.name + time.strftime(".bak-%Y%m%d-%H%M%S"))
            shutil.copy2(path, backup)
        _write_atomic(path, new_text)
        return Result(path, action if old_text is not None else "created", backup)
    except ConfigError as exc:
        return Result(path, "error", error=str(exc))
    except OSError as exc:
        return Result(path, "error", error=f"{exc.strerror or exc}")


def register_desktop(python: str, script: str, paths: Optional[Iterable] = None, args: Optional[list] = None) -> list:
    """Registers in the config files that exist (or creates the default one if none exists).
    `args` replaces [script] when the command takes other arguments (the packaged .exe takes --mcp)."""
    entry = server_entry(python, script) if args is None else {"command": str(python), "args": [str(a) for a in args]}
    if paths is not None:
        targets = [Path(p) for p in paths]
    else:
        found = candidate_paths()
        targets = [p for p in found if p.exists()] or found[:1]
    if not targets:
        return [Result(Path(""), "error", error="could not find the Claude Desktop config folder (APPDATA variable)")]
    return [register_one(p, entry) for p in targets]
