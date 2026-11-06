"""漏斗分析：按步骤统计去重访客，支持选维度和逐级下钻。

ponytail: 这是“同周期各步骤 UV 之比”，不是同一用户按顺序走完的严格路径漏斗。
严格路径需要窗口函数，等有真实需求且数据规模允许时再加。
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from .analysis import ratio
from .warehouse import DataUnavailable, Period, parse_week, week_of


def _week_periods(week):
    start = parse_week(week)
    this = Period(start, start + timedelta(days=6))
    prev = Period(start - timedelta(days=7), start - timedelta(days=1))
    r4 = Period(start - timedelta(days=28), start - timedelta(days=1))
    return {"week": this, "prev": prev, "r4": r4}


def latest_funnel_week(wh):
    latest = wh.latest_date("funnel")
    if latest is None:
        raise DataUnavailable("漏斗表没有数据")
    if latest.isoweekday() != 7:
        latest -= timedelta(days=latest.isoweekday())
    return week_of(latest)


def _pct(a, b):
    r = ratio(a, b)
    return None if r is None else r * 100


def _step_frames(wh, steps, dims, periods, filters):
    def one(step):
        f = {**filters, "event": step["value"]}
        return wh.aggregate("funnel", dims, {"uv": ("distinct", "user")}, periods, f, f"漏斗：{step['name']}")

    with ThreadPoolExecutor(max_workers=len(steps)) as pool:  # 每步一条查询，并行能明显缩短等待
        return list(pool.map(one, steps))


def _row(values, steps):
    """values: {step_index: {period: uv}}，算各步 UV、转化和周环比。"""
    out = {"steps": [], "overall": None, "overall_prev": None}
    for i, step in enumerate(steps):
        uv, prev = values[i]["week"], values[i]["prev"]
        conv = _pct(uv, values[i - 1]["week"]) if i else None
        conv_prev = _pct(prev, values[i - 1]["prev"]) if i else None
        conv_r4 = _pct(values[i]["r4"], values[i - 1]["r4"]) if i else None
        out["steps"].append({
            "name": step["name"], "uv": uv, "wow": (uv / prev * 100) if prev > 0 else None,
            "r4_avg": values[i]["r4"] / 4, "conv": conv, "conv_prev": conv_prev, "conv_r4": conv_r4,
            "conv_change": conv - conv_prev if conv is not None and conv_prev is not None else None,
        })
    last = len(steps) - 1
    out["overall"] = _pct(values[last]["week"], values[0]["week"])
    out["overall_prev"] = _pct(values[last]["prev"], values[0]["prev"])
    return out


CACHE_SECONDS = 600
_cache = {}


def analyze_funnel(wh, week=None, dimension=None, filters=None):
    """同样的查询 10 分钟内直接复用。ponytail: 进程内缓存；多实例时换 Redis。"""
    key = json.dumps([id(wh), week, dimension, filters], sort_keys=True, ensure_ascii=False)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    result = _compute_funnel(wh, week, dimension, filters)
    if len(_cache) > 200:
        _cache.clear()
    _cache[key] = (time.time(), result)
    return result


def _compute_funnel(wh, week=None, dimension=None, filters=None):
    sem = wh.semantic
    if not sem.has("funnel"):
        raise DataUnavailable("当前数仓没有配置漏斗数据。")
    src = sem.source("funnel")
    steps, dimensions = src.steps, src.dimensions
    if len(steps) < 2:
        raise DataUnavailable("漏斗至少需要两个步骤。")
    week = str(week or latest_funnel_week(wh))
    latest = wh.latest_date("funnel")
    periods = _week_periods(week)
    if latest < periods["week"].end:
        raise DataUnavailable(f"周次 {week} 还没结束，漏斗数据只更新到 {latest}。最近完整周是 {latest_funnel_week(wh)}。")

    order = list(dimensions)
    dimension = dimension or order[0]
    if dimension not in dimensions:
        raise ValueError(f"不支持的维度 {dimension}，可选：{'、'.join(order)}")
    filters = {k: v for k, v in (filters or {}).items() if v}
    bad = [k for k in filters if k not in dimensions]
    if bad:
        raise ValueError(f"不支持按 {bad[0]} 筛选，可选：{'、'.join(order)}")

    start_log = len(wh.log)
    total_frames = _step_frames(wh, steps, [], periods, filters)
    total_values = {i: {p: float(f[f"uv__{p}"].iloc[0]) for p in periods} for i, f in enumerate(total_frames)}
    total = _row(total_values, steps)
    if total["steps"][0]["uv"] <= 0:
        raise DataUnavailable(f"第 {week} 周在当前筛选下没有行为数据。")

    # 近 8 周整体转化趋势
    monday = parse_week(week)
    trend_periods = {week_of(monday - timedelta(days=7 * i)): Period(monday - timedelta(days=7 * i), monday - timedelta(days=7 * i - 6))
                     for i in range(7, -1, -1)}
    trend_frames = _step_frames(wh, [steps[0], steps[-1]], [], trend_periods, filters)
    trend = [{"week": w, "overall": _pct(float(trend_frames[1][f"uv__{w}"].iloc[0]), float(trend_frames[0][f"uv__{w}"].iloc[0]))}
             for w in trend_periods]

    frames = _step_frames(wh, steps, [dimension], periods, filters)
    keys = set()
    for f in frames:
        keys.update(f[dimension])
    lookup = [f.set_index(dimension) for f in frames]
    rows = []
    for key in keys:
        values = {i: {p: float(lookup[i][f"uv__{p}"].get(key, 0.0)) for p in periods} for i in range(len(steps))}
        row = _row(values, steps)
        if row["steps"][0]["uv"] <= 0:
            continue
        row["name"] = key
        row["share"] = _pct(row["steps"][0]["uv"], total["steps"][0]["uv"])
        rows.append(row)
    rows.sort(key=lambda r: -r["steps"][0]["uv"])

    # 机会点：流量够大（占比 ≥ 1%）但转化低于整体的对象，按“补齐到整体水平能多成交多少”排序
    for r in rows:
        gap = (total["overall"] or 0) - (r["overall"] or 0)
        r["opportunity"] = max(gap, 0) / 100 * r["steps"][0]["uv"] if (r["share"] or 0) >= 1 else 0
    opportunity = sorted((r for r in rows if r["opportunity"] > 0 and r["name"] != "未分类"), key=lambda r: -r["opportunity"])[:3]

    biggest = min((s for s in total["steps"] if s["conv"] is not None), key=lambda s: s["conv"])
    index = order.index(dimension)
    return {
        "week": week, "period": {"start": str(periods["week"].start), "end": str(periods["week"].end)},
        "latest_date": str(latest), "note": src.note, "steps": steps, "total": total, "trend": trend,
        "dimension": dimension, "dimension_label": dimensions[dimension], "dimensions": dimensions,
        "next_dimension": order[index + 1] if index + 1 < len(order) else None,
        "filters": filters, "rows": rows, "opportunity": opportunity, "biggest_drop": biggest,
        "queries": wh.log[start_log:],
    }
