# -*- coding: utf-8 -*-
"""
DTC-RCMP 销售分析 + Sales Tree（迁移自 notebook）
=================================================
Sales Tree 图从 graphviz 改为纯 HTML/CSS 渲染：
无系统二进制依赖，可直接内嵌 Streamlit 页面与下载的 HTML 报告中。
"""

import json
import math

from . import llm


def online_for_human(df2, hfb):
    results = []
    hfb_perf = df2[(df2['hfb_no'] == hfb) & (df2['date_type'] == 'Weekly')]
    rolling_4wks = df2[(df2['hfb_no'] == hfb) & (df2['date_type'] == 'Rolling 4wks')]
    hfb_perf = hfb_perf.iloc[0]
    rolling_4wks_perf = rolling_4wks.iloc[0]

    def format_metric(metric_name, current, rolling, multiplier=1, fmt=".0f"):
        current_val = current * multiplier
        rolling_val = rolling * multiplier
        diff_rolling = current_val - rolling_val
        return f"{metric_name}: {current_val:{fmt}} ({diff_rolling:+.0f} vs. 4WKs)"

    kpi_metrics = [
        format_metric("Sales ind.LY", hfb_perf['sales_ind_ly'], rolling_4wks_perf['sales_ind_ly']),
        format_metric("Qty ind.LY", hfb_perf['qty_ind_ly'], rolling_4wks_perf['qty_ind_ly']),
    ]
    results.append("，".join(kpi_metrics))

    tree_metrics = [
        format_metric("PIP ind.LY", hfb_perf['pip_ind_ly'], rolling_4wks_perf['pip_ind_ly']),
        format_metric("HFB Tickets ind.LY", hfb_perf['ticket_ind_ly'], rolling_4wks_perf['ticket_ind_ly']),
        format_metric("HFB Conv. Rate ind.LY", hfb_perf['ticket_conv_ind_ly'], rolling_4wks_perf['ticket_conv_ind_ly']),
    ]
    tree_metrics.append(
        f"Items/ticket {hfb_perf['itemperticket_ty']:.1f}→{hfb_perf['itemperticket_lyr']:.1f} "
        f"ind.LY: {hfb_perf['itemperticket_ind_ly']:.0f} "
        f"({hfb_perf['itemperticket_ind_ly'] - rolling_4wks_perf['itemperticket_ind_ly']:+.0f} vs. 4WKs)"
    )
    tree_metrics.append(
        f"Price/item {hfb_perf['priceperitem_ty']:.1f}→{hfb_perf['priceperitem_lyr']:.1f} "
        f"ind.LY: {hfb_perf['priceperitem_ind_ly']:.0f} "
        f"({hfb_perf['priceperitem_ind_ly'] - rolling_4wks_perf['priceperitem_ind_ly']:+.0f} vs. 4WKs)"
    )
    results.append("，".join(tree_metrics))
    return results


def _safe_round(value):
    """将 ind.LY 值取整；若为 None/NaN 返回 None；若以 0-2 区间的小数口径存储则先 ×100。"""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, (int, float)) and 0 < value < 2:
        return round(value * 100)
    return round(value)


def _format_ind(ind_value):
    return _safe_round(ind_value)


def online_for_llm(df2, hfb):
    results = []
    hfb_perf = df2[(df2['hfb_no'] == hfb) & (df2['date_type'] == 'Weekly')]
    if hfb_perf.empty:
        return [f"HFB {hfb} 无数据"]
    hfb_perf = hfb_perf.iloc[0]

    results.append("，".join([
        f"Sales ind.LY: {_format_ind(hfb_perf['sales_ind_ly'])}",
        f"Qty ind.LY: {_format_ind(hfb_perf['qty_ind_ly'])}",
    ]))
    results.append("，".join([
        f"PIP ind.LY: {_format_ind(hfb_perf['pip_ind_ly'])}",
        f"HFB Conv. Rate ind.LY: {_format_ind(hfb_perf['ticket_conv_ind_ly'])}",
        f"Items/ticket ind.LY: {_format_ind(hfb_perf['itemperticket_ind_ly'])}",
        f"Price/item ind.LY: {_format_ind(hfb_perf['priceperitem_ind_ly'])}",
    ]))
    return results


# ---------------------------------------------------------------------------
# Sales Tree
# ---------------------------------------------------------------------------

def retrieve_sales_tree_data(df2, hfb):
    hfb_perf = df2[(df2['hfb_no'] == hfb) & (df2['date_type'] == 'Weekly')].iloc[0]
    result = {
        'PIP ind': _safe_round(hfb_perf.get('pip_ind_ly')),
        'HFB Conv.ind.ly': _safe_round(hfb_perf.get('ticket_conv_ind_ly')),
        'Addtocard ind': _safe_round(hfb_perf.get('atc_ind_ly')),
        'PIP Conv.ind.ly': _safe_round(hfb_perf.get('pip_conv_ind_ly')),
        'Checkout ind': _safe_round(hfb_perf.get('checkout_ind_ly')),
        'Addtocard Conv.ind.ly': _safe_round(hfb_perf.get('checkout_conv_ind_ly')),
        'Buy ind': _safe_round(hfb_perf.get('buyer_ind_ly')),
        'Checkout Conv.ind.ly': _safe_round(hfb_perf.get('buy_conv_ind_ly')),
        'item/ticket ind': _safe_round(hfb_perf.get('itemperticket_ind_ly')),
        'price/item ind': _safe_round(hfb_perf.get('priceperitem_ind_ly')),
        'HFB ticket ind': _safe_round(hfb_perf.get('ticket_ind_ly')),
        'qty ind': _safe_round(hfb_perf.get('qty_ind_ly')),
        'ATV ind': _safe_round(hfb_perf.get('atv_ind_ly')),
        'HFB sales ind': _safe_round(hfb_perf.get('sales_ind_ly')),
    }
    return json.dumps(result, ensure_ascii=False)


def _node(label, value):
    color = "#1a7f37" if (value is not None and value >= 100) else "#c0392b"
    v = value if value is not None else "NA"
    return (f"<div class='tree-node'><div class='tree-label'>{label}</div>"
            f"<div class='tree-value' style='color:{color}'>ind.LY {v}</div></div>")


def sales_tree_html(sales_tree_data):
    """纯 HTML/CSS 的 Sales Tree（替代 notebook 的 graphviz 实现）。"""
    g = json.loads(sales_tree_data)
    return f"""
<div class='sales-tree'>
  <div class='tree-col'>
    <div class='tree-node root'><div class='tree-label'>HFB Sales</div>
      <div class='tree-value' style='color:{"#1a7f37" if (g.get("HFB sales ind") or 0) >= 100 else "#c0392b"}'>ind.LY {g.get("HFB sales ind")}</div></div>
  </div>
  <div class='tree-col'>
    {_node("HFB Ticket", g.get("HFB ticket ind"))}
    {_node("ATV", g.get("ATV ind"))}
  </div>
  <div class='tree-col'>
    {_node("PIP", g.get("PIP ind"))}
    {_node("Conv. Rate", g.get("HFB Conv.ind.ly"))}
    {_node("Items/ticket", g.get("item/ticket ind"))}
    {_node("Price/item", g.get("price/item ind"))}
  </div>
  <div class='tree-col'>
    {_node("Add to cart", g.get("Addtocard ind"))}
    {_node("PIP Conv.", g.get("PIP Conv.ind.ly"))}
    {_node("Checkout", g.get("Checkout ind"))}
    {_node("ATC Conv.", g.get("Addtocard Conv.ind.ly"))}
    {_node("Buyer", g.get("Buy ind"))}
    {_node("Checkout Conv.", g.get("Checkout Conv.ind.ly"))}
  </div>
</div>
<div class='tree-caption'>Sales Tree：从右至左为漏斗下钻（Buyer → Checkout → Add to cart → PIP），各级配 Conv. Rate；绿 ≥100，红 &lt;100。</div>
"""


def online_analysis(
    df2,
    hfb,
    use_llm=True,
    *,
    llm_config=None,
    llm_events=None,
):
    """DTC-RCMP 销售分析模块入口，返回 (HTML 片段, raw 数值上下文)。"""
    outputs_for_llm = online_for_llm(df2, hfb)
    outputs_for_human = online_for_human(df2, hfb)

    perf = df2[(df2['hfb_no'] == hfb) & (df2['date_type'] == 'Weekly')].iloc[0]
    raw = {
        "sales_ind_ly": float(perf["sales_ind_ly"]),
        "tree": {
            "PIP": float(perf["pip_ind_ly"]),
            "Conv. Rate": float(perf["ticket_conv_ind_ly"]),
            "Items/ticket": float(perf["itemperticket_ind_ly"]),
            "Price/item": float(perf["priceperitem_ind_ly"]),
        },
    }

    summary = llm.online_summary(
        outputs_for_llm,
        raw,
        use_llm=use_llm,
        llm_config=llm_config,
        events=llm_events,
    )
    tree_html = sales_tree_html(retrieve_sales_tree_data(df2, hfb))

    html = f"""### <span style='color: #0058a3;'>DTC-RCMP 销售分析</span>
{summary}<br>

- **HFB KPI**：{outputs_for_human[0]}
- **HFB Sales Tree**：{outputs_for_human[1]}

{tree_html}
"""
    return html, raw
