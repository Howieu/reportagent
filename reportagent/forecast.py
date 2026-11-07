"""销量预测和 SHAP 归因。

原 notebook 的做法不可信：特征里留着同期字段，又用随机切分，等于拿答案预测答案。这里用三条规则防泄漏：
1. 特征只用预测起点及之前的数据（features）。
2. 训练样本的目标周不晚于训练截止周（_pairs + 掩码）。
3. 用滚动回测和简单基线比较，模型赢了才用模型的数字，否则用基线（_method）。

序列包含门店 × 品类、门店合计、品类合计和全仓合计，一起训练，每个范围直接用自己的序列预测。
实测明细加总会系统性偏低，大范围反而不如基线。目标是“目标周值 / 近 8 周周均”，乘回周均后 SHAP 各项可以直接相加。
SHAP 用 LightGBM 自带的精确 TreeSHAP，解释的是模型，不是因果。
"""

import ctypes
import re
import sys
import threading
import time
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .narrative import money, num
from .warehouse import DataUnavailable, Period, parse_week, week_of

HISTORY_WEEKS = 104
HORIZONS = (1, 2, 3, 4)
BACKTEST_WEEKS = 12
MIN_WEEKS = 8 + BACKTEST_WEEKS + max(HORIZONS) + 6
SPARSE_WEEK = 0.6  # 全仓最新一周不足前 4 周均值的这个比例，视为数据没入齐
PARAMS = {"objective": "huber", "learning_rate": 0.03, "num_leaves": 7, "min_data_in_leaf": 30, "bagging_fraction": 0.8,
          "bagging_freq": 1, "feature_fraction": 0.8, "verbose": -1, "seed": 7, "deterministic": True,
          "force_row_wise": True, "num_threads": 2}
ROUNDS = 200
ALL = ""  # 合计序列的门店或品类取值
METRICS = {"sales": "销售额", "qty": "销量"}
BASELINES = {"last": "上周值", "mean4": "近 4 周均值", "mean8": "近 8 周均值"}
# (展示名, 对应的特征列)
GROUPS = [("上周表现", [0]), ("前 2 到 4 周表现", [1, 2, 3, 4]), ("价格变化", [5]), ("大盘走势", [6]),
          ("去年同期季节性", [7, 8]), ("经营规模", [9])]
FEATURE_COUNT = 10


@dataclass
class Panel:
    weeks: list  # 每周周一
    stores: np.ndarray
    categories: np.ndarray
    y: np.ndarray  # 序列 × 周
    sales: np.ndarray
    qty: np.ndarray


_load_error = None


def _short_error(exc):
    """只留库名和原因，页面上不暴露服务器目录。"""
    return re.sub(r"/[^\s:'\"]*/", "", str(exc))[:200]


def _load_lightgbm():
    """Linux 上依赖 libgomp。Vercel 由构建脚本打包到 native/，先载入后 LightGBM 才能按库名找到它。
    加载失败时退回基线，不让整个服务起不来。"""
    global _load_error
    bundled = Path(__file__).parent / "native" / "libgomp.so.1"
    try:
        if bundled.exists():
            ctypes.CDLL(str(bundled), mode=ctypes.RTLD_GLOBAL)
        import lightgbm
    except (ImportError, OSError) as exc:
        _load_error = _short_error(exc)
        print(f"LightGBM 加载失败：{_load_error}", file=sys.stderr)
        return None
    _load_error = None
    return lightgbm


def load_panel(wh, metric, week):
    monday = parse_week(week)
    weeks = [monday - timedelta(days=7 * i) for i in range(HISTORY_WEEKS - 1, -1, -1)]
    periods = {f"w{i}": Period(d, d + timedelta(days=6)) for i, d in enumerate(weeks)}
    measures = {"sales": ("sum", "sales"), "qty": ("sum", "qty")}
    frame = wh.aggregate("sales", ["store", "category"], measures, periods, None, "预测：门店 × 品类周度历史")
    if frame.empty:
        raise DataUnavailable("销售表在这段时间没有数据，无法预测。")
    return _trim_leading_weeks(build_panel(frame, weeks, metric))


def build_panel(frame, weeks, metric):
    """明细行加上门店合计、品类合计和全仓合计。"""
    sales_cols = [f"sales__w{i}" for i in range(len(weeks))]
    qty_cols = [f"qty__w{i}" for i in range(len(weeks))]
    cols = [*sales_cols, *qty_cols]
    # SQL 不保证行序，而采样依赖行序。排序后同样的数据才能得到同样的预测
    frame = frame[["store", "category", *cols]].sort_values(["store", "category"], ignore_index=True).copy()
    levels = [frame,
              frame.groupby("store", as_index=False)[cols].sum().reindex(columns=frame.columns, fill_value=ALL),
              frame.groupby("category", as_index=False)[cols].sum().reindex(columns=frame.columns, fill_value=ALL),
              frame[cols].sum().to_frame().T.reindex(columns=frame.columns, fill_value=ALL)]
    full = pd.concat(levels, ignore_index=True)
    sales, qty = full[sales_cols].to_numpy(dtype=float), full[qty_cols].to_numpy(dtype=float)
    return Panel(list(weeks), full["store"].astype(str).to_numpy(), full["category"].astype(str).to_numpy(),
                 sales if metric == "sales" else qty, sales, qty)


def _trim_leading_weeks(p):
    active = np.flatnonzero(p.y.sum(0) > 0)
    if not len(active):
        raise DataUnavailable("销售表在这段时间没有数据，无法预测。")
    start = int(active[0])
    if len(p.weeks) - start < MIN_WEEKS:
        raise DataUnavailable(f"历史只有 {len(p.weeks) - start} 周，至少需要 {MIN_WEEKS} 周才能预测和回测。")
    return Panel(p.weeks[start:], p.stores, p.categories, *[a[:, start:] for a in (p.y, p.sales, p.qty)])


def _ratio(a, b, default=1.0):
    return np.divide(a, b, out=np.full(np.shape(a), default, dtype=float), where=np.asarray(b) > 0)


def features(p, t, h):
    """起点 t 预测 t + h 的特征。所有下标都不超过 t；去年同期也只用已经发生的周。"""
    y = p.y
    scale = y[:, t - 7:t + 1].mean(1)
    lags = [_ratio(y[:, t - i], scale, 0.0) for i in range(4)]
    recent = _ratio(y[:, t - 3:t + 1].mean(1), scale, 0.0)
    price = _ratio(_ratio(p.sales[:, t - 3:t + 1].sum(1), p.qty[:, t - 3:t + 1].sum(1), 0.0),
                   _ratio(p.sales[:, t - 7:t + 1].sum(1), p.qty[:, t - 7:t + 1].sum(1), 0.0))
    total = y.sum(0)  # 每一层加起来都等于全仓，所以比值和只看全仓相同
    market = np.full(len(y), _ratio(total[t - 3:t + 1].mean(), total[t - 7:t + 1].mean()))
    season, known = np.ones(len(y)), np.zeros(len(y))
    if t - 59 >= 0:  # 去年同期前后 3 周相对去年那时近 8 周均值的比值。t + h - 51 <= t，没有用到未来
        base = y[:, t - 59:t - 51].mean(1)
        season = np.minimum(_ratio(y[:, t + h - 53:t + h - 50].mean(1), base), 5.0)
        known = (base > 0).astype(float)
    return np.column_stack([*lags, recent, price, market, season, known, np.log1p(scale)]), scale


def _pairs(p, h):
    """所有可用的 (起点, 序列) 样本。目标周可见与否由调用方按 t + h 过滤。"""
    last = len(p.weeks) - 1
    xs, targets, weights, origins = [], [], [], []
    for t in range(7, last - h + 1):
        x, scale = features(p, t, h)
        keep = scale > 0
        xs.append(x[keep])
        targets.append(np.clip(p.y[keep, t + h] / scale[keep], 0, 8))
        weights.append(np.maximum(np.sqrt(scale[keep]), 1))
        origins.append(np.full(keep.sum(), t))
    return np.vstack(xs), np.concatenate(targets), np.concatenate(weights), np.concatenate(origins)


def _fit(lgb, x, y, w):
    return lgb.train(PARAMS, lgb.Dataset(x, y, weight=w), ROUNDS)


def _baselines(y, t):
    return {"last": y[:, t], "mean4": y[:, t - 3:t + 1].mean(1), "mean8": y[:, t - 7:t + 1].mean(1)}


def train(p):
    """每个预测步长一个模型：滚动回测 + 用全部历史训练最终模型。"""
    lgb = _load_lightgbm()
    last = len(p.weeks) - 1
    backtest, final = {}, {}
    for h in HORIZONS:
        x, y, w, origins = (_pairs(p, h) if lgb else (None, None, None, None))
        if lgb and len(y) < 200:
            lgb = None  # 样本太少，树模型没有意义
        rows = []
        for origin in range(last - BACKTEST_WEEKS + 1 - h, last - h + 1):
            pred = None
            if lgb:
                seen = origins + h <= origin  # 只用目标周在起点之前的样本
                model = _fit(lgb, x[seen], y[seen], w[seen])
                now, scale = features(p, origin, h)
                pred = model.predict(now) * scale
            rows.append({"target": origin + h, "model": pred, "actual": p.y[:, origin + h], **_baselines(p.y, origin)})
        backtest[h] = rows
        now, scale = features(p, last, h)
        contrib = _fit(lgb, x, y, w).predict(now, pred_contrib=True) if lgb else None
        final[h] = {"scale": scale, "contrib": contrib, **_baselines(p.y, last)}
    return {"panel": p, "backtest": backtest, "final": final, "model_available": bool(lgb)}


def _wape(rows, mask, name):
    error = sum(abs(r[name][mask].sum() - r["actual"][mask].sum()) for r in rows)
    actual = sum(r["actual"][mask].sum() for r in rows)
    return error / actual * 100 if actual > 0 else None


def _method(trained, mask, h):
    """模型只有在这个范围的回测里赢过最好的基线，才用模型的数字。"""
    rows = trained["backtest"][h]
    pooled = [r for step in HORIZONS for r in trained["backtest"][step]]
    scores = {k: _wape(pooled, mask, k) for k in BASELINES}  # 同一范围所有步长用同一个基线，预测才不会逐周跳方法
    known = {k: v for k, v in scores.items() if v is not None}
    if not known:
        raise DataUnavailable("回测期内这个范围没有销售，无法评估预测。")
    baseline = min(known, key=known.get)
    baseline_wape = _wape(rows, mask, baseline)
    model = _wape(rows, mask, "model") if trained["model_available"] else None
    if baseline_wape is None:
        raise DataUnavailable("回测期内这个范围没有销售，无法评估预测。")
    return {"model_wape": model, "baseline": baseline, "baseline_name": BASELINES[baseline], "baseline_wape": baseline_wape,
            "beats": model is not None and model < baseline_wape}


def _model_point(entry, mask):
    return float((entry["scale"][mask] * entry["contrib"][mask].sum(1)).sum())


def _interval(rows, mask, name):
    """80% 区间：同一方法在回测里“实际 / 预测”的 P10 和 P90。"""
    pairs = [(r["actual"][mask].sum(), r[name][mask].sum()) for r in rows]
    ratios = [a / b for a, b in pairs if b > 0]
    return np.percentile(ratios, [10, 90]) if len(ratios) >= 8 else (None, None)


def shap_attribution(trained, mask, h=1):
    """把下一周的模型预测拆成：近 8 周周均 + 历史平均趋势 + 各因素贡献。三者相加等于模型预测。"""
    entry = trained["final"][h]
    contrib = entry["contrib"]
    if contrib is None:
        return None
    scale = entry["scale"][mask]
    rows = contrib[mask] * scale[:, None]
    start = float(scale.sum())
    items = [{"factor": name, "value": float(rows[:, cols].sum()), "share": float(rows[:, cols].sum()) / start * 100 if start else 0.0}
             for name, cols in GROUPS]
    items.sort(key=lambda x: -abs(x["value"]))
    trend = float(rows[:, FEATURE_COUNT].sum()) - start
    return {"start": start, "trend": trend, "items": items, "model": start + trend + sum(i["value"] for i in items)}


_cache = {}
_lock = threading.Lock()
CACHE_SECONDS = 3600


def _trained(wh, week, metric):
    """要做几十次拟合，按“起点 + 指标”缓存。ponytail: 进程内缓存；多实例时每个实例各训练一次。"""
    key = (id(wh), week, metric)
    with _lock:  # 同时来的请求只训练一次
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
        start = len(wh.log)
        trained = train(load_panel(wh, metric, week))
        trained["queries"] = wh.log[start:]
        if len(_cache) > 20:
            _cache.clear()
        _cache[key] = (time.time(), trained)
        return trained


def _origin(wh, week, metric):
    """没指定周次时用最近完整周；最新一周明显没入齐时退回一周，并写明。"""
    latest = wh.latest_date()
    if latest is None:
        raise DataUnavailable("销售表没有数据")
    if week:
        week = str(week)
        if latest < parse_week(week) + timedelta(days=6):
            raise DataUnavailable(f"周次 {week} 还没结束，数据只更新到 {latest}。最近完整周是 {wh.latest_complete_week()}。")
        return week, None
    week = wh.latest_complete_week()
    monday = parse_week(week)
    periods = {f"w{i}": Period(monday - timedelta(days=7 * i), monday - timedelta(days=7 * i - 6)) for i in range(5)}
    row = wh.aggregate("sales", [], {"v": ("sum", metric)}, periods, None, "预测：检查最新一周是否入齐").iloc[0]
    recent = np.mean([row[f"v__w{i}"] for i in range(1, 5)])
    if recent > 0 and row["v__w0"] < recent * SPARSE_WEEK:
        earlier = week_of(monday - timedelta(days=7))
        share = row["v__w0"] / recent * 100
        return earlier, f"第 {week} 周只有前 4 周均值的 {share:.0f}%，疑似数据没入齐，预测起点退回第 {earlier} 周"
    return week, None


def forecast(wh, store=None, category=None, metric="sales", week=None):
    if metric not in METRICS:
        raise ValueError(f"不支持的预测指标 {metric}，可选：{'、'.join(METRICS)}")
    week, origin_note = _origin(wh, week, metric)
    trained = _trained(wh, week, metric)
    p = trained["panel"]
    mask = (p.stores == (store or ALL)) & (p.categories == (category or ALL))
    labels = wh.semantic.labels
    if not mask.any():
        raise DataUnavailable(f"{store or ''} {category or ''} 近 {HISTORY_WEEKS} 周没有销售数据，无法预测。")
    last = len(p.weeks) - 1
    if p.y[mask, last - 7:last + 1].sum() <= 0:
        raise DataUnavailable(f"{store or ''} {category or ''} 近 8 周没有销售，无法预测。")

    series = p.y[mask].sum(0)
    fmt = money if metric == "sales" else num
    rows = []
    for h in HORIZONS:
        monday = p.weeks[last] + timedelta(days=7 * h)
        entry = trained["final"][h]
        method = _method(trained, mask, h)
        name = "model" if method["beats"] else method["baseline"]
        point = max(_model_point(entry, mask), 0.0) if method["beats"] else float(entry[method["baseline"]][mask].sum())
        low, high = _interval(trained["backtest"][h], mask, name)
        ly_index = last + h - 52
        ly = float(series[ly_index]) if ly_index >= 0 else None
        rows.append({"h": h, "week": week_of(monday), "start": str(monday), "end": str(monday + timedelta(days=6)), "forecast": point,
                     "low": point * low if low is not None else None, "high": point * high if high is not None else None,
                     "method": "模型" if method["beats"] else f"基线（{method['baseline_name']}）",
                     "vs_ly": point / ly * 100 if ly else None, "ly": ly, **method})

    recent = trained["backtest"][1][-8:]
    return {
        "metric": metric, "metric_label": METRICS[metric], "store": store, "category": category, "origin": week,
        "origin_period": {"start": str(p.weeks[last]), "end": str(p.weeks[last] + timedelta(days=6))},
        "latest_date": str(wh.latest_date()), "origin_note": origin_note, "model_available": trained["model_available"], "model_error": _load_error,
        "rows": rows, "shap": shap_attribution(trained, mask), "labels": labels, "fmt": fmt,
        "history": [{"week": week_of(d), "value": float(v)} for d, v in list(zip(p.weeks, series))[-16:]],
        "backtest": [{"week": week_of(p.weeks[r["target"]]), "actual": float(r["actual"][mask].sum()),
                      "model": float(r["model"][mask].sum()) if r["model"] is not None else None,
                      "baseline": float(r[rows[0]["baseline"]][mask].sum())} for r in recent],
        "backtest_weeks": BACKTEST_WEEKS, "queries": trained["queries"],
    }
