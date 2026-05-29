import asyncio
from pathlib import Path
from typing import Any
from agent.tools.registry import TOOLS, execute_tool
from agent.trace.trace import make_session_id, AgentTrace, TraceHook
from agent.runtime.hooks import Hook, HookManager
from agent.memory.store import MemoryStore
from agent.runtime.session import prepare_session_messages
from agent.runtime.rollback import SessionRollback, create_rollback_hook
from agent.skills import SkillSelector, SkillStore, render_skill_system_prompt
from agent.skills.selector import SkillSelection
import json
import time


ROOT_DIR = Path(__file__).resolve().parents[1]


def get_default_client():
    from agent.LLM.client import get_default_client as create_default_client

    return create_default_client()

def response_to_text(response) -> str:
    texts = [block.text for block in response.content if getattr(block, "type", None) == "text"]
    return "\n".join(texts).strip()

def make_json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, dict):
        return {
            str(key): make_json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [make_json_safe(item) for item in value]

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return make_json_safe(model_dump(mode="json", exclude_none=True))

    block_type = getattr(value, "type", None)
    if block_type:
        serialized = {"type": block_type}
        for key in ("text", "id", "name", "input", "thinking", "signature", "content"):
            if hasattr(value, key):
                serialized[key] = make_json_safe(getattr(value, key))
        return serialized

    return str(value)


def serialize_content_blocks(content: list[Any]) -> list[Any]:
    return [make_json_safe(block) for block in content]


def emit_hook(
        hook_manager: HookManager,
        event: str,
        payload: dict,
        *,
        session_id: str,
        workspace: Path,
) -> None:
    hook_manager.emit(
        event,
        payload,
        session_id=session_id,
        workspace=str(workspace),
    )

BASE_PROMPT_PATH = ROOT_DIR / "prompts" / "system.md"

ROLE_PROMPT_FILES = {
    "main": "system.md",
    "explorer": "subagent-explorer.md",
    "editor": "subagent-editor.md",
    "reviewer": "subagent-reviewer.md",
}


def _load_base_prompt(role: str = "main", prompt_override: str | None = None) -> str:
    if prompt_override:
        return prompt_override

    prompt_file = ROLE_PROMPT_FILES.get(role, "system.md")
    prompt_path = ROOT_DIR / "prompts" / prompt_file

    try:
        return prompt_path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _truncate_messages(
    messages: list,
    max_context_messages: int = 10,
) -> list:
    if len(messages) <= max_context_messages:
        return messages
    first = messages[:1]
    last = messages[-(max_context_messages - 1):]

    known_ids: set[str] = set()
    for m in first + last:
        if m.get("role") == "assistant":
            content = m.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        bid = block.get("id")
                        if bid:
                            known_ids.add(bid)

    cleaned: list = []
    for m in last:
        if m.get("role") == "user":
            content = m.get("content", [])
            if isinstance(content, list):
                filtered = [
                    b for b in content
                    if not (isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") not in known_ids)
                ]
                if filtered:
                    cleaned.append({"role": "user", "content": filtered})
            else:
                cleaned.append(m)
        else:
            cleaned.append(m)

    return first + cleaned


def select_skills_for_messages(
        messages: list,
        skills_root: Path | str | None,
) -> tuple[SkillSelection, str]:
    selection = SkillSelection(
        skills=[],
        mode="None",
        explicit_names=[],
        missing_explicit_names=[],
        cleaned_text="",
    )

    if not skills_root:
        return selection, ""

    user_text = "\n".join(
        str(message.get("content", ""))
        for message in messages
        if isinstance(message, dict) and message.get("role") == "user"
    )

    skills = SkillStore(skills_root).load_all()
    selection = SkillSelector(skills).select(user_text)
    system_prompt = render_skill_system_prompt(selection.skills)

    return selection, system_prompt


def emit_skills_selected(
        hook_manager: HookManager,
        selection: SkillSelection,
        *,
        session_id: str,
        workspace: str,
        skills_root: Path | str | None,
) -> None:
    emit_hook(
        hook_manager,
        "skills.selected",
        {
            "mode": selection.mode,
            "skill_names": [skill.name for skill in selection.skills],
            "explicit_names": selection.explicit_names,
            "missing_explicit_names": selection.missing_explicit_names,
            "skills_root": str(skills_root) if skills_root else None,
        },
        session_id=session_id,
        workspace=workspace,
    )


def _prepare_loop(
    messages: list,
    *,
    workspace: Path,
    session_id: str,
    llm_client: object | None,
    hooks: list[Hook] | None,
    memory_store: MemoryStore | None,
    skills_root: Path | str | None,
    trace_enabled: bool,
    trace_payload_limit: int,
    role: str = "main",
    prompt_override: str | None = None,
) -> tuple[object, str, HookManager, SessionRollback, list, str]:
    llm_client = llm_client or get_default_client()
    session_id = session_id or make_session_id()
    active_hooks = list(hooks or [])
    if trace_enabled:
        trace = AgentTrace(workspace=workspace, session_id=session_id)
        active_hooks.insert(0, TraceHook(trace, payload_limit=trace_payload_limit))
    rollback = SessionRollback(workspace)
    active_hooks.append(create_rollback_hook(rollback))
    hook_manager = HookManager(active_hooks)
    incoming_messages = list(messages)

    selection, skill_prompt = select_skills_for_messages(
        messages=incoming_messages,
        skills_root=skills_root
    )
    base_prompt = _load_base_prompt(role=role, prompt_override=prompt_override)
    if base_prompt and skill_prompt:
        system_prompt = f"{base_prompt}\n\n{skill_prompt}"
    else:
        system_prompt = base_prompt or skill_prompt

    if memory_store:
        messages = prepare_session_messages(
            messages, session_id=session_id, memory_store=memory_store,
        )

    emit_hook(
        hook_manager,
        "session.start",
        {"session_id": session_id},
        session_id=session_id,
        workspace=workspace,
    )

    emit_skills_selected(
        hook_manager,
        selection,
        session_id=session_id,
        workspace=workspace,
        skills_root=skills_root,
    )

    for message in messages:
        if isinstance(message, dict):
            emit_hook(
                hook_manager,
                "message",
                {
                    "role": message.get("role", "unknow"),
                    "content": str(message.get("content", "")),
                },
                session_id=session_id,
                workspace=workspace,
            )

    return llm_client, session_id, hook_manager, rollback, messages, system_prompt


async def async_agent_loop(
        messages: list,
        max_tokens: int = 4096,
        workspace: Path = ROOT_DIR,
        max_steps: int = 12,
        session_id: str | None = None,
        llm_client=None,
        hooks: list[Hook] | None = None,
        memory_store: MemoryStore | None = None,
        skills_root: Path | str | None = None,
        trace_enabled: bool = False,
        trace_payload_limit: int = 2000,
        tool_filter: set[str] | None = None,
        role: str = "main",
        prompt_override: str | None = None,
) -> Any:
    llm_client, session_id, hook_manager, rollback, messages, system_prompt = _prepare_loop(
        messages,
        workspace=workspace,
        session_id=session_id,
        llm_client=llm_client,
        hooks=hooks,
        memory_store=memory_store,
        skills_root=skills_root,
        trace_enabled=trace_enabled,
        trace_payload_limit=trace_payload_limit,
        role=role,
        prompt_override=prompt_override,
    )

    available_tools = TOOLS
    if tool_filter is not None:
        available_tools = [t for t in TOOLS if t["name"] in tool_filter]

    last_response = None
    tool_cache: dict[str, str] = {}
    consecutive_dedup = 0
    consecutive_tool_only = 0
    MAX_CONSECUTIVE_TOOL_ONLY = 4
    force_text_response = False
    i = 0
    while i < max_steps:
        i += 1
        emit_hook(
            hook_manager,
            "loop.iteration.start",
            {"iteration": i + 1},
            session_id=session_id,
            workspace=workspace,
        )

        request_start = time.perf_counter()
        emit_hook(
            hook_manager,
            "model.request",
            {
                "model": llm_client.default_model,
                "max_tokens": max_tokens,
                "message_count": len(messages),
                "tool_names": [tool["name"] for tool in available_tools],
            },
            session_id=session_id,
            workspace=workspace,
        )

        request_kwargs = {
            "model": llm_client.default_model,
            "max_tokens": max_tokens,
            "messages": _truncate_messages(messages),
        }
        if not force_text_response:
            request_kwargs["tools"] = available_tools
        else:
            force_text_response = False
        if system_prompt:
            request_kwargs["messages"] = [{"role": "system", "content": system_prompt}] + request_kwargs["messages"]

        response = None
        for ctx_limit in [10, 6, 4]:
            if ctx_limit != 10:
                request_kwargs["messages"] = _truncate_messages(messages, ctx_limit)
            try:
                response = llm_client.messages.create(**request_kwargs)
                break
            except Exception as exc:
                err_str = str(exc).lower()
                if any(word in err_str for word in ("context length", "too many tokens", "maximum context", "context window", "tool result")):
                    print(f"[retry] LLM call failed, retrying with ctx_limit={ctx_limit}: {exc}")
                else:
                    print(f"[error] LLM call failed: {exc}")
                    emit_hook(
                        hook_manager,
                        "session.end",
                        {
                            "final_output": f"模型调用失败：{exc}",
                            "stop_reason": "error",
                        },
                        session_id=session_id,
                        workspace=workspace,
                    )
                    return last_response or messages
        if response is None:
            emit_hook(
                hook_manager,
                "session.end",
                {
                    "final_output": "模型多次调用失败，请检查模型配置或稍后重试。",
                    "stop_reason": "error",
                },
                session_id=session_id,
                workspace=workspace,
            )
            return last_response or messages
        last_response = response

        request_elapsed = (time.perf_counter() - request_start) * 1000
        emit_hook(
            hook_manager,
            "model.response",
            {
                "stop_reason": response.stop_reason,
                "content": response_to_text(response),
            },
            session_id=session_id,
            workspace=workspace,
        )
        emit_hook(
            hook_manager,
            "loop.model.duration",
            {
                "duration_ms": request_elapsed,
                "stop_reason": response.stop_reason,
            },
            session_id=session_id,
            workspace=workspace,
        )

        full_content = serialize_content_blocks(response.content)
        content_no_thinking = [b for b in full_content if b.get("type") != "thinking"]
        msg: dict[str, Any] = {"role": "assistant", "content": content_no_thinking}
        reasoning = getattr(response, "reasoning_content", None)
        if reasoning:
            msg["reasoning_content"] = reasoning
        messages.append(msg)
        if response.stop_reason == "tool_use":
            rt = response_to_text(response)
            if not rt:
                consecutive_tool_only += 1
            else:
                consecutive_tool_only = 0

        if memory_store and response.stop_reason != "tool_use":
            text = response_to_text(response)
            if text.strip():
                memory_store.append_message(session_id, {"role": "assistant", "content": text})

        if response.stop_reason != "tool_use":
            final_text = response_to_text(response)
            emit_hook(
                hook_manager,
                "session.end",
                {
                    "final_output": final_text,
                    "stop_reason": response.stop_reason,
                },
                session_id=session_id,
                workspace=workspace,
            )
            return response

        delegate_blocks = []
        other_blocks = []
        for block in response.content:
            if block.type == "tool_use":
                if block.name == "delegate":
                    delegate_blocks.append(block)
                else:
                    other_blocks.append(block)

        results = []
        tool_use_count = len(delegate_blocks) + len(other_blocks)
        dedup_count = 0

        for block in other_blocks:
            emit_hook(
                hook_manager,
                "tool.before",
                {
                    "tool_name": block.name,
                    "tool_input": block.input,
                    "tool_use_id": block.id,
                },
                session_id=session_id,
                workspace=workspace,
            )
            cache_key = f"{block.name}:{json.dumps(block.input, sort_keys=True)}"
            cached = tool_cache.get(cache_key)
            if cached is not None:
                dedup_count += 1
                tool_start = time.perf_counter()
                output = cached
                success = True
                tool_elapsed = (time.perf_counter() - tool_start) * 1000
                emit_hook(
                    hook_manager,
                    "tool.after",
                    {
                        "tool_name": block.name,
                        "tool_input": block.input,
                        "tool_use_id": block.id,
                        "output": output,
                        "success": success,
                        "duration_ms": tool_elapsed,
                        "dedup": True,
                    },
                    session_id=session_id,
                    workspace=workspace,
                )
                print(f"[dedup] {block.name} → cached result ({len(output)} chars)")
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": output[:10000]})
                continue
            tool_start = time.perf_counter()
            success = True
            output = ""
            try:
                output = await asyncio.to_thread(
                    execute_tool, block.name, block.input, workspace=workspace
                )
            except Exception as exc:
                output = str(exc)
                success = False
            finally:
                tool_elapsed = (time.perf_counter() - tool_start) * 1000
            if success:
                tool_cache[cache_key] = output
            emit_hook(
                hook_manager,
                "tool.after",
                {
                    "tool_name": block.name,
                    "tool_input": block.input,
                    "tool_use_id": block.id,
                    "output": output,
                    "success": success,
                    "duration_ms": tool_elapsed,
                },
                session_id=session_id,
                workspace=workspace,
            )
            print(output[:200])
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": output[:10000]})

        if delegate_blocks:
            async def run_delegate_block(block):
                emit_hook(
                    hook_manager,
                    "tool.before",
                    {
                        "tool_name": "delegate",
                        "tool_input": block.input,
                        "tool_use_id": block.id,
                    },
                    session_id=session_id,
                    workspace=workspace,
                )
                tool_start = time.perf_counter()
                success = True
                output = ""
                try:
                    output = await asyncio.to_thread(
                        execute_tool, "delegate", block.input, workspace=workspace
                    )
                except Exception as exc:
                    output = str(exc)
                    success = False
                finally:
                    tool_elapsed = (time.perf_counter() - tool_start) * 1000
                emit_hook(
                    hook_manager,
                    "tool.after",
                    {
                        "tool_name": "delegate",
                        "tool_input": block.input,
                        "tool_use_id": block.id,
                        "output": output,
                        "success": success,
                        "duration_ms": tool_elapsed,
                    },
                    session_id=session_id,
                    workspace=workspace,
                )
                print(f"[delegate] completed in {tool_elapsed:.0f}ms success={success}")
                return {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output[:10000],
                }

            delegate_results = await asyncio.gather(*[
                run_delegate_block(block) for block in delegate_blocks
            ])
            results.extend(delegate_results)

        if tool_use_count > 0 and tool_use_count == dedup_count:
            consecutive_dedup += 1
            print(f"[dedup] all {tool_use_count} tool(s) were cached (x{consecutive_dedup}), not counting iteration")
            if consecutive_dedup >= 5:
                print("[dedup] too many consecutive dedup rounds, stopping")
                emit_hook(
                    hook_manager,
                    "session.end",
                    {
                        "final_output": "模型陷入重复调用，请重试或使用其他模型。",
                        "stop_reason": "error",
                    },
                    session_id=session_id,
                    workspace=workspace,
                )
                return last_response or messages
            i -= 1
        else:
            consecutive_dedup = 0

        messages.append({"role": "user", "content": results})

        if consecutive_tool_only >= MAX_CONSECUTIVE_TOOL_ONLY:
            print(f"[force] {consecutive_tool_only} consecutive tool-only rounds, forcing text response")
            messages.append({
                "role": "user",
                "content": (
                    "你已经进行了多次工具调用，获得了足够的上下文信息。"
                    "请直接输出最终回答，不要再调用任何工具。"
                ),
            })
            consecutive_tool_only = 0
            force_text_response = True

    emit_hook(
        hook_manager,
        "session.end",
        {
            "final_output": "max steps reached",
            "stop_reason": "max_steps",
        },
        session_id=session_id,
        workspace=workspace,
    )
    return last_response or messages


def agent_loop(
        messages: list,
        max_tokens: int = 4096,
        workspace: Path = ROOT_DIR,
        max_steps: int = 12,
        session_id: str | None = None,
        llm_client=None,
        hooks: list[Hook] | None = None,
        memory_store: MemoryStore | None = None,
        skills_root: Path | str | None = None,
        trace_enabled: bool = False,
        trace_payload_limit: int = 2000,
        tool_filter: set[str] | None = None,
        role: str = "main",
        prompt_override: str | None = None,
) -> Any:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    coro = async_agent_loop(
        messages=messages,
        max_tokens=max_tokens,
        workspace=workspace,
        max_steps=max_steps,
        session_id=session_id,
        llm_client=llm_client,
        hooks=hooks,
        memory_store=memory_store,
        skills_root=skills_root,
        trace_enabled=trace_enabled,
        trace_payload_limit=trace_payload_limit,
        tool_filter=tool_filter,
        role=role,
        prompt_override=prompt_override,
    )

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()
    else:
        return asyncio.run(coro)
