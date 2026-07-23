import pandas as pd

from src.analysis_drilldown import potential_recognition

HFB, PA, FAMILY, ITEM = "01", "PA1", "FAM1", "ITEM1"


def _rows(*, weekly_available_percent, weekly_qty_1k_cus_ind_ly, weekly_sales_ind_ly,
          rolling_available_percent, rolling_sales_ind_ly):
    common = {"hfb_no": HFB, "pa_no": PA, "item_family": FAMILY, "item_id": ITEM}
    return pd.DataFrame([
        {**common, "date_type": "Weekly",
         "available_percent": weekly_available_percent,
         "qty_1k_cus_ind_ly": weekly_qty_1k_cus_ind_ly,
         "sales_ind_ly": weekly_sales_ind_ly},
        {**common, "date_type": "Rolling 4wks",
         "available_percent": rolling_available_percent,
         "qty_1k_cus_ind_ly": 0,
         "sales_ind_ly": rolling_sales_ind_ly},
    ])


def test_missing_data_returns_no_signal():
    empty = pd.DataFrame(columns=["hfb_no", "pa_no", "item_family", "item_id", "date_type"])
    assert potential_recognition(empty, HFB, PA, FAMILY, ITEM, "sales", desc=True) == (None, [])


def test_desc_continuous_out_of_stock():
    df = _rows(weekly_available_percent=80, weekly_qty_1k_cus_ind_ly=50, weekly_sales_ind_ly=100,
               rolling_available_percent=0, rolling_sales_ind_ly=100)
    assert potential_recognition(df, HFB, PA, FAMILY, ITEM, "sales", desc=True) == (False, ["连续4周缺货"])


def test_desc_temporary_out_of_stock_is_potential():
    df = _rows(weekly_available_percent=30, weekly_qty_1k_cus_ind_ly=50, weekly_sales_ind_ly=100,
               rolling_available_percent=80, rolling_sales_ind_ly=100)
    potential, reasons = potential_recognition(df, HFB, PA, FAMILY, ITEM, "sales", desc=True)
    assert (potential, reasons) == (True, ["临时性缺货"])


def test_desc_high_qty_per_1k_cus_rules_out_potential():
    df = _rows(weekly_available_percent=80, weekly_qty_1k_cus_ind_ly=150, weekly_sales_ind_ly=100,
               rolling_available_percent=80, rolling_sales_ind_ly=100)
    potential, reasons = potential_recognition(df, HFB, PA, FAMILY, ITEM, "sales", desc=True)
    assert potential is False
    assert "Qty / 1k Cus ind.LY: 150" in reasons[0]


def test_desc_significant_downward_trend_is_potential():
    df = _rows(weekly_available_percent=80, weekly_qty_1k_cus_ind_ly=50, weekly_sales_ind_ly=40,
               rolling_available_percent=80, rolling_sales_ind_ly=100)
    assert potential_recognition(df, HFB, PA, FAMILY, ITEM, "sales", desc=True) == (True, ["环比趋势显著向下"])


def test_desc_no_signal_when_nothing_triggers():
    df = _rows(weekly_available_percent=80, weekly_qty_1k_cus_ind_ly=50, weekly_sales_ind_ly=90,
               rolling_available_percent=80, rolling_sales_ind_ly=100)
    assert potential_recognition(df, HFB, PA, FAMILY, ITEM, "sales", desc=True) == (False, [])


def test_asc_low_qty_per_1k_cus_rules_out_potential():
    df = _rows(weekly_available_percent=80, weekly_qty_1k_cus_ind_ly=50, weekly_sales_ind_ly=100,
               rolling_available_percent=80, rolling_sales_ind_ly=100)
    potential, reasons = potential_recognition(df, HFB, PA, FAMILY, ITEM, "sales", desc=False)
    assert potential is False
    assert "Qty / 1k Cus ind.LY: 50" in reasons[0]


def test_asc_significant_upward_trend_is_potential():
    df = _rows(weekly_available_percent=80, weekly_qty_1k_cus_ind_ly=150, weekly_sales_ind_ly=160,
               rolling_available_percent=80, rolling_sales_ind_ly=100)
    assert potential_recognition(df, HFB, PA, FAMILY, ITEM, "sales", desc=False) == (True, ["环比趋势显著向上"])
