# -*- coding: utf-8 -*-
"""
渠道分析（迁移自 notebook）
===========================
保留 for_human / for_llm 双轨制：同一份数据渲染成给人看的 HTML 明细
和给 LLM 看的纯文本输入。返回 (HTML 片段, raw 数值上下文)。
"""

from .metrics import display_metrics
from . import llm

_NAME_MAPPING_L1 = {
    'sales_ind_goal': 'Sales ind.Goal',
    'sales_ind_ly': 'Sales ind.LY',
    'qty_ind_ly': 'Qty ind.LY',
}

_NAME_MAPPING_L2 = {
    'sales_share': 'Sales Share',
    'sales_ind_goal': 'Sales ind.Goal',
    'sales_ind_ly': 'Sales ind.LY',
    'qty_ind_ly': 'Qty ind.LY',
}


def _weekly_row(df1, hfb, channel):
    rows = df1[(df1['hfb_no'] == hfb) &
               (df1['sales_channel'] == channel) &
               (df1['date_type'] == 'Weekly')]
    return rows.iloc[0] if not rows.empty else None


def channel_online_l1_for_human(df1, hfb):
    hfb_perf = _weekly_row(df1, hfb, 'ONLINE')
    rolling = df1[(df1['hfb_no'] == hfb) &
                  (df1['sales_channel'] == 'ONLINE') &
                  (df1['date_type'] == 'Rolling 4wks')]
    rolling_perf = rolling.iloc[0] if not rolling.empty else None

    metrics = {
        'sales_ind_goal': [[], '%', None],
        'sales_ind_ly': [['4WKs'], '%', 'ind.LY'],
        'qty_ind_ly': [[], '%', 'ind.LY'],
    }
    return {'ONLINE': display_metrics(metrics, hfb_perf, rolling_perf, name_mapping=_NAME_MAPPING_L1)}


def channel_offline_l1_for_human(df1, hfb):
    hfb_perf = _weekly_row(df1, hfb, 'OFFLINE')
    metrics = {
        'sales_ind_goal': [[], '%', None],
        'sales_ind_ly': [[], '%', 'ind.LY'],
        'qty_ind_ly': [[], '%', 'ind.LY'],
    }
    return {'OFFLINE': display_metrics(metrics, hfb_perf, name_mapping=_NAME_MAPPING_L1)}


def channel_l1_for_llm(df1, hfb):
    results = {}
    for channel in ['OFFLINE', 'ONLINE']:
        hfb_perf = _weekly_row(df1, hfb, channel)
        metrics = {
            'sales_ind_goal': [[], '%', None],
            'sales_ind_ly': [[], '%', 'ind.LY'],
        }
        results[channel] = display_metrics(metrics, hfb_perf, name_mapping=_NAME_MAPPING_L1)
    return results


def channel_l2_for_human(df1, hfb):
    results = {}
    for channel in ['DTC', 'RCMP', 'TMALL']:
        hfb_perf = _weekly_row(df1, hfb, channel)
        metrics = {
            'sales_share': [[], '1%'],
            'sales_ind_goal': [[], '%', None],
            'sales_ind_ly': [[], '%', 'ind.LY'],
            'qty_ind_ly': [[], '%', 'ind.LY'],
        }
        results[channel] = display_metrics(metrics, hfb_perf, name_mapping=_NAME_MAPPING_L2).replace(', ', '，')
    return results


def channel_l2_for_llm(df1, hfb):
    results = {}
    for channel in ['DTC', 'RCMP', 'TMALL']:
        hfb_perf = _weekly_row(df1, hfb, channel)
        metrics = {
            'sales_share': [[], '1%'],
            'sales_ind_goal': [[], '%', None],
            'sales_ind_ly': [[], '%', 'ind.LY'],
        }
        results[channel] = display_metrics(metrics, hfb_perf, name_mapping=_NAME_MAPPING_L2).replace(', ', '，')
    return results


def channel_analysis(
    df1,
    hfb,
    use_llm=True,
    *,
    llm_config=None,
    llm_events=None,
):
    """渠道分析模块入口，返回 (HTML 片段, raw 数值上下文)。"""
    outputs_l1_llm = channel_l1_for_llm(df1, hfb)
    outputs_l2_llm = channel_l2_for_llm(df1, hfb)
    out_online = channel_online_l1_for_human(df1, hfb)
    out_offline = channel_offline_l1_for_human(df1, hfb)
    out_l2 = channel_l2_for_human(df1, hfb)

    # 供离线模板 / 业绩总结使用的原始数值
    raw = {"ONLINE": {}, "OFFLINE": {}, "L2": {}}
    for channel in ["ONLINE", "OFFLINE"]:
        row = _weekly_row(df1, hfb, channel)
        raw[channel] = {"sales_ind_goal": float(row["sales_ind_goal"]),
                        "sales_ind_ly": float(row["sales_ind_ly"])}
    for channel in ["DTC", "RCMP", "TMALL"]:
        row = _weekly_row(df1, hfb, channel)
        raw["L2"][channel] = float(row["sales_ind_ly"])

    summary = llm.channel_summary(
        outputs_l1_llm,
        outputs_l2_llm,
        raw,
        use_llm=use_llm,
        llm_config=llm_config,
        events=llm_events,
    )

    html = f"""### <span style='color: #0058a3;'>渠道分析</span>
{summary}<br>

- **ONLINE**: <u>**{out_online['ONLINE']}**</u>
  - **DTC**: {out_l2['DTC']}
  - **RCMP**: {out_l2['RCMP']}
  - **TMALL**: {out_l2['TMALL']}
- **OFFLINE**: <u>**{out_offline['OFFLINE']}**</u>
"""
    return html, raw
