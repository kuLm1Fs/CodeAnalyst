from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable


@dataclass
class HookContext:
    event: str
    payload: dict[str, Any]
    session_id: str
    workspace: str


Hook = Callable[[HookContext], None] | Callable[[HookContext], Awaitable[None]]


class HookManager:
    def __init__(self, hooks: list[Hook] | None = None) -> None:
        self._hooks: list[Hook] = hooks or []

    def register(self, hook: Hook) -> None:
        self._hooks.append(hook)

    def registry(self, hook: Hook) -> None:
        self.register(hook)

    def emit(
        self,
        event: str,
        payload: dict[str, Any],
        *,
        session_id: str,
        workspace: str,
    ) -> None:
        context = HookContext(
            event=event,
            payload=payload,
            session_id=session_id,
            workspace=workspace
        )
        for hook in self._hooks:
            result = hook(context)
            if asyncio.iscoroutine(result):
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(result)
                except RuntimeError:
                    asyncio.run(result)

    async def emit_async(
        self,
        event: str,
        payload: dict[str, Any],
        *,
        session_id: str,
        workspace: str,
    ) -> None:
        context = HookContext(
            event=event,
            payload=payload,
            session_id=session_id,
            workspace=workspace
        )
        for hook in self._hooks:
            result = hook(context)
            if asyncio.iscoroutine(result):
                await result


@dataclass
class SubAgentEvent:
    task_id: str
    event_type: str
    payload: dict[str, Any]


class SubAgentEventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[SubAgentEvent]]] = {}

    def subscribe(self, task_id: str) -> asyncio.Queue[SubAgentEvent]:
        queue: asyncio.Queue[SubAgentEvent] = asyncio.Queue()
        self._subscribers.setdefault(task_id, []).append(queue)
        return queue

    def unsubscribe(self, task_id: str, queue: asyncio.Queue[SubAgentEvent]) -> None:
        queues = self._subscribers.get(task_id, [])
        if queue in queues:
            queues.remove(queue)
        if not queues:
            self._subscribers.pop(task_id, None)

    async def emit(self, event: SubAgentEvent) -> None:
        queues = self._subscribers.get(event.task_id, [])
        for queue in queues:
            await queue.put(event)

    def emit_sync(self, event: SubAgentEvent) -> None:
        queues = self._subscribers.get(event.task_id, [])
        for queue in queues:
            queue.put_nowait(event)
