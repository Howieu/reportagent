# -*- coding: utf-8 -*-
"""
智能业绩诊断 Agent — 产品 Demo（Streamlit）
============================================
运行：streamlit run app.py

Key 安全约定：API Key 仅保存在当前浏览器会话（st.session_state）内，
不写入文件、环境变量、日志、URL 或报告；Key 会发送到 Streamlit 服务端，
建议使用低额度、可撤销的专用 Key。
"""

import streamlit as st

from src import report
from src.data_provider import MockDataProvider, ReportRequest
from src.llm import LLMConfig
from src.report import parse_hfb_input

st.set_page_config(page_title="智能业绩诊断 Agent", page_icon="📊", layout="wide")

PROVIDER_LABELS = {
    "template": "离线模板（无需 Key，推荐演示）",
    "openai_compatible": "OpenAI 兼容服务（OpenAI / DeepSeek / vLLM 等）",
    "anthropic": "Anthropic（Claude）",
}

# ---------------------------------------------------------------------------
# 数据加载（确定性 Mock，公开 Demo 唯一启用的数据源）
# ---------------------------------------------------------------------------

@st.cache_resource
def load_data():
    request = ReportRequest(
        store_id="401",
        hfb_ids=tuple(f"{i:02d}" for i in range(1, 11)),
        week_info="202527",
        focus="sales",
    )
    return MockDataProvider().load(request)


@st.cache_data(show_spinner=False)
def cached_report(store, hfb, week_info, focus, use_ml,
                  provider, model, base_url, api_key):
    """按参数缓存报告 HTML；Key 仅参与缓存键哈希，不写入缓存内容与报告。"""
    config = LLMConfig(
        provider=provider,
        api_key=api_key,
        model=model,
        base_url=base_url,
    )
    return report.build_report(
        load_data(), hfb=hfb, week_info=week_info, focus=focus,
        use_llm=True, use_ml=use_ml, store=store, llm_config=config)


data = load_data()

# ---------------------------------------------------------------------------
# 顶部产品叙事区
# ---------------------------------------------------------------------------

st.title("📊 智能业绩诊断 Agent")
st.caption("把门店商业团队 **4 小时** 的周报工作压缩到 **1 分钟** —— "
           "数仓统一口径 · 规则+LLM 双引擎 · ML 归因与预测 · 数字全部由代码计算，LLM 只做表达")

tab_report, tab_about = st.tabs(["📈 生成业绩报告", "💡 产品说明"])

# ---------------------------------------------------------------------------
# 侧边栏控制区
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("报告配置")
    store = st.selectbox("门店", ["401", "402", "403"], index=0)
    st.caption("仿真数据无门店级差异，门店选择仅影响报告标题展示，不改变分析结果。")
    hfb_input = st.text_input("HFB 编号（支持 1-3,7 形式）", value="1")
    week_info = st.text_input("周次", value="202527")
    focus = st.selectbox("分析指标", ["sales", "qty"], index=0,
                         format_func=lambda x: "Sales（销售金额）" if x == "sales" else "Qty（销售数量）")

    st.divider()
    st.header("文本生成方式")
    provider = st.selectbox(
        "文本生成方式",
        list(PROVIDER_LABELS),
        index=0,
        format_func=lambda x: PROVIDER_LABELS[x],
    )
    if provider == "template":
        st.info("当前为**离线演示模式**：无需 API Key，结论文字由内置规则模板生成，"
                "数值与结构同在线模式完全一致。", icon="ℹ️")
    else:
        st.warning("API Key 会发送到 **Streamlit 服务端** 再转发给模型服务商；"
                   "Key 仅保存在当前浏览器会话内，不会写入文件、日志、URL 或报告。"
                   "建议使用**低额度、可撤销**的专用 Key。", icon="⚠️")
        st.text_input("API Key", type="password", key="llm_api_key")
        if provider == "openai_compatible":
            st.text_input("Base URL", value="https://api.openai.com/v1", key="llm_base_url")
        else:
            st.session_state.setdefault("llm_base_url", "https://api.openai.com/v1")
        model = st.text_input(
            "模型", key="llm_model",
            placeholder="gpt-4o-mini" if provider == "openai_compatible" else "claude-haiku-4-5")
        if not st.session_state.get("llm_api_key") or not model:
            st.caption("Key 或模型名为空时将自动降级为离线模板。")

    use_ml = st.toggle("启用 ML 归因 / 预测", value=False,
                       help="LightGBM+SHAP 特征归因与 7 天销量预测；关闭可加速生成")

    generate = st.button("🚀 生成报告", type="primary", use_container_width=True)

# ---------------------------------------------------------------------------
# 主报告区
# ---------------------------------------------------------------------------

with tab_report:
    if not generate:
        st.markdown("""
        👈 在左侧选择 **门店 / HFB / 周次**，点击 **生成报告**。

        报告包含四个部分，与线下真实周报同构：
        1. **业绩总结** —— 4 点式执行摘要（LLM 生成，few-shot 格式约束）
        2. **渠道分析** —— ONLINE / OFFLINE / 二级渠道表现
        3. **DTC-RCMP 销售分析** —— KPI + Sales Tree 漏斗下钻
        4. **异动商品归因** —— PA → Family → Article 三级下钻，附 ML 归因、销量预测与潜力商品标记

        > 📌 本 Demo 使用确定性仿真数据（时间锚点 2025-07-06，仿真门店），不含任何真实经营数据。
        """)
    else:
        try:
            hfb_list = parse_hfb_input(hfb_input, max_hfb=10)
        except (ValueError, TypeError) as e:
            st.error(f"HFB 输入有误：{e}（Demo 数据范围为 1-10）")
            st.stop()

        model = st.session_state.get("llm_model", "")
        api_key = st.session_state.get("llm_api_key", "")
        base_url = st.session_state.get("llm_base_url", "https://api.openai.com/v1")
        if provider == "template" or not api_key or not model:
            provider = "template"
            api_key = ""

        for num in hfb_list:
            hfb = f"{num:02d}"
            with st.status(f"正在生成 HFB {hfb} 报告…", expanded=len(hfb_list) == 1) as status:
                st.write("① 加载确定性 mock 数仓表（5 张预聚合表）")
                st.write("② 指标文本化（for_human / for_llm 双轨）")
                st.write("③ 渠道分析 + Sales Tree 漏斗")
                if use_ml:
                    st.write("④ ML 归因（LightGBM+SHAP）与 7 天销量预测")
                st.write("⑤ 业绩总结 + 报告装配")
                html = cached_report(store, hfb, week_info, focus, use_ml,
                                     provider, model, base_url, api_key)
                status.update(label=f"HFB {hfb} 报告生成完成", state="complete")

            # 注：st.iframe 仅支持 URL；渲染 srcdoc 需用 components.v1.html（有弃用警告，无碍功能）
            st.components.v1.html(html, height=1400, scrolling=True)
            st.download_button(
                f"⬇️ 下载 HFB {hfb} HTML 报告",
                data=html, file_name=f"wk{week_info}_Online_{hfb}.html",
                mime="text/html", key=f"dl_{hfb}")
            st.divider()

# ---------------------------------------------------------------------------
# 产品说明页（面试叙事材料）
# ---------------------------------------------------------------------------

with tab_about:
    st.markdown("""
### 背景与痛点
门店商业团队每周需要对每个 HFB（高层级商品分类）做业绩复盘：跨 ONLINE/OFFLINE 多渠道、
跨 HFB→PA→Family→Article 四个层级、读数十个指标（ind.Goal / ind.LY / Conv. Rate …），
再人工归因、写结论。**单份周报耗时约 4 小时，且不同分析师口径不一。**

### 方案：五层诊断流水线

```
┌─────────────────────────────────────────────────────────┐
│ ① 数仓层   5 张预聚合周表统一指标口径（ind.LY / Rolling 4wks）│
│ ② 文本化层  for_human / for_llm 双轨：数字只由代码计算       │
│ ③ 分析层   规则引擎 + LLM（业务词典 prompt + 两段式总结）     │
│ ④ ML 层    SHAP 归因 · 7 天销量预测 · 潜力商品规则识别        │
│ ⑤ 渲染层   报告装配 → HTML/PDF → 推送                        │
└─────────────────────────────────────────────────────────┘
```

### 核心设计决策（为什么不只是"调 LLM 写报告"）

| 设计 | 解决的问题 |
|---|---|
| **数字全部由代码计算**（`display_metrics` 统一格式化），LLM 只负责语言组织 | 从架构上杜绝 LLM 算错数的幻觉 |
| **for_human / for_llm 双轨** | 同一份数据分别渲染人读明细与模型输入，互不污染 |
| **业务术语词典 prompt**（ind.LY / PIP / Conv. Rate …） | LLM 不需要猜指标口径，结论可复现 |
| **两段式对话**：先完整分析、再压缩为 ≤100 字总结 | 兼顾分析深度与报告可读性 |
| **few-shot 输出格式约束**（Output Format + Output Example） | 业绩总结结构稳定，可直接排版 |
| **负向业务约束**（门店无定价权，禁止"优化定价"建议） | 结论符合业务常识，不误导一线 |
| **规则引擎兜底**（潜力识别 / 离线模板） | 无网无 Key 可演示；LLM 故障时服务不中断 |
| **"报告中的文字说明由AI生成"标注** | 风险披露，明确人机责任边界 |

### 效果与价值
- 单份周报：**4 小时 → 约 1 分钟**；支持 `1-5,10` 式批量生成；
- 规模化账：N 个 HFB × M 家门店 × 每周 1 次，全年释放分析师人力约 **N×M×4h×52**；
- 报告不止陈述，直接指导行动：归因 Top3 特征、下周预测、潜力商品（附图）→ 补货 / 推广 / 陈列。

### 产品化路线图
1. **配置化**：HFB / 周次已参数化（本 Demo 已实现）；潜力识别阈值目前为规则引擎内置常量，
   UI 暴露为可调参数是下一步路线图项；
2. **IM 推送**：飞书/企微定时推送 PDF，触达一线店长；
3. **追问式分析**：在报告上直接对话追问（"为什么 PA 013 上升？"）；
4. **评估体系**：结论准确率抽检 + 业务采纳率回流，持续迭代 prompt 与规则阈值。

---
*本 Demo 所有数据均为确定性仿真数据（时间锚点 2025-07-06，仿真门店）；原始系统运行于企业数仓（MaxCompute）之上。*
""")
