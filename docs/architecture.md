# 智能业绩诊断 Agent — 分析流程架构

五层诊断流水线的完整数据流与降级路径（与 `src/` 代码一一对应）。

```mermaid
flowchart TB
    UI["用户输入：门店 / HFB（支持 1-3,7 批量）/ 周次 / 指标<br/>文本生成方式 / ML 开关（Streamlit 侧边栏）"]

    subgraph L1["① 数仓层 — 统一指标口径"]
        direction LR
        MDP["MockDataProvider<br/><code>data_provider.py</code>"]
        MOCK["5 张预聚合周表<br/>确定性仿真数据（blake2b 派生种子）<br/><code>mock_data.py</code>"]
        MDP --> MOCK
    end

    METRICS["② 文本化层（数字唯一入口）<br/>display_number / display_metrics · for_human / for_llm 双轨<br/><code>metrics.py</code>"]

    subgraph L3["③ 分析层 — 规则引擎"]
        direction LR
        CH["渠道分析<br/>ONLINE / OFFLINE / 二级渠道<br/><code>analysis_channel.py</code>"]
        FUN["DTC-RCMP 销售分析<br/>KPI + Sales Tree 漏斗（纯 HTML/CSS）<br/><code>analysis_funnel.py</code>"]
        DRILL["异动商品归因<br/>PA → Family → Article 三级下钻<br/>+ 潜力商品规则引擎<br/><code>analysis_drilldown.py</code>"]
    end

    subgraph L4["④ ML 层 — 归因与预测（可开关）"]
        direction LR
        ML["LightGBM + SHAP 特征归因<br/>7 天销量预测<br/><code>ml_insights.py</code>"]
        ML_FB["降级：|Pearson| 相关系数归因<br/>（lightgbm / shap 缺失或训练失败时）"]
        ML -.->|ImportError / 异常| ML_FB
    end

    subgraph LLM["LLM 抽象层 — 三 Provider + 自动降级"]
        direction LR
        PROMPT["业务词典 prompt<br/>few-shot 格式约束 / 负向业务约束<br/>两段式：完整分析 → ≤100 字总结<br/><code>prompts.py</code>"]
        TPL["template<br/>离线规则模板（默认，无需 Key）"]
        OAI["openai_compatible<br/>OpenAI / DeepSeek / vLLM"]
        ANT["anthropic<br/>Claude"]
        TPL_FB["错误分类降级<br/>401 / 429 / 超时 → 规则模板<br/>错误文本不回显 Key"]
        PROMPT --> TPL
        PROMPT --> OAI
        PROMPT --> ANT
        OAI -.->|调用失败| TPL_FB
        ANT -.->|调用失败| TPL_FB
    end

    subgraph L5["⑤ 渲染层 — 报告装配"]
        direction LR
        ASM["build_report：业绩总结置顶<br/>markdown2 → HTML · 标注数据源 / 时间锚点 / 生成模式<br/><code>report.py</code>"]
        OUT["页面内渲染 + 下载 HTML<br/>（生产环境：PDF + IM 推送）"]
        ASM --> OUT
    end

    UI --> MDP
    MOCK --> METRICS
    METRICS --> CH
    METRICS --> FUN
    METRICS --> DRILL
    DRILL -->|"use_ml = True"| ML
    ML --> DRILL
    CH -->|"for_llm 纯文本"| PROMPT
    FUN --> PROMPT
    DRILL --> PROMPT
    TPL -->|"≤100 字业绩总结"| ASM
    TPL_FB --> ASM
    CH -->|"for_human HTML 明细"| ASM
    FUN --> ASM
    DRILL --> ASM

    classDef fallback fill:#fff7e0,stroke:#b45309,color:#1f2933,stroke-dasharray:5 5;
    class ML_FB,TPL_FB fallback;
```

## 读图要点（面试讲解动线）

1. **数字与文字分离**：所有数字只经过 ② `metrics.py` 一个入口，LLM 拿到的 `for_llm`
   文本里的数字也是代码算好后塞进去的——从架构上杜绝 LLM 算错数；
2. **双轨渲染**：③ 分析层每个模块同时产出人读 HTML 明细（`for_human`）和模型输入
   纯文本（`for_llm`），互不污染；
3. **两条降级链**（虚线）：LLM 无 Key / 调用失败 → 离线规则模板；LightGBM/SHAP 缺失
   或训练失败 → 相关系数归因。任意一条触发，报告都能完整产出，演示永不中断；
4. **ML 层可开关**：默认关闭（演示速度），开启后归因文本由
   `ml_insights.top3_features` / `forecast_next_week` 注入 ③ 的下钻结论中。
