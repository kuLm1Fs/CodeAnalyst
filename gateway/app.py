from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from agent.memory.store import MemoryStore
from agent.runtime.agent.agent import Agent
from agent.trace.trace import make_session_id
from gateway.chat import run_chat as run_gateway_chat
from gateway.events import EventBroker
from gateway.state import GatewayState
from gateway.state import resolve_workspace_path
from gateway.trace_reader import read_trace_events


WORKSPACE = Path.cwd()
MEMORY_ROOT = WORKSPACE / ".memory"
TRACE_ROOT = WORKSPACE / ".trace"
SKILLS_ROOT = WORKSPACE / ".skills"
state = GatewayState(WORKSPACE)

broker = EventBroker()
session_workspaces = state.session_workspaces


def log(message: str) -> None:
    print(f"[gateway] {message}", flush=True)


def connection_label(websocket: ServerConnection) -> str:
    remote_address = getattr(websocket, "remote_address", None)
    if isinstance(remote_address, tuple) and len(remote_address) >= 2:
        return f"{remote_address[0]}:{remote_address[1]}"
    return "unknown-peer"


def configure_workspace(raw_workspace: str | None = None) -> Path:
    global WORKSPACE, MEMORY_ROOT, TRACE_ROOT, SKILLS_ROOT

    workspace = state.configure_default_workspace(raw_workspace or os.getenv("LUMAK_WORKSPACE", "") or str(Path.cwd()))
    WORKSPACE = workspace
    MEMORY_ROOT = state.memory_root
    TRACE_ROOT = state.trace_root
    SKILLS_ROOT = state.skills_root
    log(f"workspace configured: {workspace}")
    return workspace


def workspace_for_session(session_id: str) -> Path:
    return state.workspace_for_session(session_id)


def memory_root_for_session(session_id: str) -> Path:
    if session_id in session_workspaces:
        return state.memory_root_for_session(session_id)
    return MEMORY_ROOT


def build_project_detail(workspace: Path | None = None) -> dict[str, Any]:
    return state.project_detail(workspace or WORKSPACE)


def build_project_list(workspace: Path | None = None) -> list[dict[str, Any]]:
    return state.project_list(workspace or WORKSPACE)


def dumps(message: dict[str, Any]) -> str:
    return json.dumps(message, ensure_ascii=False)


async def send_json(websocket: ServerConnection, message: dict[str, Any]) -> None:
    await websocket.send(dumps(message))


def parse_message(raw_message: str | bytes) -> dict[str, Any]:
    if isinstance(raw_message, bytes):
        raw_message = raw_message.decode("utf-8")

    message = json.loads(raw_message)
    if not isinstance(message, dict):
        raise ValueError("websocket message must be a JSON object")
    return message


async def run_chat(websocket: ServerConnection, message: dict[str, Any]) -> None:
    await run_gateway_chat(
        websocket,
        message,
        state=state,
        broker=broker,
        send_json=send_json,
        log=log,
        agent_factory=Agent,
    )


async def send_memory(websocket: ServerConnection, message: dict[str, Any]) -> None:
    session_id = str(message.get("session_id") or "")
    if not session_id:
        await send_json(websocket, {"type": "error", "error": "session_id is required"})
        return

    workspace = workspace_for_session(session_id)
    log(f"memory get session={session_id} workspace={workspace}")
    store = MemoryStore(memory_root_for_session(session_id))
    await send_json(
        websocket,
        {
            "type": "memory.response",
            "session_id": session_id,
            "messages": store.load_messages(session_id),
        },
    )


async def send_conversation_list(websocket: ServerConnection) -> None:
    log(f"conversation list workspace={WORKSPACE}")
    store = MemoryStore(MEMORY_ROOT)
    await send_json(
        websocket,
        {
            "type": "conversation.list.response",
            "conversations": store.list_sessions(),
        },
    )


async def send_conversation(websocket: ServerConnection, message: dict[str, Any]) -> None:
    session_id = str(message.get("session_id") or "")
    if not session_id:
        await send_json(websocket, {"type": "error", "error": "session_id is required"})
        return

    workspace = workspace_for_session(session_id)
    store = MemoryStore(memory_root_for_session(session_id))
    log(f"conversation get session={session_id} workspace={workspace}")
    await send_json(
        websocket,
        {
            "type": "conversation.response",
            "session_id": session_id,
            "messages": store.load_messages(session_id),
        },
    )


async def send_project_list(websocket: ServerConnection) -> None:
    log(f"project list workspace={WORKSPACE}")
    await send_json(
        websocket,
        {
            "type": "project.list.response",
            "projects": build_project_list(WORKSPACE),
        },
    )


async def send_project(websocket: ServerConnection, message: dict[str, Any]) -> None:
    project_id = str(message.get("project_id") or "current")
    if project_id != "current":
        await send_json(websocket, {"type": "error", "error": f"unknown project_id: {project_id}"})
        return

    await send_json(
        websocket,
        {
            "type": "project.response",
            "project": build_project_detail(WORKSPACE),
        },
    )


async def send_trace(websocket: ServerConnection, message: dict[str, Any]) -> None:
    session_id = str(message.get("session_id") or "")
    if not session_id:
        await send_json(websocket, {"type": "error", "error": "session_id is required"})
        return

    workspace = workspace_for_session(session_id)
    _memory_root, trace_root, _skills_root = state.roots_for_session(session_id)
    log(f"trace get session={session_id} trace_root={trace_root}")

    await send_json(
        websocket,
        {
            "type": "trace.response",
            "session_id": session_id,
            "events": read_trace_events(trace_root, session_id),
        },
    )


async def switch_project(websocket: ServerConnection, message: dict[str, Any]) -> None:
    session_id = str(message.get("session_id") or make_session_id())
    path = str(message.get("path") or "").strip()
    if not path:
        await send_json(websocket, {"type": "error", "session_id": session_id, "error": "path is required"})
        return

    try:
        workspace = state.switch_session_workspace(session_id, path)
    except ValueError as exc:
        await send_json(websocket, {"type": "error", "session_id": session_id, "error": str(exc)})
        return

    log(f"project switch session={session_id} workspace={workspace}")
    await send_json(
        websocket,
        {
            "type": "project.switched",
            "session_id": session_id,
            "name": workspace.name,
            "path": str(workspace),
        },
    )


async def handle_message(websocket: ServerConnection, message: dict[str, Any]) -> None:
    message_type = message.get("type")
    log(f"message type={message_type}")

    if message_type == "chat":
        await run_chat(websocket, message)
    elif message_type == "project.switch":
        await switch_project(websocket, message)
    elif message_type == "conversation.list":
        await send_conversation_list(websocket)
    elif message_type == "conversation.get":
        await send_conversation(websocket, message)
    elif message_type == "project.list":
        await send_project_list(websocket)
    elif message_type == "project.get":
        await send_project(websocket, message)
    elif message_type == "memory.get":
        await send_memory(websocket, message)
    elif message_type == "trace.get":
        await send_trace(websocket, message)
    elif message_type == "ping":
        await send_json(websocket, {"type": "pong"})
    else:
        await send_json(
            websocket,
            {
                "type": "error",
                "error": f"unknown message type: {message_type}",
            },
        )


async def websocket_handler(websocket: ServerConnection) -> None:
    label = connection_label(websocket)
    log(f"connection open peer={label}")
    await send_json(websocket, {"type": "gateway.ready"})

    try:
        async for raw_message in websocket:
            try:
                message = parse_message(raw_message)
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
                log(f"message parse error peer={label}: {exc}")
                await send_json(websocket, {"type": "error", "error": str(exc)})
                continue

            await handle_message(websocket, message)
    except ConnectionClosed:
        log(f"connection closed peer={label}")
        return
    finally:
        log(f"connection done peer={label}")


async def serve_gateway(host: str = "127.0.0.1", port: int = 8765) -> None:
    async with serve(websocket_handler, host, port):
        log(f"listening on ws://{host}:{port}")
        await asyncio.Future()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the LumaK websocket gateway.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--workspace",
        default=None,
        help="Project directory to use as the default workspace. Defaults to LUMAK_WORKSPACE or the current directory.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    configure_workspace(args.workspace)
    asyncio.run(serve_gateway(host=args.host, port=args.port))


if __name__ == "__main__":
    main()
