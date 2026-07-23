# Handoff 交接文档 — 智能业绩诊断 Agent 产品 Demo

> 交接日期：2026-07-22
> 项目状态：**已完成，端到端验证通过**
> 项目路径：`AI-Agent-Outputs/claude/ikea-report-agent-demo/`

---

## 1. 项目背景

| 项 | 内容 |
|---|---|
| 来源 | 用户在 IKEA 实习期间开发的自动化数分周报 notebook（`实习&工作/IKEA实习/自动数分报告生成Agent/Automated PDF Generation.ipynb`） |
| 目标 | 包装为**求职作品集级产品 Demo**，受众为面试官（AI 产品经理·数据方向） |
| 已确认方向 | 交互式 Streamlit Web 应用 + mock 数据离线跑通（剥离 ODPS/Azure 依赖，不含任何真实密钥与经营数据） |
| 业务场景 | 门店商业团队每周对每个 HFB 做业绩复盘，人工约 4 小时/份 → 系统约 1 分钟/份 |

## 2. 快速启动

```bash
cd "AI-Agent-Outputs/claude/ikea-report-agent-demo"
.venv/bin/streamlit run app.py
```

- 浏览器打开后：左侧选门店 / HFB（支持 `1-3,7` 形式）/ 周次 → 点 **生成报告**；
- **离线演示模式**：不配任何 Key 即可完整演示，结论文字由规则模板生成；
- 启用 LLM 润色（可选）：`cp .env.example .env`，填入任意 OpenAI 兼容服务的 `LLM_API_KEY / LLM_BASE_URL / LLM_MODEL`。

⚠️ **环境注意**：系统 anaconda base 环境的 pandas/numpy 已损坏（NumPy 1.x 编译的 pandas 遇 NumPy 2.x）。本项目所有 Python 操作一律使用项目内 `.venv/bin/python`，不要在 base 环境运行。

## 3. 架构与代码地图

五层诊断流水线（与 notebook 一一对应）：

```
数仓层  src/mock_data.py        5 张预聚合表的 mock 生成器（schema 与线上 ODPS 表一致，固定 seed=42）
文本化  src/metrics.py          数字唯一入口 display_number / display_metrics（LLM 不做算术）
分析层  src/analysis_channel.py 渠道分析（ONLINE/OFFLINE/二级渠道，for_human/for_llm 双轨）
        src/analysis_funnel.py  DTC-RCMP 销售分析 + Sales Tree（纯 HTML/CSS，替代 graphviz）
        src/analysis_drilldown.py PA→Family→Article 三级归因 + 潜力识别规则引擎
        src/prompts.py          全部 prompt（业务词典 / 两段式 / few-shot / 负向约束）
        src/llm.py              OpenAI 兼容客户端 + 无 Key 规则模板降级
ML 层   src/ml_insights.py      LightGBM+SHAP 归因（缺失时相关系数兜底）、轻量 7 天预测
渲染层  src/report.py           报告装配（业绩总结置顶，markdown2 → HTML）
入口    app.py                  Streamlit 双 Tab（生成报告 / 产品说明）
```

配套文档：`README.md`（PRD-lite 产品叙事）、`demo_script.md`（3 分钟演示动线 + 问答预案）。

## 4. 关键设计决策（面试叙事核心）

1. **幻觉防控**：报告里每个数字都由代码计算，LLM 只负责语言组织；
2. **双轨渲染**：同一数据分别产出人读明细（HTML）与模型输入（纯文本）；
3. **业务词典 prompt**：ind.LY / PIP / Conv. Rate 等口径内置，禁止"优化定价"等越权建议；
4. **降级设计**：LLM 无 Key/失败 → 规则模板；SHAP 缺失 → 相关系数；演示永不中断；
5. **风险披露**：页面保留"报告中的文字说明由AI生成"标注。

## 5. 与原始 notebook 的差异（有意为之）

| 改动 | 原因 |
|---|---|
| ODPS 取数 → mock 数据生成器 | 剥离内网依赖；字段名完全一致，分析代码零改动 |
| 四模型融合归因 → 单模型 LightGBM+SHAP | 演示速度（完整模式逻辑保留在注释/README 中） |
| Prophet 预测 → 28 天按星期均值外推 | 依赖重、慢；轻量版秒级出结果 |
| graphviz Sales Tree → 纯 HTML/CSS | graphviz 需系统二进制，不可移植 |
| `display_number` ×100 启发式阈值修正 | **修复了原 notebook 的真实 bug**：100 口径下 <10 的差值被误放大（-1.2 → -120） |
| wkhtmltopdf PDF → HTML 报告 + 浏览器打印 | wkhtmltopdf 硬编码 Windows 路径，不可交付 |

## 6. 验证记录（2026-07-22）

- ✅ 离线模式 + ML 全量：HFB 01/05/10 报告五模块（业绩总结/渠道/Sales Tree/异动归因/潜力标签）全部渲染，数值无异常；
- ✅ 关闭 ML 快速模式正常；非法 HFB 输入（99）正确拦截并提示范围；
- ✅ 潜力【高】标签按规则正确触发（临时性缺货 / 环比趋势显著向上）；
- ✅ 全库 grep：无明文密钥、无内网地址、无个人路径残留；
- ✅ Streamlit AppTest 三个场景 headless 回归通过。

## 7. 已知限制

- 单份报告生成约 18 秒（ML 模式），演示前建议预生成一次预热；
- mock 数据为静态快照（时间锚点 2025-07-06），周次选择仅为展示参数；
- `st.components.v1.html` 有弃用警告（st.iframe 仅支持 URL，无法替代 srcdoc 渲染），功能无碍；
- 商品图为 base64 SVG 占位图（离线可用）；接真实环境时换回 `pic_url`。

## 8. 后续路线（如继续迭代）

1. IM 推送：飞书/企微定时推送 PDF（触达一线店长的真实形态）；
2. 追问式分析：报告上对话追问（"为什么 PA 013 上升？"）；
3. 评估闭环：结论准确率抽检 + 业务采纳率回流，迭代 prompt 与规则阈值；
4. 若接回真实数仓：替换 `mock_data.load_all()` 为 ODPS 取数即可，分析层无需改动。
