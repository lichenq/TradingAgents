from tradingagents.dataflows.report_paths import (
    build_report_bundle_name,
    sanitize_report_label,
)


def test_bundle_name_cn():
    name = build_report_bundle_name("600584.SS", "2026-05-23")
    assert name.endswith("-2026-05-23")
    assert "600584" in name
    # Bundle label is 名称-代码-日期: split from the left so the date keeps
    # its own dashes (rsplit would only ever yield the "05"/"23" tail fields).
    parts = name.split("-", 2)
    assert len(parts) == 3
    assert parts[1] == "600584"


def test_sanitize_strips_invalid():
    assert sanitize_report_label("长电/科技") == "长电_科技"
