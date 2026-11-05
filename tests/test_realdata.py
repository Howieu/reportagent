"""独立核对：绕过产品代码，用 pandas 从原始 CSV 重算，再和产品结果比。原始数据不在时跳过。"""

from pathlib import Path

import pandas as pd
import pytest

from reportagent.analysis import analyze
from reportagent.funnel import analyze_funnel
from reportagent.render import render_funnel
from reportagent.service import App, State

RAW = Path("data/raw")
DB = Path("data/real.duckdb")
pytestmark = pytest.mark.skipif(not DB.exists() or not (RAW / "olist").exists(), reason="需要 data/real.duckdb 和原始 CSV")
WEEK = "201830"


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    state = State(f"sqlite:///{tmp_path_factory.mktemp('s') / 'app.db'}")
    return App("semantic.real.yaml", url=f"duckdb:///{DB}", llm=False, state=state)


def test_report_matches_raw_csv(app):
    r = analyze(app.wh, "SP", "美妆个护", WEEK)
    o = RAW / "olist"
    orders = pd.read_csv(o / "olist_orders_dataset.csv", parse_dates=["order_purchase_timestamp"])
    orders = orders[~orders["order_status"].isin(["canceled", "unavailable"])]
    items = pd.read_csv(o / "olist_order_items_dataset.csv")
    sellers = pd.read_csv(o / "olist_sellers_dataset.csv")
    products = pd.read_csv(o / "olist_products_dataset.csv")
    names = pd.read_csv(o / "product_category_name_translation.csv", encoding="utf-8-sig")
    df = items.merge(orders, on="order_id").merge(sellers, on="seller_id").merge(products, on="product_id").merge(names, on="product_category_name")
    beauty = df[df["product_category_name_english"].isin(["health_beauty", "perfumery", "diapers_and_hygiene"]) & (df["seller_state"] == "SP")]
    day = beauty["order_purchase_timestamp"].dt.normalize()
    ty = beauty[(day >= "2018-07-23") & (day <= "2018-07-29")]
    ly = beauty[(day >= "2017-07-24") & (day <= "2017-07-30")]
    week = r["overall"]["week"]
    assert week["sales"] == pytest.approx(ty["price"].sum())
    assert week["sales_vs_ly"] == pytest.approx(ty["price"].sum() / ly["price"].sum() * 100)
    assert week["qty_vs_ly"] == pytest.approx(len(ty) / len(ly) * 100)
    assert sum(c["sales"] for c in r["channels"]) == pytest.approx(ty["price"].sum())


def test_funnel_matches_raw_csv(app):
    f = analyze_funnel(app.wh, "201535")
    e = pd.read_csv(RAW / "retailrocket" / "events.csv")
    e["day"] = pd.to_datetime(e["timestamp"], unit="ms", utc=True).dt.tz_localize(None).dt.normalize()
    w = e[(e["day"] >= "2015-08-24") & (e["day"] <= "2015-08-30")]
    uv = w.groupby("event")["visitorid"].nunique()
    steps = f["total"]["steps"]
    assert [s["uv"] for s in steps] == [uv["view"], uv["addtocart"], uv["transaction"]]
    assert steps[2]["conv"] == pytest.approx(uv["transaction"] / uv["addtocart"] * 100)
    assert sum(r["steps"][0]["uv"] for r in f["rows"]) >= steps[0]["uv"]  # 同一访客可落在多个品类


def test_funnel_drilldown_narrows(app):
    top = analyze_funnel(app.wh, "201535", "category_l1")
    name = top["rows"][0]["name"]
    child = analyze_funnel(app.wh, "201535", "category_l2", {"category_l1": name})
    assert child["total"]["steps"][0]["uv"] == top["rows"][0]["steps"][0]["uv"]
    assert child["filters"] == {"category_l1": name} and child["next_dimension"] == "category_id"
    assert "category_l2=" not in render_funnel(child).split("Select Dimension")[0]


def test_incomplete_funnel_week_and_bad_dimension(app):
    from reportagent.warehouse import DataUnavailable
    with pytest.raises(DataUnavailable):
        analyze_funnel(app.wh, "201538")
    with pytest.raises(ValueError):
        analyze_funnel(app.wh, "201535", "password")
