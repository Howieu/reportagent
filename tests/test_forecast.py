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


def test_load_error_hides_server_paths():
    text = F._short_error(OSError("libgomp.so.1: cannot open shared object file: /var/task/_vendor/lightgbm/lib/lib_lightgbm.so"))
    assert "libgomp.so.1" in text and "/var/task" not in text


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


def test_future_event_calendar_is_learned_and_known_ahead():
    y = seasonal(weeks=90) * 0 + 100.0
    start = date(2024, 1, 1)
    events = []
    for t in range(9, 90, 9):
        monday = start + timedelta(days=7 * t)
        events.append(("大促", monday, monday + timedelta(days=6)))
        y[:, t] *= 3
    p = panel(y)
    p.events = tuple(events)
    x, _ = F.features(p, 44, 1)  # 第 45 周是活动周
    assert x[0, 10] == 7
    x, _ = F.features(p, 45, 1)
    assert x[0, 10] == 0
    s = F.shap_attribution(F.train(p), np.array([True] + [False] * 7), 1)
    assert any(i["factor"] == "活动日历" for i in s["items"])


def test_bad_event_calendar_is_refused():
    from reportagent.config import ConfigError, _events

    assert _events([{"name": "x", "start": "2026-01-01"}])[0][1] == date(2026, 1, 1)
    with pytest.raises(ConfigError):
        _events([{"start": "2026-01-02", "end": "2026-01-01"}])
    with pytest.raises(ConfigError):
        _events([{"name": "没有日期"}])


def test_accuracy_reports_bias_and_out_of_sample_coverage():
    rows = [{"actual": np.array([100.0 + i]), "m": np.array([110.0])} for i in range(12)]
    a = F.accuracy(rows, np.array([True]), "m")
    assert a["bias"] > 0  # 预测总体偏高
    assert 0 <= a["coverage"] <= 100


def test_anomaly_detection_finds_injected_shock_and_stays_quiet_otherwise():
    y = np.random.default_rng(5).normal(1000, 60, (8, 70)).clip(1)
    y[0, -1] = 3000
    y[1, -1] = 200
    trained = F.train(panel(y))

    def flag(i):
        mask = np.zeros(8, dtype=bool)
        mask[i] = True
        return F.detect_anomalies(trained, mask)

    assert flag(0)[-1]["flag"] == "up" and flag(0)[-1]["impact"] > 0
    assert flag(1)[-1]["flag"] == "down" and flag(1)[-1]["impact"] < 0
    quiet = [a["flag"] for i in range(2, 8) for a in flag(i)]
    assert sum(f is not None for f in quiet) / len(quiet) < 0.2
    assert all(a["low"] <= a["expected"] * 2 for a in flag(0))


def test_checkup_ranks_and_explains(demo_app, week):
    from reportagent.checkup import checkup

    F._cache.clear()
    c = checkup(demo_app.wh, week=week)
    assert c["checked"] > 0 and c["flagged"] == c["up"] + c["down"]
    impacts = [abs(a["impact"]) for a in c["items"]]
    assert impacts == sorted(impacts, reverse=True)
    for a in c["items"]:
        assert (a["impact"] > 0) == a["up"] and a["why"]["hint"] and a["next_forecast"] >= 0
    only = checkup(demo_app.wh, "S01", week=week)
    assert all(a["store"] == "S01" for a in only["items"])
    with pytest.raises(DataUnavailable):
        checkup(demo_app.wh, "NOPE", week=week)


def test_shift_explanation_identity_and_direction(demo_app, week):
    from reportagent.checkup import explain_shift

    w = explain_shift(demo_app.wh, "S01", "SKINCARE", "sales", week, True)
    assert w["levers"]["tickets"] + w["levers"]["per_ticket"] == pytest.approx(100)
    assert w["levers"]["tickets_index"] * w["levers"]["per_ticket_index"] / 100 == pytest.approx(w["now"] / w["prior"] * 100)
    assert w["subcategory"] is None or w["subcategory"]["delta"] > 0


def test_what_if_is_arithmetic_and_reports_history(demo_app, week):
    from reportagent.checkup import what_if

    w = what_if(demo_app.wh, "S01", "SKINCARE", "sales", "per_ticket", change=10, week=week)
    assert w["result"] == pytest.approx(w["base"] * 1.1) and w["delta"] == pytest.approx(w["base"] * 0.1)
    assert 0 <= w["reached"] <= w["weeks"] and w["lever_label"] == "客单价"
    target = what_if(demo_app.wh, "S01", "SKINCARE", "sales", "tickets", target=w["base"] * 1.2, week=week)
    assert target["change"] == pytest.approx(20)
    assert what_if(demo_app.wh, "S01", "SKINCARE", "qty", "per_ticket", change=-5, week=week)["lever_label"] == "客件数"
    with pytest.raises(ValueError):
        what_if(demo_app.wh, metric="sales", lever="tickets", week=week)
    with pytest.raises(ValueError):
        what_if(demo_app.wh, metric="sales", lever="nope", change=1, week=week)
    with pytest.raises(ValueError, match="超出"):
        what_if(demo_app.wh, metric="sales", lever="tickets", change=900, week=week)


def test_new_tools_and_pages(demo_app, week):
    from fastapi.testclient import TestClient

    from reportagent.server import create_app

    tools = Tools(demo_app)
    c = tools.business_checkup({"week": week})
    assert c["open"]["url"].startswith("/checkup?") and check_text(c["fallback"], c["facts"]) is None
    w = tools.what_if_forecast({"store": "S01", "category": "SKINCARE", "lever": "per_ticket", "change_pct": 5, "week": week})
    assert check_text(w["fallback"], w["facts"]) is None and "不代表" in w["facts"]
    with pytest.raises(ToolError):
        tools.what_if_forecast({"lever": "tickets", "week": week})

    client = TestClient(create_app(demo_app))
    page = client.get("/checkup", params={"week": week})
    assert page.status_code == 200 and "经营体检" in page.text and "<script" not in page.text
    assert "default-src 'none'" in page.headers["content-security-policy"]
    assert client.get("/checkup", params={"store": "NOPE", "week": week}).status_code == 400
    scenario = client.get("/forecast", params={"store": "S01", "week": week, "lever": "tickets", "change": 5})
    assert scenario.status_code == 200 and "这个幅度有多常见" in scenario.text
    bad = client.get("/forecast", params={"store": "S01", "week": week, "lever": "tickets", "change": 900})
    assert bad.status_code == 200 and "超出" in bad.text
