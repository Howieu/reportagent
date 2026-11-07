from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from reportagent import forecast as F
from reportagent.narrative import check_text
from reportagent.tools import ToolError, Tools
from reportagent.warehouse import DataUnavailable


def panel(y, stores=None, categories=None):
    y = np.asarray(y, dtype=float)
    weeks = [date(2024, 1, 1) + timedelta(days=7 * i) for i in range(y.shape[1])]
    stores = np.array(stores or [f"S{i}" for i in range(len(y))])
    categories = np.array(categories or ["C"] * len(y))
    return F.Panel(weeks, stores, categories, y, y.copy(), np.maximum(y / 10, 1))


def seasonal(seed=1, series=8, weeks=70):
    """下一周明确取决于上周的序列：y 在高低两档之间交替，模型应该能学到。"""
    rng = np.random.default_rng(seed)
    t = np.arange(weeks)
    base = rng.uniform(200, 800, (series, 1))
    return base * (1 + 0.6 * (-1.0) ** t) * rng.normal(1, 0.02, (series, weeks))


def test_features_do_not_read_after_the_origin():
    y = seasonal()
    t, h = 60, 4
    before, _ = F.features(panel(y), t, h)
    changed = y.copy()
    changed[:, t + 1:] *= 50
    after, _ = F.features(panel(changed), t, h)
    assert np.array_equal(before, after)


def test_backtest_only_sees_earlier_targets():
    """改掉最后一周的实际值，只影响以它为目标的回测行，更早的预测必须一字不变。"""
    y = seasonal()
    changed = y.copy()
    changed[:, -1] *= 50
    a, b = F.train(panel(y)), F.train(panel(changed))
    rows_a, rows_b = a["backtest"][1], b["backtest"][1]
    for ra, rb in zip(rows_a, rows_b):
        assert ra["target"] == rb["target"]
        assert np.array_equal(ra["model"], rb["model"])
    assert not np.array_equal(rows_a[-1]["actual"], rows_b[-1]["actual"])
    assert not np.array_equal(a["final"][1]["contrib"], b["final"][1]["contrib"])


def test_model_beats_baseline_on_learnable_signal_and_shap_adds_up():
    trained = F.train(panel(seasonal()))
    mask = np.zeros(8, dtype=bool)
    mask[0] = True
    method = F._method(trained, mask, 1)
    assert method["beats"] and method["model_wape"] < method["baseline_wape"]
    s = F.shap_attribution(trained, mask)
    assert s["start"] + s["trend"] + sum(i["value"] for i in s["items"]) == pytest.approx(F._model_point(trained["final"][1], mask))
    assert s["items"][0]["factor"] in {"上周表现", "前 2 到 4 周表现"}  # 交替序列只依赖近几周
    covered = sorted(c for _, cols in F.GROUPS for c in cols)
    assert covered == list(range(F.FEATURE_COUNT))


def test_gate_follows_the_backtest_score_on_noise():
    y = np.random.default_rng(3).normal(500, 150, (8, 70)).clip(1)
    trained = F.train(panel(y))
    for i in range(8):
        mask = np.zeros(8, dtype=bool)
        mask[i] = True
        for h in F.HORIZONS:
            m = F._method(trained, mask, h)
            assert m["beats"] == (m["model_wape"] < m["baseline_wape"])


def test_falls_back_to_baselines_without_the_model_library(monkeypatch):
    monkeypatch.setattr(F, "_load_lightgbm", lambda: None)
    trained = F.train(panel(seasonal()))
    mask = np.ones(8, dtype=bool)
    assert not trained["model_available"] and F.shap_attribution(trained, mask) is None
    assert not F._method(trained, mask, 1)["beats"]


def test_panel_has_every_level_and_totals_match(demo_app, week):
    from reportagent.warehouse import parse_week

    F._cache.clear()
    p = F.load_panel(demo_app.wh, "sales", week)
    assert p.weeks[-1] == parse_week(week)
    whole = p.y[(p.stores == F.ALL) & (p.categories == F.ALL)]
    assert len(whole) == 1
    detail = p.y[(p.stores != F.ALL) & (p.categories != F.ALL)]
    assert whole[0] == pytest.approx(detail.sum(0))
    assert (p.stores == "S01").sum() >= 2


def test_same_data_gives_same_forecast_regardless_of_sql_row_order():
    weeks = [date(2024, 1, 1) + timedelta(days=7 * i) for i in range(2)]
    frame = pd.DataFrame({"store": ["B", "A"], "category": ["X", "X"], "sales__w0": [1.0, 2.0], "sales__w1": [3.0, 4.0],
                          "qty__w0": [1.0, 1.0], "qty__w1": [1.0, 1.0]})
    a, b = F.build_panel(frame, weeks, "sales"), F.build_panel(frame.iloc[::-1], weeks, "sales")
    assert np.array_equal(a.y, b.y) and list(a.stores) == list(b.stores)
    assert list(a.stores[:2]) == ["A", "B"]


def test_sparse_latest_week_moves_the_origin_back(tiny, monkeypatch):
    class Row:
        def __init__(self, values):
            self.iloc = [values]

    latest = date(2026, 11, 1)
    monkeypatch.setattr(tiny.wh, "latest_date", lambda source="sales": latest)
    monkeypatch.setattr(tiny.wh, "aggregate", lambda *a, **k: Row({"v__w0": 40.0, **{f"v__w{i}": 100.0 for i in range(1, 5)}}))
    week, note = F._origin(tiny.wh, None, "sales")
    assert week == "202643" and "40%" in note
    assert F._origin(tiny.wh, "202644", "sales") == ("202644", None)  # 指定周次时不改
    monkeypatch.setattr(tiny.wh, "aggregate", lambda *a, **k: Row({f"v__w{i}": 100.0 for i in range(5)}))
    assert F._origin(tiny.wh, None, "sales") == ("202644", None)


def test_short_history_and_unknown_scope_are_refused(demo_app, week):
    F._cache.clear()
    with pytest.raises(DataUnavailable, match="历史只有"):
        F._trim_leading_weeks(panel(np.ones((3, F.MIN_WEEKS - 1))))
    with pytest.raises(DataUnavailable, match="没有销售数据"):
        F.forecast(demo_app.wh, "NOPE", week=week)
    with pytest.raises(ValueError, match="不支持"):
        F.forecast(demo_app.wh, metric="margin", week=week)


def test_forecast_tool_end_to_end(demo_app, week):
    result = Tools(demo_app).forecast_sales({"store": "S01", "category": "SKINCARE", "metric": "qty", "week": week})
    assert result["kind"] == "table" and len(result["rows"]) == 4
    assert result["open"]["url"].startswith("/forecast?") and "metric=qty" in result["open"]["url"]
    assert check_text(result["fallback"], result["facts"]) is None
    assert all(len(q["sql"]) <= 1500 for q in result["queries"])
    assert "不代表因果" in result["facts"]
    with pytest.raises(ToolError):
        Tools(demo_app).forecast_sales({"store": "没有这家店"})


def test_forecast_page_and_scope_selection(demo_app, week):
    from fastapi.testclient import TestClient

    from reportagent.server import create_app

    client = TestClient(create_app(demo_app))
    page = client.get("/forecast", params={"store": "S01", "category": "SKINCARE", "week": week})
    assert page.status_code == 200 and "SHAP 归因" in page.text and "回测" in page.text
    assert "default-src 'none'" in page.headers["content-security-policy"]
    assert "<script" not in page.text and "合成演示数据" in page.text
    overall = client.get("/forecast", params={"week": week})
    assert overall.status_code == 200 and "全部" in overall.text
    assert client.get("/forecast", params={"store": "NOPE", "week": week}).status_code == 400
    assert client.get("/forecast", params={"week": "abc"}).status_code == 400
