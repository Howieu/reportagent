# -*- coding: utf-8 -*-
"""
ML 深度分析：归因 + 预测（notebook 四模型融合的轻量重构版）
=============================================================
- 归因：LightGBM + SHAP 计算特征重要性（完整版为 LGBM/XGB/CatBoost/GBRT 四模型
  按 1/MSE 加权融合，Demo 默认轻量单模型，秒级出结果）；依赖缺失或训练失败时
  自动降级为 |Pearson 相关系数| 排序，保证演示不中断。
- 预测：最近 28 天按星期几取均值，滚动外推未来 7 天（完整版为 Prophet +
  滞后特征树模型，Demo 默认轻量实现）。
- mock 数据的 sale_net_amt 由驱动特征显式生成，因此归因结果有真实信号。
"""

import numpy as np
import pandas as pd

# 特征的业务友好名称（不让业务读者直接看英文列名）
FEATURE_NAME_MAP = {
    "daily_pip": "PIP流量",
    "conv_rate": "转化率",
    "avg_price": "件单价",
    "discount_depth": "促销力度",
    "stock_rate": "库存充足率",
    "week_of_year": "周次",
}

_FEATURES = list(FEATURE_NAME_MAP.keys())
_TARGET = "sale_net_amt"

try:
    import lightgbm as lgb
    import shap
    _HAS_ML = True
except ImportError:
    _HAS_ML = False


def _importance_lgbm_shap(X, y):
    model = lgb.LGBMRegressor(random_state=42, min_data_in_leaf=5,
                              min_gain_to_split=0.01, verbose=-1)
    model.fit(X, y)
    explainer = shap.Explainer(model, X)
    sample = X.sample(n=min(200, len(X)), random_state=42)
    shap_values = explainer(sample, check_additivity=False)
    return np.abs(shap_values.values).mean(axis=0)


def _importance_correlation(X, y):
    corrs = []
    for col in X.columns:
        c = np.corrcoef(X[col], y)[0, 1]
        corrs.append(abs(c) if not np.isnan(c) else 0.0)
    return np.array(corrs)


def top3_features(pred_df, entity_col, entity_ids):
    """计算每个实体影响 Sales 的前三特征，返回 {entity_id: 人类可读文本}。"""
    results = {}
    data = pred_df[pred_df[entity_col].isin(entity_ids)]
    for eid, group in data.groupby(entity_col):
        if len(group) < 20:
            results[eid] = "样本不足，无法归因"
            continue
        X = group[_FEATURES].astype(float)
        y = group[_TARGET].astype(float)
        try:
            importance = (_importance_lgbm_shap(X, y) if _HAS_ML
                          else _importance_correlation(X, y))
        except Exception:
            importance = _importance_correlation(X, y)

        total = importance.sum()
        if total <= 0:
            results[eid] = "特征重要性计算失败"
            continue
        order = np.argsort(importance)[::-1][:3]
        parts = [f"{FEATURE_NAME_MAP[_FEATURES[i]]}（{importance[i] / total * 100:.1f}%）"
                 for i in order]
        method = "" if _HAS_ML else "（相关性方法）"
        results[eid] = f"影响 Sales 的前三指标为{method}：" + "、".join(parts)
    return results


def forecast_next_week(pred_df, entity_col, entity_ids, days=7):
    """轻量预测：最近 28 天按星期几取均值外推，返回 {entity_id: 周总量}。"""
    results = {}
    data = pred_df[pred_df[entity_col].isin(entity_ids)].copy()
    data["payment_date"] = pd.to_datetime(data["payment_date"])
    for eid, group in data.groupby(entity_col):
        group = group.sort_values("payment_date").tail(28)
        if len(group) < 14:
            continue
        by_dow = group.groupby(group["payment_date"].dt.dayofweek)[_TARGET].mean()
        last_date = group["payment_date"].max()
        total = 0.0
        for d in range(1, days + 1):
            dow = (last_date + pd.Timedelta(days=d)).dayofweek
            total += float(by_dow.get(dow, by_dow.mean()))
        results[eid] = round(total, 2)
    return results
