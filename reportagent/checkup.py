"""经营体检和情景试算：把预测结果用到业务判断上。

体检：用回测里没见过这一周的预测当“本该卖多少”，找出偏差超过过去半年任何一周的序列，
按金额排序，再拆单量和单件价值、定位子类和品牌，并给出下周预计。
试算：销售额 = 单量 × 客单价，只做恒等式算术并给出这个幅度历史上有多常见，不声称因果。
"""

import math
from datetime import timedelta

import numpy as np

from .forecast import ALL, METRICS, _origin, _trained, detect_anomalies, forecast
from .narrative import money, num
from .warehouse import DataUnavailable, Period, parse_week

MIN_IMPACT_SHARE = 0.005  # 偏差不到全仓当周的这个比例，再异常也不值得看
PLAUSIBILITY_WEEKS = 52


def _filters(store, category):
    return {k: v for k, v in {"store": store, "category": category}.items() if v}


def _weekly_periods(monday):
    return {"now": Period(monday, monday + timedelta(days=6)), "prior": Period(monday - timedelta(days=56), monday - timedelta(days=1))}


def _top_mover(wh, dim, periods, filters, metric, up):
    frame = wh.aggregate("sales", [dim], {"v": ("sum", metric)}, periods, filters, f"体检：定位{wh.semantic.labels.get(dim, dim)}")
    if frame.empty:
        return None
    delta = frame["v__now"] - frame["v__prior"] / 8
    i = delta.idxmax() if up else delta.idxmin()
    if (delta[i] > 0) != up or delta[i] == 0:
        return None
    return {"name": str(frame.loc[i, dim]), "delta": float(delta[i])}


def explain_shift(wh, store, category, metric, week, up):
    """这周相对近 8 周周均，差在单量还是单件价值，主要落在哪个子类和品牌。"""
    periods = _weekly_periods(parse_week(week))
    filters = _filters(store, category)
    row = wh.sales([], periods, filters, "体检：单量和单件价值").iloc[0]
    now, prior = row[f"{metric}__now"], row[f"{metric}__prior"] / 8
    tickets_now, tickets_prior = row["tickets__now"], row["tickets__prior"] / 8
    levers = None
    if min(now, prior, tickets_now, tickets_prior) > 0 and now != prior:
        ln_total = math.log(now / prior)
        tickets = math.log(tickets_now / tickets_prior) / ln_total * 100
        levers = {"tickets": tickets, "per_ticket": 100 - tickets,
                  "tickets_index": tickets_now / tickets_prior * 100,
                  "per_ticket_index": (now / tickets_now) / (prior / tickets_prior) * 100}
    if not levers:
        hint = "先看子类和品牌的变化。"
    elif abs(abs(levers["tickets"]) - abs(levers["per_ticket"])) < 20:  # 差不多时不硬说谁是主因
        hint = "单量和每单价值都有明显变化，先查流量和商品结构。"
    elif abs(levers["tickets"]) > abs(levers["per_ticket"]):
        hint = "主要是单量变化，先查流量、曝光和缺货。" if not up else "主要是单量变化，先确认来源能否持续，并检查库存是否跟得上。"
    else:
        hint = "主要是每单价值变化，先查商品结构和连带购买。"
    return {"now": float(now), "prior": float(prior), "levers": levers, "hint": hint,
            "subcategory": _top_mover(wh, "subcategory", periods, filters, metric, up),
            "family": _top_mover(wh, "family", periods, filters, metric, up)}


def checkup(wh, store=None, category=None, metric="sales", week=None, top=5):
    if metric not in METRICS:
        raise ValueError(f"不支持的指标 {metric}，可选：{'、'.join(METRICS)}")
    week, origin_note = _origin(wh, week, metric)
    trained = _trained(wh, week, metric)
    p = trained["panel"]
    last = len(p.weeks) - 1
    whole = float(p.y[(p.stores == ALL) & (p.categories == ALL), last].sum())
    floor = whole * MIN_IMPACT_SHARE
    detail = (p.stores != ALL) & (p.categories != ALL)
    if store:
        detail &= p.stores == store
    if category:
        detail &= p.categories == category
    if not detail.any():
        raise DataUnavailable(f"{store or ''} {category or ''} 没有销售数据，无法体检。")

    found, checked = [], 0
    for i in np.flatnonzero(detail):
        if p.y[i, last - 7:last + 1].sum() <= 0:
            continue
        mask = np.zeros(len(p.y), dtype=bool)
        mask[i] = True
        try:
            weeks = detect_anomalies(trained, mask)
        except DataUnavailable:
            continue
        if not weeks or weeks[-1]["target"] != last:
            continue
        checked += 1
        a = weeks[-1]
        if a["flag"] and abs(a["impact"]) >= floor:
            found.append({"store": str(p.stores[i]), "category": str(p.categories[i]), **a})
    found.sort(key=lambda x: -abs(x["impact"]))

    names = dict(zip(wh.stores()["store"], wh.stores()["name"]))
    items = []
    for a in found[:top]:
        up = a["flag"] == "up"
        outlook = forecast(wh, a["store"], a["category"], metric, week)["rows"][0]
        items.append({**a, "store_name": names.get(a["store"], a["store"]), "up": up,
                      "why": explain_shift(wh, a["store"], a["category"], metric, week, up),
                      "next_week": outlook["week"], "next_forecast": outlook["forecast"], "next_method": outlook["method"]})
    monday = p.weeks[last]
    return {"metric": metric, "metric_label": METRICS[metric], "week": week, "store": store, "category": category,
            "period": {"start": str(monday), "end": str(monday + timedelta(days=6))}, "origin_note": origin_note,
            "latest_date": str(wh.latest_date()), "checked": checked, "flagged": len(found), "items": items,
            "net_impact": sum(a["impact"] for a in found), "up": sum(a["flag"] == "up" for a in found), "down": sum(a["flag"] == "down" for a in found),
            "floor": floor, "fmt": money if metric == "sales" else num, "labels": wh.semantic.labels,
            "backtest_weeks": len(trained["backtest"][1]), "model_available": trained["model_available"]}


LEVERS = {"sales": {"tickets": "单量", "per_ticket": "客单价"}, "qty": {"tickets": "单量", "per_ticket": "客件数"}}


def what_if(wh, store=None, category=None, metric="sales", lever="tickets", change=None, target=None, week=None):
    """下周预测上做恒等式试算：给变化幅度算结果，或给目标反推需要的幅度。"""
    names = LEVERS.get(metric)
    if not names:
        raise ValueError(f"不支持的指标 {metric}")
    if lever not in names:
        raise ValueError(f"不支持的杠杆 {lever}，可选：{'、'.join(names)}")
    if (change is None) == (target is None):
        raise ValueError("变化幅度和目标值要填且只填一个")
    f = forecast(wh, store, category, metric, week)
    first = f["rows"][0]
    base = first["forecast"]
    if base <= 0:
        raise DataUnavailable("下周预测为 0，无法试算。")
    change = float(change) if change is not None else (float(target) / base - 1) * 100
    if not -90 <= change <= 500:
        raise ValueError(f"变化幅度 {change:.0f}% 超出可试算范围（-90% 到 +500%）。")
    monday = parse_week(f["origin"])
    count = PLAUSIBILITY_WEEKS + 8
    periods = {f"w{i}": Period(monday - timedelta(days=7 * i), monday - timedelta(days=7 * i - 6)) for i in range(count)}
    row = wh.sales([], periods, _filters(store, category), "试算：历史单量和单件价值").iloc[0]
    tickets = np.array([row[f"tickets__w{i}"] for i in range(count)][::-1])
    value = np.array([row[f"{metric}__w{i}"] for i in range(count)][::-1])
    series = tickets if lever == "tickets" else np.divide(value, tickets, out=np.zeros(count), where=tickets > 0)
    moves = [series[t] / series[t - 8:t].mean() - 1 for t in range(8, count) if series[t - 8:t].mean() > 0 and tickets[t] > 0]
    if len(moves) < 8:
        raise DataUnavailable("历史周数太少，无法判断这个幅度是否常见。")
    moves = np.array(moves) * 100
    reached = int((moves >= change).sum() if change >= 0 else (moves <= change).sum())
    return {"forecast": f, "metric_label": METRICS[metric], "lever": lever, "lever_label": names[lever], "change": change,
            "week": first["week"], "base": base, "base_method": first["method"], "result": base * (1 + change / 100),
            "delta": base * change / 100, "reached": reached, "weeks": len(moves), "max_up": float(moves.max()), "max_down": float(moves.min())}



