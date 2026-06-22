# TradingAgents/graph/reflection.py

from typing import Any

from tradingagents.agents.schemas import (
    ReflectionOutcome,
    format_reflection_storage,
)
from tradingagents.agents.utils.structured import bind_structured

class Reflector:
    """Handles reflection on trading decisions."""

    def __init__(self, quick_thinking_llm: Any):
        """Initialize the reflector with an LLM."""
        self.quick_thinking_llm = quick_thinking_llm
        self.structured_llm = bind_structured(
            quick_thinking_llm, ReflectionOutcome, "Reflector"
        )
        self.log_reflection_prompt = self._get_log_reflection_prompt()

    def _get_log_reflection_prompt(self) -> str:
        return (
            "You are a trading analyst reviewing your own past decision now that "
            "the outcome is known.\n"
            "Return structured output with:\n"
            "- failure_mode: none if direction was broadly correct; otherwise "
            "hallucination / timing / macro / valuation / sentiment / other\n"
            "- reflection: 2-4 sentences plain prose (no bullets)\n\n"
            "Cover: directional accuracy vs alpha, which thesis part failed, "
            "one concrete lesson for the next similar case."
        )

    def reflect_on_final_decision(
        self,
        final_decision: str,
        raw_return: float,
        alpha_return: float,
        benchmark_name: str = "SPY",
    ) -> str:
        """Return stored reflection text including FAILURE_MODE prefix."""
        human = (
            f"Raw return: {raw_return:+.1%}\n"
            f"Alpha vs {benchmark_name}: {alpha_return:+.1%}\n\n"
            f"Final Decision:\n{final_decision}"
        )
        if self.structured_llm is not None:
            try:
                outcome = self.structured_llm.invoke(
                    [
                        ("system", self.log_reflection_prompt),
                        ("human", human),
                    ]
                )
                if isinstance(outcome, ReflectionOutcome):
                    return format_reflection_storage(outcome)
            except Exception:
                pass

        messages = [
            ("system", self.log_reflection_prompt),
            ("human", human),
        ]
        text = self.quick_thinking_llm.invoke(messages).content.strip()
        return f"FAILURE_MODE: other\n{text}"
