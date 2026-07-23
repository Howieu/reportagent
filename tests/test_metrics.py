import pandas as pd

from src.metrics import display_metrics, display_number


def test_display_number_nan_is_placeholder():
    assert display_number(float("nan"), "%") == "≤0"


def test_display_number_1pct_scales_small_decimal_ratio():
    # '1%' 格式下，<2 的小数口径按 ×100 处理（如 0.94 -> 94.0%）
    assert display_number(0.94, "1%") == "94.0%"


def test_display_number_1pct_boundary_at_2_not_scaled():
    # 边界值 2.0 及以上视为已是百分比口径，不再 ×100
    assert display_number(1.9, "1%") == "190.0%"
    assert display_number(2.0, "1%") == "2.0%"
    assert display_number(2.1, "1%") == "2.1%"


def test_display_number_pct_does_not_rescale_small_diffs():
    # 修复过的 bug：'%'/'%+' 口径下已是 100 制，不应把 -1.2 误放大成 -120
    assert display_number(-1.2, "%") == "-1"
    assert display_number(-1.2, "%+") == "-1"


def test_display_number_k_and_default_formats():
    assert display_number(12345, "K") == "12K"
    assert display_number(3.14159, None) == "3.1"
    assert display_number(-0.02, None) == "0.0"


def test_display_metrics_joins_with_comparison():
    metrics = {"sales_ind_ly": [["4WKs"], "%"]}
    perf = pd.Series({"sales_ind_ly": 106})
    rolling_perf = pd.Series({"sales_ind_ly": 100})
    text = display_metrics(metrics, perf, rolling_perf,
                           name_mapping={"sales_ind_ly": "Sales ind.LY"})
    assert text == "Sales ind.LY: 106 (+6 vs. 4WKs)"


def test_display_metrics_skips_nan_metric():
    metrics = {"sales_ind_ly": [None, "%"]}
    perf = pd.Series({"sales_ind_ly": float("nan")})
    assert display_metrics(metrics, perf) == ""
