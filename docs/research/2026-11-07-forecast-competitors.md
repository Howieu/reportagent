# 预测与经营分析竞品调研（2026-11-07）

只读了公开文档和文章，没有试用这些产品。“未查到”不等于产品没有。

## 竞品现状

| 能力 | Databricks | Google BigQuery | Snowflake | ThoughtSpot | Tableau Pulse | Power BI | ReportAgent（本次之后） |
|---|---|---|---|---|---|---|---|
| Agent 调预测 | Genie 接入中（官方称预测“即将支持”） | 有，工具封装 `AI.FORECAST` | 未查到 | 有，Spotter 用 Python 选模型 | 有，指标页和问答 | 未查到 Copilot 调用；折线图内置预测 | 有 |
| 模型 | 时序基础模型 | TimesFM 预训练模型 | Prophet、ARIMA、指数平滑、GBM 集成 | SARIMA、Holt-Winters 等 | 未查到 | 指数平滑 | LightGBM，赢不过基线就用基线 |
| 未来已知变量 | 有（节假日、外部变量） | 有（TimesFM 3.0 预览） | 有（预测时必须提供） | 未查到 | 未查到 | 未查到 | 有（活动日历配置） |
| 预测区间 | 有 | 有 | 有 | 提到置信区间 | 未查到 | 有 | 有（80%，来自回测误差） |
| 准确率评估 | 官方博客只有基准对比 | `AI.EVALUATE` | MAE、MAPE、区间覆盖率等 | 评估是否有用，可换模型重跑 | 没把握时默认隐藏预测 | 未查到 | WAPE、偏差、留一法区间覆盖率 |
| 解释预测 | 未查到 | 未查到 | 特征重要性（0 到 1） | 报告和建议 | 相关指标 | 未查到 | 单次预测的 SHAP 金额拆解 |
| 异常检测 | `ai_detect_anomalies` | `AI.DETECT_ANOMALIES` | 独立函数 | 未查到 | 有（第三方资料） | 折线图内置 | 有 |
| 涨跌归因 | `ai_top_drivers` | 未查到 | 未查到 | “为什么”类问题 | 问答洞察 | 关键影响因素（视觉对象） | 销售树和商品下钻 |
| 主动体检 | 未查到 | 未查到 | 未查到 | 未查到 | 指标摘要 | 未查到 | 有页面和工具，还没有定时推送 |
| 情景试算 | 未查到 | `AI.CAUSAL_EFFECT`（预览，不是同一能力） | 未查到 | 未查到 | 未查到 | 第三方提到 Fabric 支持 | 有（恒等式算术） |

其他：

- 帆软 FineBI NEXT：第三方测评称有场景 Agent，可按周或月主动体检，并推送异常原因和建议。**这和我们的经营体检方向相近，不能说只有我们有。**
- Blue Yonder、RELEX 是专业需求计划系统，有因果变量、补货和情景规划，定位比 ChatBI 更重，不直接对标。
- Quick BI 小Q 有问数和波动归因，未查到时序预测。

## 我们对齐了什么

1. 异常检测。
2. 活动日历（未来已知变量）。
3. 偏差和区间覆盖率。

## 我们的差异化

差异化不在模型精度，而在把结果变成可核对的业务判断。

1. **经营体检把四步串起来。** 一次得到哪里异常、差多少钱、差在单量还是单件价值和落在哪个子类品牌、下周怎么走。竞品多数把这些做成分开的函数或视图。
2. **每个判断都能核对。** 预期来自没见过这一周的回测预测，并写明来自模型还是基线。
3. **情景试算不假装因果。** 只算恒等式，并给出这个幅度历史上有多常见；也能反推达成目标需要的幅度。

## 实测结果（Olist，起点 2018 年第 33 周，回测 26 周）

| 范围 | 提前 1 周胜率 | 提前 2 周 | 提前 3 周 | 提前 4 周 | 异常触发率（理论约 7.7%） |
|---|---|---|---|---|---|
| 全部（1 个） | 0% | 0% | 0% | 0% | 7.7% |
| 品类（9 个） | 22% | 33% | 22% | 22% | 7.7% |
| 卖家州（19 个） | 47% | 58% | 42% | 42% | 6.1% |
| 州 × 品类（105 个） | 63% | 64% | 62% | 66% | 5.7% |

- **模型只在细粒度上有优势。** 全部和品类层面大多输给基线，所以这些范围会显示基线数字。
- **12 周窗口会误导。** 12 周时全部层面提前 1 周模型赢，26 周时输，所以把回测延长到 26 周。
- **活动日历在 Olist 上没有证明有用。** 公开的巴西零售节点加入后好坏参半，所以线上默认不开。真实促销日历的效果要用客户数据验证。

## 还没做

- 定时体检和消息推送。
- 用客户真实促销数据验证活动日历。
- 和竞品做同一份数据的准确率对比。在此之前不能说“比竞品更准”。

## 来源

- Databricks：[Predictive AI Functions](https://www.databricks.com/blog/unlock-powerful-insights-and-forecasts-predictive-ai-functions)、[ai_forecast](https://docs.databricks.com/sql/language-manual/functions/ai_forecast)
- Google：[AI.FORECAST](https://docs.cloud.google.com/bigquery/docs/reference/standard-sql/bigqueryml-syntax-ai-forecast?authuser=2)、[Agent 工具](https://cloud.google.com/blog/products/data-analytics/ai-based-forecasting-and-analytics-in-bigquery-via-mcp-and-adk)、[发布说明](https://docs.cloud.google.com/bigquery/docs/resources?hl=ja)
- Snowflake：[Time-Series Forecasting](https://docs.snowflake.com/en/user-guide/analysis-forecasting)、[EXPLAIN_FEATURE_IMPORTANCE](https://docs.snowflake.com/sql-reference/classes/forecast/methods/explain_feature_importance)
- ThoughtSpot：[Spotter 高级分析](https://docs.thoughtspot.com/cloud/latest/spotter-advanced-analysis)、[时序预测](https://docs.thoughtspot.com/cloud/latest/spotiq-forecasting)
- Tableau：[About Pulse](https://help.tableau.com/current/online/en-gb/pulse_intro.htm)、[Premium 能力](https://help.tableau.com/release-preview/online/en-us/pulse_capabilities.htm)
- Power BI（第三方）：[预测工作原理](https://www.thebricks.com/resources/guide-how-does-power-bi-forecasting-work)、[AI 功能指南](https://technijian.com/ai/business-intelligence/power-bi-ai-features-in-2026-guide-for-oc-business-intelligence-teams/)、[Protiviti 文章](https://www.protiviti.com/au-en/blogs/next-generation-power-bi-interactivity)
- Amazon：[RCF 预测](https://docs.aws.amazon.com/quicksuite/latest/userguide/how-does-rcf-generate-forecasts.html)
- 国内：[Quick BI 智能小Q](https://help.aliyun.com/zh/quick-bi/user-guide/smartq)、[第三方 BI 测评](https://juejin.cn/post/7665633271010951204)
- 需求计划：[Blue Yonder 与 RELEX 对比](https://www.rfp.wiki/supply-chain-logistics-transportation/supply-chain-planning-solutions/blue-yonder/relex-solutions)
