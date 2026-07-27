# 智能业绩诊断 Agent — 产品 Demo

> 把门店商业团队 **4 小时** 的周报工作压缩到 **1 分钟**。
> 源自真实业务场景的自动化数分报告系统的产品化重构：数仓统一口径 · 规则+LLM 双引擎 · ML 归因与预测。

![Python](https://img.shields.io/badge/Python-3.12-blue) ![Streamlit](https://img.shields.io/badge/Streamlit-App-red) [![test](https://github.com/Howieu/reportagent/actions/workflows/test.yml/badge.svg)](https://github.com/Howieu/reportagent/actions/workflows/test.yml)

## 在线访问

| 入口 | 地址 | 说明 |
|---|---|---|
| **固定域名落地页** | `https://reportagent.vercel.app`（Vercel） | 项目介绍 + 内嵌交互 Demo |
| **Streamlit 直达** | `https://ikea-report-agent.streamlit.app` | 交互应用本体（空闲会休眠，打开后稍等唤醒） |
| **GitHub 源码** | `https://github.com/Howieu/reportagent` | 代码、测试与部署配置 |

> 落地页由 Vercel 从 `site/` 目录自动部署（Root Directory = `site`，无构建步骤），
> push 到 main 即自动发布。Streamlit 应用空闲休眠时，可通过落地页「新窗口打开」唤醒。

## 一分钟了解

- **用户与场景**：零售门店店长 / 商业团队，每周一上午对每个 HFB（高层级商品分类）做业绩复盘。
- **痛点**：跨 ONLINE/OFFLINE 多渠道、跨 HFB→PA→Family→Article 四层级读数十个指标，再人工归因写结论，单份周报约 4 小时，且不同分析师口径不一。
- **方案**：五层诊断流水线，一键生成"业绩总结 + 渠道分析 + Sales Tree 漏斗 + 异动商品归因（含 ML 归因、销量预测、潜力商品标记）"的结构化周报。
- **Demo 亮点**：交互式生成、离线可演示（无 LLM Key 时规则模板兜底）、全部数据为仿真数据。

## 快速开始

```bash
pip install -r requirements.txt
streamlit run app.py
```

跑测试 / lint（需要开发依赖，CI 用同一套）：

```bash
pip install -r requirements-dev.txt
ruff check .
python -m pytest
```

打开浏览器后：左侧选 **门店 / HFB（支持 `1-3,7` 形式）/ 周次** → 点击 **生成报告** → 页面内渲染完整报告，可下载 HTML。

**可选：启用 LLM 润色**（不配置也能完整演示，系统自动降级为规则模板）：

- 方式一：页面侧边栏「文本生成方式」选择 OpenAI 兼容服务或 Anthropic，填入 Key / 模型即可
  （Key 仅保存在当前浏览器会话，不写入文件、日志、URL 或报告）；
- 方式二：`cp .env.example .env`，填入 `LLM_API_KEY / LLM_BASE_URL / LLM_MODEL`。

## 部署架构

```text
reportagent.vercel.app
        │
        ▼
Vercel（site/ 静态落地页，Git 集成自动部署）
  项目背景 / 架构 / 个人贡献 / 隐私说明
        │
        ├── iframe: ikea-report-agent.streamlit.app/?embed=true（懒加载 + 骨架屏）
        └── 新窗口打开 Streamlit（备用入口）
                         │
                         ▼
              Streamlit Cloud（app.py）
              Mock 数据 / 分析 / LLM / HTML 报告
```

- **Streamlit Cloud**：从 `app.py` 部署，固定易读的 `*.streamlit.app` 子域名；
- **Vercel**：Git 集成连接本仓库，Root Directory 设为 `site/`，Framework=None、
  无构建命令，push 到 main 自动发布；免费 `*.vercel.app` 子域名；
- 不使用心跳绕过 Streamlit 休眠机制；若后续要求单一域名 / 持续在线，
  将同一应用 Docker 化部署到 Render / Cloud Run，Vercel 侧绑定自有域名即可保持不变。

## 方案架构：五层诊断流水线

```
┌─────────────────────────────────────────────────────────────┐
│ ① 数仓层    5 张预聚合周表统一指标口径（ind.LY / Rolling 4wks）  │
│             （Demo 中为 src/mock_data.py 生成的仿真数据）         │
│ ② 文本化层  for_human / for_llm 双轨渲染                        │
│             报告里的每个数字都只由代码计算（src/metrics.py）       │
│ ③ 分析层    规则引擎 + LLM 两段式对话                             │
│             业务词典 prompt → 完整分析 → 压缩为 ≤100 字结论        │
│ ④ ML 层     SHAP 归因（影响 Sales 的前三指标）                    │
│             7 天销量预测 · 潜力商品规则识别                        │
│ ⑤ 渲染层    报告装配 → HTML（生产环境为 PDF + IM 推送）           │
└─────────────────────────────────────────────────────────────┘
```

## 核心设计决策（为什么不只是"调 LLM 写报告"）

| 设计 | 解决的问题 |
|---|---|
| **数字全部由代码计算**，LLM 只负责语言组织 | 从架构上杜绝 LLM 算错数的幻觉 |
| **for_human / for_llm 双轨** | 同一份数据分别渲染人读明细与模型输入，互不污染 |
| **业务术语词典 prompt**（ind.LY / PIP / Conv. Rate …） | LLM 不需要猜指标口径，结论可复现 |
| **两段式对话**：先完整分析、再压缩为 ≤100 字总结 | 兼顾分析深度与报告可读性 |
| **few-shot 输出格式约束** | 业绩总结结构稳定，可直接排版 |
| **负向业务约束**（门店无定价权，禁止"优化定价"建议） | 结论符合业务常识，不误导一线 |
| **规则引擎兜底**（潜力识别 / 离线模板） | LLM 故障或无 Key 时服务不中断 |
| **"报告中的文字说明由AI生成"标注** | 风险披露，明确人机责任边界 |

## 目录结构

```
├── app.py                    # Streamlit 入口（报告生成 + 产品说明双 Tab）
├── site/
│   └── index.html            # Cloudflare Pages 落地页（项目介绍 + iframe 嵌入 Demo）
├── src/
│   ├── mock_data.py          # 确定性 mock 数据生成器（blake2b 派生种子，跨进程可复现）
│   ├── data_provider.py      # ReportRequest / ReportData 契约 + MockDataProvider（OdpsDataProvider 占位）
│   ├── metrics.py            # 数字唯一入口：display_number / display_metrics
│   ├── prompts.py            # 全部 prompt 模板（业务词典 / few-shot / 负向约束）
│   ├── llm.py                # LLM 抽象层：template / openai_compatible / anthropic + 自动降级
│   ├── analysis_channel.py   # 渠道分析（ONLINE/OFFLINE/二级渠道）
│   ├── analysis_funnel.py    # DTC-RCMP 销售分析 + Sales Tree（HTML/CSS）
│   ├── analysis_drilldown.py # PA→Family→Article 三级归因 + 潜力识别规则
│   ├── ml_insights.py        # LightGBM+SHAP 归因、轻量 7 天预测
│   └── report.py             # 报告装配（业绩总结置顶）
├── tests/                    # pytest + Streamlit AppTest 回归
└── data/                     # 首次运行自动生成的 mock 数据缓存（不入库）
```

## 从 notebook 到产品的工程化改造

原始系统是一个串联执行的 Jupyter notebook，本 Demo 做了以下产品化重构：

1. **依赖剥离**：ODPS 数仓 → mock 数据生成器（schema 一致，分析代码零改动）；
2. **安全合规**：移除全部明文密钥与内网地址，LLM 配置走环境变量；
3. **降级设计**：LLM 无 Key / 调用失败 → 规则模板；LightGBM/SHAP 缺失 → 相关系数归因；演示永不中断；
4. **轻量化**：四模型融合归因 → 单模型 SHAP（完整模式保留开关）；Prophet 预测 → 轻量外推；
5. **修复线上 bug**：原 `display_number` 的 ×100 启发式会把 100 口径下 <10 的真实差值误放大（-1.2 → -120），已修正；
6. **交互化**：graphviz（依赖系统二进制）→ 纯 HTML/CSS Sales Tree；静态 PDF → 可交互 Web 报告。

## 产品化路线图

1. **配置化**：HFB / 周次已参数化（✅ 本 Demo 已实现）；潜力识别阈值当前为规则引擎内置常量，
   UI 暴露为可调参数（🔄 待实现）；
2. **IM 推送**：飞书/企微定时推送 PDF，触达一线店长；
3. **追问式分析**：在报告上直接对话追问（"为什么 PA 013 上升？"）；
4. **评估体系**：结论准确率抽检 + 业务采纳率回流，持续迭代 prompt 与规则阈值。

---

## 隐私与安全声明

- 所有数据均为**确定性仿真数据**（时间锚点 2025-07-06，仿真门店），不含任何真实经营数据；
- API Key 仅保存在当前浏览器会话内，不写入文件、日志、URL 或报告；Key 会发送到
  Streamlit 服务端再转发给模型服务商，建议使用低额度、可撤销的专用 Key；
- 报告只记录 Provider、模型与调用状态，不记录 Key；
- 公开版本已移除原 notebook 中的全部凭证、内网地址、绝对路径与真实输出；
- 运行测试：`pytest`（含 Mock 跨进程确定性、LLM 降级、Key 不泄漏、AppTest 页面回归）。

*本项目为求职作品集 Demo。*
