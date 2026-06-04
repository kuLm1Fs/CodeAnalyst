from __future__ import annotations

from typing import Any


def response_to_text(response: Any) -> str:
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


def truncate_messages(
    messages: list,
    max_context_messages: int = 10,
) -> list:
    if len(messages) <= max_context_messages:
        return messages
    first = messages[:1]
    last = messages[-(max_context_messages - 1):]

    known_ids: set[str] = set()
    for message in first + last:
        if message.get("role") == "assistant":
            content = message.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        block_id = block.get("id")
                        if block_id:
                            known_ids.add(block_id)

    cleaned: list = []
    for message in last:
        if message.get("role") == "user":
            content = message.get("content", [])
            if isinstance(content, list):
                filtered = [
                    block for block in content
                    if not (
                        isinstance(block, dict)
                        and block.get("type") == "tool_result"
                        and block.get("tool_use_id") not in known_ids
                    )
                ]
                if filtered:
                    cleaned.append({"role": "user", "content": filtered})
            else:
                cleaned.append(message)
        else:
            cleaned.append(message)

    return first + cleaned


def step_budget_warning(current_step: int, max_steps: int) -> str:
    remaining = max_steps - current_step
    if max_steps <= 0 or remaining > 2:
        return ""
    return (
        f"\n\nYou are near the tool budget: step {current_step} of {max_steps}, "
        f"with {remaining} step(s) remaining. Do not call more tools unless essential; "
        "produce the final answer now if possible."
    )
