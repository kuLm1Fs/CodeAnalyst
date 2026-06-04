from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol

from agent.CLI.app import response_to_text
from agent.memory.store import MemoryStore
from agent.runtime.agent.agent import Agent, AgentConfig
from agent.runtime.hooks import HookContext
from agent.trace.trace import make_session_id
from gateway.events import EventBroker, LiveEventHook
from gateway.llm import build_request_llm_client
from gateway.state import GatewayState


class Sender(Protocol):
    async def send(self, raw_message: str) -> None:
        ...


SendJson = Callable[[Sender, dict[str, Any]], Awaitable[None]]
Logger = Callable[[str], None]
AgentFactory = Callable[[AgentConfig], Agent]
LlmClientBuilder = Callable[[dict[str, Any]], object | None]


class SessionEndCaptureHook:
    def __init__(self) -> None:
        self.final_output: str = ""
        self.stop_reason: str = ""

    def __call__(self, context: HookContext) -> None:
        if context.event != "session.end":
            return
        final_output = context.payload.get("final_output", "")
        if isinstance(final_output, str):
            self.final_output = final_output.strip()
        else:
            self.final_output = str(final_output).strip()
        self.stop_reason = str(context.payload.get("stop_reason", "")).strip()


async def forward_session_events(
    websocket: Sender,
    session_id: str,
    event_queue: asyncio.Queue[dict[str, Any]],
    *,
    send_json: SendJson,
) -> None:
    try:
        while True:
            event = await event_queue.get()
            await send_json(websocket, event)
    except asyncio.CancelledError:
        raise


def answer_from_agent_response(response: object, session_end: SessionEndCaptureHook) -> str:
    if isinstance(response, list):
        return session_end.final_output or "Agent 运行异常，请检查模型配置或稍后重试。"

    answer = response_to_text(response)
    if answer:
        return answer

    blocks = getattr(response, "content", [])
    tool_uses = [block for block in blocks if getattr(block, "type", None) == "tool_use"]
    stop_reason = getattr(response, "stop_reason", "")
    if tool_uses:
        tool_names = ", ".join(getattr(block, "name", "?") for block in tool_uses)
        if stop_reason == "max_steps":
            return f"Agent 达到最大步数，以下工具调用未完成：{tool_names}"
        if stop_reason == "max_tokens":
            return f"响应被截断（超出 max_tokens），以下工具调用未完成：{tool_names}"
        return f"已调用工具：{tool_names}"
    if stop_reason == "max_tokens":
        return "响应被截断（超出 max_tokens），请重试或增加 max_tokens。"
    if stop_reason == "max_steps":
        return "Agent 达到最大步数，任务未完成。请简化问题或分多步提问。"
    return "Agent 已完成，但没有返回文本。"


async def run_chat(
    websocket: Sender,
    message: dict[str, Any],
    *,
    state: GatewayState,
    broker: EventBroker,
    send_json: SendJson,
    log: Logger,
    agent_factory: AgentFactory = Agent,
    llm_client_builder: LlmClientBuilder = build_request_llm_client,
) -> None:
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
    workspace = state.workspace_for_session(session_id)
    memory_root, _trace_root, skills_root = state.roots_for_session(session_id)
    max_tokens = int(message.get("max_tokens") or 1024)
    max_steps = int(message.get("max_steps") or 12)
    event_queue = broker.subscribe(session_id)
    forwarder = asyncio.create_task(
        forward_session_events(websocket, session_id, event_queue, send_json=send_json)
    )
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
        memory_store = MemoryStore(Path(memory_root))
        session_end = SessionEndCaptureHook()
        agent = agent_factory(
            AgentConfig(
                workspace=workspace,
                session_id=session_id,
                max_tokens=max_tokens,
                max_steps=max_steps,
                llm_client=llm_client_builder(message),
                memory_store=memory_store,
                skills_root=skills_root,
                trace_enabled=True,
                hooks=[session_end, LiveEventHook(broker)],
            )
        )

        response = await agent.async_run(
            [{"role": "user", "content": prompt}],
        )
        answer = answer_from_agent_response(response, session_end)

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
