# -*- coding: utf-8 -*-
"""
异动商品归因：PA → Family → Article 三级下钻（迁移自 notebook）
================================================================
- pa/family/article_for_human：按贡献度排序截取 Top N，生成人读明细；
- potential_recognition：潜力识别规则引擎（缺货、Qty/1k Cus、环比趋势阈值）；
- anomaly_analysis：串起"上升 Top + 下降 Top"双向归因，叠加 ML 归因/预测。
"""

import pandas as pd

from .metrics import display_metrics
from . import ml_insights


# ---------------------------------------------------------------------------
# PA level
# ---------------------------------------------------------------------------

def pa_for_human(pre, hfb, focus, rolling_nWKs, desc=True, limit=8, contribution_threshold=0.9):
    results = {}
    base_metric = focus.replace('_exc', '')
    focus_dif = f'{focus}_dif' if '_exc' in focus else f'{base_metric}_dif'
    focus_exc_dif = f'{base_metric}_exc_dif'
    focus_offline_exc_dif = f'{base_metric}_offline_exc_dif'

    weekly = pre[(pre['date_type'] == 'Weekly') & (pre['hfb_no'] == hfb) &
                 (pre['item_family'] == 'TOTAL') & (pre['item_id'] == 'TOTAL')].copy()
    rolling = pre[(pre['date_type'] == 'Rolling 4wks') & (pre['hfb_no'] == hfb) &
                  (pre['item_family'] == 'TOTAL') & (pre['item_id'] == 'TOTAL')].copy()

    if focus_dif not in weekly.columns:
        return results

    weekly[focus_dif] = pd.to_numeric(weekly[focus_dif], errors='coerce')
    condition = weekly[focus_dif] < 0 if desc else weekly[focus_dif] > 0
    hfb_perf = weekly[condition].copy()
    if hfb_perf.empty:
        return results

    hfb_perf = hfb_perf.groupby('pa_no').agg({focus_dif: 'sum'})
    total_abs_dif = hfb_perf[focus_dif].abs().sum()
    hfb_perf['contribution'] = (hfb_perf[focus_dif].abs() / total_abs_dif
                                if total_abs_dif != 0 else 0)
    hfb_perf = hfb_perf.sort_values('contribution', ascending=False)

    weekly_cache = weekly[weekly['pa_no'].isin(hfb_perf.index)].drop_duplicates(subset=['pa_no'])
    rolling_cache = rolling[rolling['pa_no'].isin(hfb_perf.index)].drop_duplicates(subset=['pa_no'])

    contribution_sum = 0.0
    for pa in hfb_perf.index[:limit]:
        contribution = hfb_perf.loc[pa, 'contribution']
        if contribution_sum >= contribution_threshold:
            break

        pa_rows = weekly_cache[weekly_cache['pa_no'] == pa]
        if pa_rows.empty:
            continue
        pa_perf = pa_rows.iloc[0]
        pa_rolling = rolling_cache[rolling_cache['pa_no'] == pa]
        rolling_perf = pa_rolling.iloc[0] if not pa_rolling.empty else None

        metric_name = f'{base_metric}_ind_ly'
        pa_val = float(pa_perf.get(metric_name, float('nan')))
        rolling_val = (float(rolling_perf[metric_name])
                       if rolling_perf is not None and metric_name in rolling_perf else float('nan'))

        result = f"{base_metric.capitalize()} ind.LY: {pa_val:.0f}"
        if not pd.isna(rolling_val):
            result += f" ({pa_val - rolling_val:+.0f} vs. {rolling_nWKs}WKs)"

        excl_val = float(pa_perf.get(f'{base_metric}_exc_ind_ly', 0.0))
        result += f"；排除News和UTG后，{base_metric.capitalize()} ind.LY: {excl_val:.0f}"

        exc_dif = float(pa_perf.get(focus_exc_dif, float('nan')))
        if not pd.isna(exc_dif):
            trend = '上升' if exc_dif >= 0 else '下降'
            amount_type = '金额' if 'sales' in base_metric else '数量'
            result += f"，{trend}{amount_type}: {int(abs(exc_dif) / 1000):,}K"

        if focus_offline_exc_dif in pa_perf:
            off_dif = float(pa_perf.get(focus_offline_exc_dif, float('nan')))
            if not pd.isna(off_dif):
                off_trend = '上升' if off_dif >= 0 else '下降'
                amount_type = '金额' if 'sales' in base_metric else '数量'
                result += f"，线下{off_trend}{amount_type}: {int(abs(off_dif) / 1000):,}K"

        results[pa] = result
        contribution_sum += contribution

    return results


# ---------------------------------------------------------------------------
# Family level
# ---------------------------------------------------------------------------

def family_for_human(pre, hfb, pa, focus, rolling_nWKs, desc=True, limit=5, contribution_threshold=0.7):
    results = {}
    base_metric = focus.replace('_exc', '')
    focus_dif = f'{base_metric}_dif'

    weekly_df = pre[(pre['hfb_no'] == hfb) & (pre['date_type'] == 'Weekly') &
                    (pre['item_id'] == 'TOTAL') & (pre['pa_no'] == pa) &
                    (pre['item_family'] != 'TOTAL')].copy()
    rolling_df = pre[(pre['hfb_no'] == hfb) & (pre['date_type'] == 'Rolling 4wks') &
                     (pre['item_id'] == 'TOTAL') & (pre['pa_no'] == pa) &
                     (pre['item_family'] != 'TOTAL')].copy()

    if focus_dif not in weekly_df.columns:
        return results

    condition = weekly_df[focus_dif] < 0 if desc else weekly_df[focus_dif] > 0
    filtered = weekly_df[condition].copy()
    if filtered.empty:
        return results

    total_change = filtered[focus_dif].abs().sum()
    filtered['contribution'] = filtered[focus_dif].abs() / total_change if total_change != 0 else 0.0
    filtered = filtered.sort_values('contribution', ascending=False)

    contribution_sum = 0.0
    for _, row in filtered.iterrows():
        if contribution_sum >= contribution_threshold or len(results) >= limit:
            break
        contribution_sum += float(row['contribution'])

        item_family = row['item_family']
        rolling_row = rolling_df[rolling_df['item_family'] == item_family]
        rolling_perf = rolling_row.iloc[0] if not rolling_row.empty else None

        metric_name = f'{base_metric}_ind_ly'
        current_val = row.get(metric_name, 0)
        base_result = f"{base_metric.capitalize()} ind.LY: {int(round(current_val, 0))}"
        if rolling_perf is not None and metric_name in rolling_perf:
            base_result += f" ({current_val - rolling_perf[metric_name]:+.0f} vs. {rolling_nWKs}WKs)"

        excl_val = row.get(f'{base_metric}_exc_ind_ly')
        if excl_val is not None:
            base_result += f"；排除News和UTG后，{base_metric.capitalize()} ind.LY: {int(round(excl_val, 0))}"

        total_dif_val = row[focus_dif]
        trend = '上升' if total_dif_val >= 0 else '下降'
        amount_type = '金额' if 'sales' in base_metric else '数量'
        base_result += f"，{trend}{amount_type}: {int(abs(total_dif_val) / 1000)}K"

        off_val = row.get(f'{base_metric}_offline_exc_dif')
        if off_val is not None:
            off_trend = '上升' if off_val >= 0 else '下降'
            base_result += f" (线下{off_trend}{amount_type}: {int(abs(off_val) / 1000)}K)"

        results[item_family] = base_result

    return results


# ---------------------------------------------------------------------------
# Article level
# ---------------------------------------------------------------------------

def article_for_human(pre, hfb, pa, family, focus, rolling_nWKs, desc=True, limit=1, contribution_threshold=1):
    results = {}
    base_metric = 'sales' if 'sales' in focus.lower() else 'qty'
    focus_dif = f"{base_metric}_dif"
    ind_ly_col = f"{base_metric}_ind_ly"

    weekly_df = pre[(pre['hfb_no'] == hfb) & (pre['pa_no'] == pa) &
                    (pre['item_family'] == family) & (pre['date_type'] == 'Weekly') &
                    (pre['item_id'] != 'TOTAL')].copy()
    rolling_df = pre[(pre['hfb_no'] == hfb) & (pre['pa_no'] == pa) &
                     (pre['item_family'] == family) & (pre['date_type'] == 'Rolling 4wks') &
                     (pre['item_id'] != 'TOTAL')].copy()

    target = weekly_df[weekly_df[focus_dif] < 0] if desc else weekly_df[weekly_df[focus_dif] > 0]
    target = target.copy()
    total_dif = target[focus_dif].sum()
    target['contribution'] = (target[focus_dif].abs() / abs(total_dif)).fillna(0.0) if total_dif != 0 else 0.0
    target = target.sort_values('contribution', ascending=False)

    contribution_sum = 0.0
    for _, article in target.iterrows():
        if len(results) >= limit or contribution_sum >= contribution_threshold:
            break
        item_id = article['item_id']
        label = article.get('product_label_ty', article.get('item_name', item_id))

        rolling_subset = rolling_df[rolling_df['item_id'] == item_id]
        rolling_perf = rolling_subset.iloc[0] if not rolling_subset.empty else None
        metrics = {ind_ly_col: [[f"{rolling_nWKs}WKs"], '%']}
        metric_str = display_metrics(metrics, article, rolling_perf,
                                     name_mapping={ind_ly_col: f"{base_metric.capitalize()} ind.LY"})

        results[item_id] = (label, metric_str, article.get('pic_url', ''))
        contribution_sum += float(article['contribution'])

    return results


# ---------------------------------------------------------------------------
# 潜力识别（规则引擎，原样迁移）
# ---------------------------------------------------------------------------

def potential_recognition(df_final, hfb, pa, family, item, focus, desc=True):
    article_data = df_final[(df_final['date_type'] == 'Weekly') & (df_final['pa_no'] == pa) &
                            (df_final['item_family'] == family) & (df_final['item_id'] == item) &
                            (df_final['hfb_no'] == hfb)]
    rolling_data = df_final[(df_final['date_type'] == 'Rolling 4wks') & (df_final['item_id'] == item) &
                            (df_final['hfb_no'] == hfb) & (df_final['item_family'] == family)]
    if article_data.empty or rolling_data.empty:
        return None, []

    article_perf = article_data.iloc[0]
    rolling_perf = rolling_data.iloc[0]

    base_metric = focus.replace('_exc', '')
    ind_col = f'{base_metric}_ind_ly'

    if desc:
        if rolling_perf['available_percent'] == 0:
            return False, ["连续4周缺货"]
        if article_perf['available_percent'] < 50:
            return True, ["临时性缺货"]
        if article_perf['qty_1k_cus_ind_ly'] > 100:
            return False, [f"Qty / 1k Cus ind.LY: {article_perf['qty_1k_cus_ind_ly']:.0f}"]
        reasons = []
        if rolling_perf[ind_col] - article_perf[ind_col] >= 50:
            reasons.append("环比趋势显著向下")
        return (len(reasons) > 0), reasons
    else:
        if article_perf['qty_1k_cus_ind_ly'] < 100:
            return False, [f"Qty / 1k Cus ind.LY: {article_perf['qty_1k_cus_ind_ly']:.0f}"]
        reasons = []
        if article_perf[ind_col] - rolling_perf[ind_col] >= 50:
            reasons.append("环比趋势显著向上")
        return (len(reasons) > 0), reasons


# ---------------------------------------------------------------------------
# 异动分析主流程
# ---------------------------------------------------------------------------

def anomaly_analysis(pre, pa_pred, article_pred, hfb, focus, rolling_nWKs=4,
                     desc=True, use_ml=True):
    """返回 (HTML 片段, top_pa 上下文)。"""
    result = ""
    top_pa_ctx = {"top_pa": None, "top_pa_direction": "变化"}
    top_pa_abs_dif = -1.0

    for current_desc in [desc, not desc]:
        trend = "下降" if current_desc else "上升"
        result += (f"<div class='section-divider'>{focus.capitalize()}{trend} Top 商品</div>\n")

        pa_results = pa_for_human(pre, hfb, focus, rolling_nWKs, current_desc)
        if not pa_results:
            result += f"<div style='margin-left: 10px;'>- 所选范围内，没有 PA {focus} 同比{trend}。</div>\n"
            continue

        # ML：PA 级归因 + 预测（一次性批量计算，避免重复训练）
        pa_ids = list(pa_results.keys())
        if use_ml:
            pa_top3 = ml_insights.top3_features(pa_pred, 'pa_no', pa_ids)
            pa_forecast = ml_insights.forecast_next_week(pa_pred, 'pa_no', pa_ids)
        else:
            pa_top3, pa_forecast = {}, {}

        # 追踪全报告贡献最大的 PA（供业绩总结引用）
        base_metric = focus.replace('_exc', '')
        dif_col = f'{base_metric}_dif'
        pa_weekly = pre[(pre['date_type'] == 'Weekly') & (pre['hfb_no'] == hfb) &
                        (pre['item_family'] == 'TOTAL') & (pre['item_id'] == 'TOTAL') &
                        (pre['pa_no'].isin(pa_ids))]
        for _, row in pa_weekly.iterrows():
            if abs(row[dif_col]) > top_pa_abs_dif:
                top_pa_abs_dif = abs(row[dif_col])
                top_pa_ctx = {"top_pa": row['pa_no'],
                              "top_pa_direction": "下滑" if row[dif_col] < 0 else "提升"}

        for pa, pa_perf_text in pa_results.items():
            result += f"<div style='margin-top: 10px;'><strong>◆ PA {pa}</strong></div>"
            result += f"<div style='margin-left: 20px;'>{pa_perf_text}</div>"
            if pa in pa_top3:
                result += f"<div style='margin-left: 20px;'>{pa_top3[pa]}</div>"
            if pa in pa_forecast:
                result += (f"<div style='margin-left: 20px;'>预测该 PA 下一周的 "
                           f"{base_metric.capitalize()} 约为 {pa_forecast[pa]:,.0f}</div>")

            family_results = family_for_human(pre, hfb, pa, focus, rolling_nWKs, current_desc)
            for family, family_text in family_results.items():
                result += (f"<div style='margin-left: 40px; margin-top: 8px;'>"
                           f"<strong>▸ Family {family}</strong>：{family_text}</div>")

                article_results = article_for_human(pre, hfb, pa, family, focus,
                                                    rolling_nWKs, current_desc)
                if not article_results:
                    continue

                if use_ml:
                    art_top3 = ml_insights.top3_features(
                        article_pred, 'item_id', list(article_results.keys()))
                else:
                    art_top3 = {}

                for item_id, (label, metric_str, pic_url) in article_results.items():
                    potential, reasons = potential_recognition(
                        pre, hfb, pa, family, item_id, focus, current_desc)
                    if potential:
                        potential_html = (f"<span class='potential-high'>潜力【高】"
                                          f"：{'、'.join(reasons)}</span>")
                    elif reasons:
                        potential_html = (f"<span class='potential-low'>潜力【低】"
                                          f"：{'、'.join(reasons)}</span>")
                    else:
                        potential_html = ""

                    result += (f"<div style='margin-left: 60px; margin-top: 6px;'>"
                               f"<strong>• {item_id}（{label}）</strong></div>")
                    result += f"<div style='margin-left: 80px;'>{metric_str}</div>"
                    if potential_html:
                        result += f"<div style='margin-left: 80px;'>{potential_html}</div>"
                    if item_id in art_top3:
                        result += f"<div style='margin-left: 80px;'>{art_top3[item_id]}</div>"
                    if pic_url and pic_url.strip():
                        result += (f"<div style='margin-left: 80px;'>"
                                   f"<img src='{pic_url}' style='max-width: 300px; "
                                   f"max-height: 200px; margin: 8px 0; border-radius: 8px;'></div>")
                    result += "<br>"

    return result, top_pa_ctx
