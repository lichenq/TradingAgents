"""Slice past_context for different agent roles."""

from __future__ import annotations

import re

_FAILURE_MODE_RE = re.compile(r"^FAILURE_MODE:\s*(\w+)\s*\n?", re.IGNORECASE | re.MULTILINE)


def _strip_failure_mode(reflection: str) -> tuple[str, str]:
    text = (reflection or "").strip()
    match = _FAILURE_MODE_RE.match(text)
    if not match:
        return "", text
    mode = match.group(1).lower()
    rest = text[match.end() :].strip()
    return mode, rest


def format_past_context_for_role(past_context: str, role: str) -> str:
    """Return a role-appropriate subset of past_context."""
    ctx = (past_context or "").strip()
    if not ctx:
        return ""

    role = (role or "").strip().lower()
    if role in ("portfolio_manager", "research_manager"):
        return ctx

    if role in ("bull_researcher", "bear_researcher", "trader"):
        lines = ctx.splitlines()
        same_lines: list[str] = []
        cross_lines: list[str] = []
        section = "other"
        for line in lines:
            if line.startswith("Past analyses of"):
                section = "same"
                same_lines.append(line)
                continue
            if line.startswith("Recent cross-ticker lessons"):
                section = "cross"
                cross_lines.append(line)
                continue
            if line.startswith("[") and section == "same":
                same_lines.append(line)
            elif line.startswith("REFLECTION:") and section == "same":
                same_lines.append(line)
            elif line.startswith("- ") and section == "cross":
                cross_lines.append(line)
            elif line.startswith("Audit aggregate") or line.startswith("Apply these lessons"):
                cross_lines.append(line)

        parts: list[str] = []
        if same_lines:
            parts.append("\n".join(same_lines[:6]))
        if cross_lines:
            trimmed = []
            for line in cross_lines:
                if line.startswith("- ") and "REFLECTION:" in ctx:
                    m = re.search(r"REFLECTION:\n(.+)", ctx, re.DOTALL)
                    if m:
                        mode, body = _strip_failure_mode(m.group(1))
                        snippet = body[:180] + ("..." if len(body) > 180 else "")
                        prefix = f"[{mode}] " if mode else ""
                        trimmed.append(f"- {prefix}{snippet}")
                    else:
                        trimmed.append(line[:220])
                else:
                    trimmed.append(line)
            parts.append("Cross-ticker lessons:\n" + "\n".join(trimmed[:5]))
        return "\n\n".join(parts).strip()

    return ctx


def past_context_prompt_block(past_context: str, role: str) -> str:
    block = format_past_context_for_role(past_context, role)
    if not block:
        return ""
    return f"\n\n**Prior decisions & lessons (apply when relevant):**\n{block}\n"
