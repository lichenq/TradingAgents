"""Per-analyst message threads for parallel LangGraph fan-out."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph.message import RemoveMessage


def _is_thread_reset(msgs: list) -> bool:
    return (
        len(msgs) == 1
        and isinstance(msgs[0], HumanMessage)
        and (msgs[0].content or "") == "Continue"
    )


def merge_analyst_threads(
    existing: Optional[Dict[str, list]],
    new: Optional[Dict[str, list]],
) -> Dict[str, list]:
    merged = dict(existing or {})
    for key, msgs in (new or {}).items():
        batch = list(msgs)
        if _is_thread_reset(batch):
            merged[key] = batch
        else:
            merged[key] = list(merged.get(key) or []) + batch
    return merged


def seed_messages(state: Dict[str, Any]) -> List[Any]:
    messages = state.get("messages") or []
    if not messages:
        return [HumanMessage(content="Continue")]
    return list(messages[:1])


def _tool_call_id(tool_call: Any) -> Optional[str]:
    if isinstance(tool_call, dict):
        return tool_call.get("id")
    return getattr(tool_call, "id", None)


def _tool_response_ids_after(messages: List[Any], start: int) -> set[str]:
    ids: set[str] = set()
    for message in messages[start:]:
        if isinstance(message, ToolMessage):
            tid = getattr(message, "tool_call_id", None)
            if tid:
                ids.add(str(tid))
    return ids


def sanitize_messages_for_llm(messages: List[Any]) -> List[Any]:
    """Drop assistant tool_calls (and trailing tail) missing ToolMessage replies.

    DeepSeek/OpenAI reject histories where an AIMessage has tool_calls but the
    following messages do not include a ToolMessage per tool_call_id.
    """
    msgs = list(messages)
    changed = True
    while changed and msgs:
        changed = False
        for i in range(len(msgs) - 1, -1, -1):
            tool_calls = getattr(msgs[i], "tool_calls", None) or []
            if not tool_calls:
                continue
            needed = {tid for tc in tool_calls if (tid := _tool_call_id(tc))}
            if needed.issubset(_tool_response_ids_after(msgs, i + 1)):
                continue
            msgs = msgs[:i]
            changed = True
            break
    return msgs


def get_analyst_thread(state: Dict[str, Any], thread_key: str, *, sanitize: bool = True) -> List[Any]:
    threads = state.get("analyst_threads")
    if isinstance(threads, dict) and thread_key in threads:
        thread = threads.get(thread_key)
        if thread:
            return sanitize_messages_for_llm(list(thread)) if sanitize else list(thread)
        return seed_messages(state)
    return sanitize_messages_for_llm(list(state.get("messages") or [])) if sanitize else list(state.get("messages") or [])


def analyst_invoke_messages(state: Dict[str, Any], thread_key: Optional[str]) -> List[Any]:
    if thread_key:
        return get_analyst_thread(state, thread_key)
    return sanitize_messages_for_llm(list(state.get("messages") or []))


def extract_last_ai_content(state: Dict[str, Any], thread_key: Optional[str]) -> str:
    """Best-effort report text from the analyst thread's last assistant message."""
    from langchain_core.messages import AIMessage

    if thread_key:
        threads = state.get("analyst_threads") or {}
        thread = list(threads.get(thread_key) or [])
    else:
        thread = list(state.get("messages") or [])

    for msg in reversed(thread):
        if not isinstance(msg, AIMessage):
            continue
        content = msg.content
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            parts: List[str] = []
            for part in content:
                if isinstance(part, dict):
                    text = part.get("text") or part.get("content") or ""
                else:
                    text = str(part)
                if str(text).strip():
                    parts.append(str(text).strip())
            joined = "\n".join(parts).strip()
            if joined:
                return joined
    return ""


def analyst_node_return(
    state: Dict[str, Any],
    *,
    thread_key: Optional[str],
    message: Any,
    report_key: str,
    report: str,
) -> Dict[str, Any]:
    if thread_key:
        out: Dict[str, Any] = {"analyst_threads": {thread_key: [message]}}
    else:
        out = {"messages": [message]}
    text = (report or "").strip()
    if text:
        out[report_key] = text
    return out


def create_analyst_clear_node(thread_key: Optional[str], report_key: str):
    """Clear analyst context and backfill report from the last assistant turn if missing."""

    clear_fn = create_analyst_msg_clear(thread_key)

    def node(state: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(clear_fn(state))
        if (state.get(report_key) or "").strip():
            return out
        fallback = extract_last_ai_content(state, thread_key)
        if fallback:
            out[report_key] = fallback
        return out

    return node


def create_thread_tool_node(tool_node: Any, thread_key: str):
    """Run ToolNode against an isolated analyst thread (parallel mode)."""

    def node(state: Dict[str, Any]) -> Dict[str, Any]:
        thread = get_analyst_thread(state, thread_key, sanitize=False)
        out = tool_node.invoke({**state, "messages": thread})
        # ToolNode returns incremental tool messages, not the full thread.
        tool_messages = list(out.get("messages") or [])
        if not tool_messages and thread:
            last = thread[-1]
            tool_calls = getattr(last, "tool_calls", None) or []
            if tool_calls:
                tool_messages = [
                    ToolMessage(
                        content="Tool execution returned no output.",
                        tool_call_id=_tool_call_id(tc) or "",
                    )
                    for tc in tool_calls
                    if _tool_call_id(tc)
                ]
        if not tool_messages:
            return {}
        return {"analyst_threads": {thread_key: tool_messages}}

    return node


def create_analyst_msg_clear(thread_key: Optional[str] = None):
    """Clear analyst context after a report is produced."""

    def delete_messages(state: Dict[str, Any]) -> Dict[str, Any]:
        if thread_key:
            return {"analyst_threads": {thread_key: [HumanMessage(content="Continue")]}}
        messages = state.get("messages") or []
        removal_operations = [RemoveMessage(id=m.id) for m in messages]
        return {
            "messages": removal_operations + [HumanMessage(content="Continue")],
        }

    return delete_messages


def last_message_in_thread(state: Dict[str, Any], thread_key: str) -> Any:
    threads = state.get("analyst_threads")
    if isinstance(threads, dict) and thread_key in threads:
        thread = threads.get(thread_key) or []
        if thread:
            return thread[-1]
        seeded = seed_messages(state)
        return seeded[-1] if seeded else HumanMessage(content="Continue")
    messages = state.get("messages") or []
    if messages:
        return messages[-1]
    return HumanMessage(content="Continue")


def tool_names_from_update(update: Optional[Dict[str, Any]]) -> List[str]:
    if not isinstance(update, dict):
        return []
    names: List[str] = []
    for message in update.get("messages") or []:
        names.extend(_tool_names_from_message(message))
    for thread in (update.get("analyst_threads") or {}).values():
        for message in thread:
            names.extend(_tool_names_from_message(message))
    return list(dict.fromkeys(names))


def _tool_names_from_message(message: Any) -> List[str]:
    out: List[str] = []
    tool_calls = getattr(message, "tool_calls", None) or []
    for tc in tool_calls:
        if isinstance(tc, dict):
            name = tc.get("name")
        else:
            name = getattr(tc, "name", None)
        if name:
            out.append(str(name))
    return out
