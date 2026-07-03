"""Tuige shortline trading rules — executable layer for recommend/analyze pipelines."""

from tradingagents.tuige.context import TuigeContext, build_tuige_context, tuige_enabled, tuige_strict
from tradingagents.tuige.position_grade import derive_position_grade, format_tuige_summary
from tradingagents.tuige.setup_classifier import SetupClassification, classify_setup

__all__ = [
    "TuigeContext",
    "SetupClassification",
    "build_tuige_context",
    "classify_setup",
    "derive_position_grade",
    "format_tuige_summary",
    "tuige_enabled",
    "tuige_strict",
]
