from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import time
from typing import Any

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from agent.CLI.app import response_to_text
from agent.memory.store import MemoryStore
from agent.runtime.agent.agent import Agent, AgentConfig
from agent.trace.trace import make_session_id
from gateway.events import EventBroker, LiveEventHook
from gateway.llm import build_request_llm_client
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


async def forward_session_events(
    websocket: ServerConnection,
    session_id: str,
    event_queue: asyncio.Queue[dict[str, Any]],
) -> None:
    try:
        while True:
            event = await event_queue.get()
            await send_json(websocket, event)
    except asyncio.CancelledError:
        raise


async def run_chat(websocket: ServerConnection, message: dict[str, Any]) -> None:
    prompt = str(message.get("message", "")).strip()
    if not prompt:
        await send_json(
            websocket,
            {
                "type": "error",
                "error": "message is required",
            },
        )
        return

    session_id = str(message.get("session_id") or make_session_id())
    workspace = workspace_for_session(session_id)
    memory_root, _trace_root, skills_root = state.roots_for_session(session_id)
    max_tokens = int(message.get("max_tokens") or 1024)
    max_steps = int(message.get("max_steps") or 12)
    event_queue = broker.subscribe(session_id)
    forwarder = asyncio.create_task(forward_session_events(websocket, session_id, event_queue))
    started_at = time.monotonic()
    log(f"chat start session={session_id} workspace={workspace} chars={len(prompt)}")

    await send_json(
        websocket,
        {
            "type": "chat.started",
            "session_id": session_id,
        },
    )

    try:
        memory_store = MemoryStore(memory_root)
        agent = Agent(
            AgentConfig(
                workspace=workspace,
                session_id=session_id,
                max_tokens=max_tokens,
                max_steps=max_steps,
                llm_client=build_request_llm_client(message),
                memory_store=memory_store,
                skills_root=skills_root,
                trace_enabled=True,
                hooks=[LiveEventHook(broker)],
            )
        )

        response = await agent.async_run(
            [{"role": "user", "content": prompt}],
        )

        if isinstance(response, list):
            answer = "Agent 运行异常，请检查模型配置或稍后重试。"
        else:
            answer = response_to_text(response)
            if not answer:
                blocks = getattr(response, "content", [])
                tool_uses = [b for b in blocks if getattr(b, "type", None) == "tool_use"]
                stop_reason = getattr(response, "stop_reason", "")
                if tool_uses:
                    tool_names = ", ".join(getattr(b, "name", "?") for b in tool_uses)
                    if stop_reason == "max_steps":
                        answer = f"Agent 达到最大步数，以下工具调用未完成：{tool_names}"
                    elif stop_reason == "max_tokens":
                        answer = f"响应被截断（超出 max_tokens），以下工具调用未完成：{tool_names}"
                    else:
                        answer = f"已调用工具：{tool_names}"
                elif stop_reason == "max_tokens":
                    answer = "响应被截断（超出 max_tokens），请重试或增加 max_tokens。"
                elif stop_reason == "max_steps":
                    answer = "Agent 达到最大步数，任务未完成。请简化问题或分多步提问。"
                else:
                    answer = "Agent 已完成，但没有返回文本。"

        await send_json(
            websocket,
            {
                "type": "chat.response",
                "session_id": session_id,
                "answer": answer,
            },
        )
        elapsed = time.monotonic() - started_at
        log(f"chat complete session={session_id} elapsed={elapsed:.2f}s")
    except Exception as exc:
        log(f"chat error session={session_id}: {exc}")
        await send_json(
            websocket,
            {
                "type": "error",
                "session_id": session_id,
                "error": str(exc),
            },
        )
    finally:
        forwarder.cancel()
        broker.unsubscribe(session_id, event_queue)
        await asyncio.gather(forwarder, return_exceptions=True)


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
