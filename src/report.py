# -*- coding: utf-8 -*-
"""
报告装配层
==========
把四个分析模块（业绩总结 / 渠道分析 / DTC-RCMP 销售分析 / 异动商品归因）
装配为一份完整 HTML 报告，对应 notebook 的 main_report / generate_report。
Markdown 转 HTML 沿用 markdown2（与 notebook 一致）。
"""

import markdown2

from . import llm
from .analysis_channel import channel_analysis
from .analysis_funnel import online_analysis
from .analysis_drilldown import anomaly_analysis

CSS = """
<style>
  body { font-family: 'Helvetica Neue', 'PingFang SC', 'Microsoft YaHei', Arial, sans-serif;
         color: #222; max-width: 900px; margin: 0 auto; padding: 24px; line-height: 1.65; }
  h2 { font-size: 22px; margin: 8px 0 4px; }
  h3 { font-size: 17px; margin-top: 28px; border-left: 4px solid #0058a3; padding-left: 10px; }
  ul { margin: 6px 0; }
  li { margin: 3px 0; }
  .report-header { background: linear-gradient(120deg, #0058a3, #0a6ed1);
                   color: #fff; padding: 28px 24px; border-radius: 10px; margin-bottom: 8px; }
  .report-header h1 { margin: 0; font-size: 26px; }
  .report-header .subtitle { opacity: .85; margin-top: 6px; font-size: 14px; }
  .ai-note { color: #999; font-size: 12px; margin: 6px 0 18px; }
  .report-meta { color: #667085; font-size: 12px; margin: 4px 0 18px; }
  .mode-badge { display: inline-block; font-size: 12px; padding: 2px 10px; border-radius: 10px;
                background: #fff3cd; color: #8a6d00; margin-left: 8px; }
  .section-divider { text-align: center; font-weight: bold; font-size: 17px;
                     border-bottom: 2px solid #333; margin: 24px 0 12px; padding-bottom: 4px; }
  .potential-high { color: #1a7f37; font-weight: 600; }
  .potential-low { color: #c0392b; }
  .sales-tree { display: flex; gap: 14px; align-items: stretch; justify-content: center;
                margin: 18px 0 6px; flex-direction: row-reverse; }
  .tree-col { display: flex; flex-direction: column; gap: 8px; justify-content: center; }
  .tree-node { border: 1px solid #d0d7de; border-radius: 8px; padding: 6px 10px;
               text-align: center; background: #f8fafc; min-width: 92px; }
  .tree-node.root { background: #0058a3; }
  .tree-node.root .tree-label, .tree-node.root .tree-value { color: #fff !important; }
  .tree-label { font-size: 12px; color: #555; }
  .tree-value { font-size: 13px; font-weight: 700; }
  .tree-caption { text-align: center; color: #999; font-size: 12px; margin-bottom: 10px; }
</style>
"""


def parse_hfb_input(input_str, max_hfb=95):
    """解析 HFB 输入（迁移自 notebook），支持 "1-5,10" 形式。"""
    hfb_numbers = set()
    parts = [p for p in input_str.replace(' ', '').split(',') if p]
    for part in parts:
        if '-' in part:
            start, end = map(int, part.split('-'))
            if start > end:
                start, end = end, start
            hfb_numbers.update(range(start, end + 1))
        else:
            hfb_numbers.add(int(part))
    invalid = [num for num in hfb_numbers if not 1 <= num <= max_hfb]
    if invalid:
        raise ValueError(f"编号需在 1-{max_hfb} 之间，无效值: {invalid}")
    return sorted(hfb_numbers)


def build_report(
    data,
    hfb,
    week_info,
    focus='sales',
    use_llm=True,
    use_ml=True,
    store='401',
    llm_config=None,
):
    """生成单个 HFB 的完整 HTML 报告。"""
    metadata = getattr(data, "metadata", {})
    if hasattr(data, "as_dict"):
        data = data.as_dict()
    config = llm_config or llm.load_environment_config()
    if not use_llm:
        config = llm.LLMConfig(provider="template")
    llm_events = []

    # 1. 渠道分析
    channel_html, channel_raw = channel_analysis(
        data['channel'],
        hfb,
        use_llm=use_llm,
        llm_config=config,
        llm_events=llm_events,
    )
    # 2. DTC-RCMP 销售分析
    online_html, online_raw = online_analysis(
        data['funnel'],
        hfb,
        use_llm=use_llm,
        llm_config=config,
        llm_events=llm_events,
    )
    # 3. 异动商品归因
    anomaly_html, top_pa_ctx = anomaly_analysis(
        data['drilldown'], data['pa_pred'], data['article_pred'],
        hfb, focus, rolling_nWKs=4, desc=True, use_ml=use_ml)

    # 4. 业绩总结（最后生成、放在最前，输入为完整报告正文——与 notebook 一致）
    summary_raw = {"channel": channel_raw, "online": online_raw, **top_pa_ctx}
    summary_text = llm.report_summary(
        channel_html + "\n" + online_html + "\n" + anomaly_html,
        summary_raw,
        use_llm=use_llm,
        llm_config=config,
        events=llm_events,
    )
    summary_html = f"### <span style='color: #0058a3;'>业绩总结</span>\n{summary_text}"

    if any(event.status == "error" for event in llm_events):
        mode_label = "LLM 调用失败，已降级离线模板"
    elif any(event.status == "success" for event in llm_events):
        mode_label = f"{config.provider} · {config.model}"
    else:
        mode_label = "离线模板"
    mode_badge = f"<span class='mode-badge'>{mode_label}</span>"
    as_of_date = metadata.get("as_of_date", "2025-07-06")
    source_label = (
        "确定性仿真数据"
        if metadata.get("source") == "deterministic_mock"
        else metadata.get("source", "仿真数据")
    )
    header = f"""<div class='report-header'>
  <h1>智能业绩诊断报告{mode_badge}</h1>
  <div class='subtitle'>Store {store} · Online · HFB {hfb} · wk{week_info}</div>
</div>
<div class='report-meta'>数据来源：{source_label} · 数据锚点：{as_of_date} ·
门店与周次为演示参数</div>
<span class='ai-note'>*文字说明由所示模型或离线模板生成；所有数字由代码计算。</span><br><br>\n\n"""

    body = header + summary_html + "<br><br>\n\n" + channel_html + "<br><br>\n\n" \
        + online_html + "<br><br>\n\n" + anomaly_html

    html_body = markdown2.markdown(body, extras=["tables"])
    return f"<html><head><meta charset='utf-8'>{CSS}</head><body>{html_body}</body></html>"
