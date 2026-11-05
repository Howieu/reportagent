import math

import pytest
from sqlalchemy.dialects import mysql, postgresql

from reportagent.analysis import analyze, potential
from reportagent.warehouse import DataUnavailable, build_periods


def test_hand_computed_indices_on_sqlite(tiny):
    r = analyze(tiny.wh, "A", "X", "202644")
    w = r["overall"]["week"]
    assert w["sales"] == 550                       # 300+100+100+50，不含窗口外的 999
    assert w["sales_vs_ly"] == pytest.approx(550 / 600 * 100)
    assert w["sales_vs_ly_comp"] == pytest.approx(150)  # B 店 900/600
    assert w["share"] == pytest.approx(550 / 1450 * 100)
    assert w["rank"] == 2 and w["prev_gap"] == 350
    retail = r["tree"]["nodes"]
    assert retail["sales"]["ty"] == 500 and retail["sales"]["ly"] == 500
    assert retail["tickets"]["ty"] == 2            # t1 跨两行只算一单


def test_missing_optional_sources_are_omitted(tiny):
    r = analyze(tiny.wh, "A", "X", "202644")
    assert "traffic" not in r["tree"]["nodes"]
    assert r["overall"]["week"]["sales_vs_goal"] is None


def test_incomplete_week_and_unknown_store_raise(tiny):
    with pytest.raises(DataUnavailable, match="还没结束"):
        analyze(tiny.wh, "A", "X", "202645")
    with pytest.raises(DataUnavailable, match="找不到门店"):
        analyze(tiny.wh, "NOPE", "X", "202644")
    with pytest.raises(DataUnavailable, match="没有销售数据"):
        analyze(tiny.wh, "A", "NOPE", "202644")


def test_report_finds_planted_anomalies(demo_app, week):
    r = analyze(demo_app.wh, "S01", "SKINCARE", week)
    ups = {f["name"] for s in r["drill"]["up"] for f in s["families"]}
    downs = {f["name"] for s in r["drill"]["down"] for f in s["families"]}
    assert "LUMERA" in ups and "VELOUR" in downs
    velour = next(i for s in r["drill"]["down"] for f in s["families"] if f["name"] == "VELOUR" for i in f["items"])
    assert velour["potential"] and "缺货" in velour["reason"]


def test_sales_tree_identities_hold(demo_app, week):
    n = analyze(demo_app.wh, "S02", "MAKE UP", week)["tree"]["nodes"]
    assert n["ab"]["ty"] * n["tickets"]["ty"] == pytest.approx(n["sales"]["ty"])
    assert n["traffic"]["ty"] * n["cr"]["ty"] * n["ai"]["ty"] * n["price"]["ty"] == pytest.approx(n["sales"]["ty"])


def test_contributions_sum_to_100(demo_app, week):
    t = analyze(demo_app.wh, "S03", "SKINCARE", week)["tree"]
    assert sum(c["share"] for c in t["contributions"]) == pytest.approx(100)
    assert not math.isnan(t["contributions"][0]["ln"])


def test_potential_rules():
    info = {"ly": 100, "vs_r4": 60, "share": 5, "avg_share": 10}
    assert potential(info, "up", 120) == (True, "环比趋势显著向上")
    assert potential(info, "up", 80)[0] is False
    assert potential({**info, "ly": 1}, "up", 120) == (False, "去年基数太小")
    assert potential({**info, "vs_r4": 0}, "down", 90, available=30)[0] is True
    assert potential({**info, "vs_r4": 0}, "down", 90, available_r4=0) == (False, "连续 4 周缺货")
    assert potential({**info, "vs_r4": 0}, "down", 120)[0] is False


def test_sql_compiles_and_binds_values(demo_app, week):
    wh = demo_app.wh
    p = build_periods(week, wh.semantic)
    stmt = wh.statement("sales", ["family"], {"s": ("sum", "sales"), "t": ("distinct", "ticket")},
                        {"week": p["week"]}, {"store": "S01'; DROP TABLE x;--"})
    compiled = str(stmt.compile())
    assert "DROP TABLE" not in compiled                     # 值走参数绑定
    from odps.sqlalchemy_odps import ODPSDialect
    for dialect in (postgresql.dialect(), mysql.dialect(), ODPSDialect()):
        assert "count(" in str(stmt.compile(dialect=dialect)).lower()
