# Handoff 交接文档 — 智能业绩诊断 Agent 产品 Demo

> 交接日期：2026-07-23（v2 固定域名展示方案）
> 项目状态：**v2 改造完成，17 项测试全绿，代码已推送 GitHub**
> 项目路径：`AI-Agent-Outputs/claude/ikea-report-agent-demo/`
> GitHub：`https://github.com/Howieu/reportagent`（Private，部署/公开前转 Public）
> Streamlit 固定子域名（待部署）：`https://ikea-report-agent.streamlit.app`
> 固定域名落地页（待绑定）：`https://demo.<个人域名>`

---

## 1. 项目背景

| 项 | 内容 |
|---|---|
| 来源 | 用户在 IKEA 实习期间开发的自动化数分周报 notebook（`实习&工作/IKEA实习/自动数分报告生成Agent/Automated PDF Generation.ipynb`） |
| 目标 | 包装为**求职作品集级产品 Demo**，受众为面试官（AI 产品经理·数据方向） |
| 展示方案（v2） | **Cloudflare Pages 固定域名外壳 + Streamlit Cloud 交互应用**：落地页承载项目叙事，iframe 懒加载嵌入 Demo，「新窗口打开」为备用入口 |
| 业务场景 | 门店商业团队每周对每个 HFB 做业绩复盘，人工约 4 小时/份 → 系统约 1 分钟/份 |

## 2. 快速启动

```bash
cd "AI-Agent-Outputs/claude/ikea-report-agent-demo"
.venv/bin/streamlit run app.py
```

- 浏览器打开后：左侧选门店 / HFB（支持 `1-3,7` 形式）/ 周次 → 点 **生成报告**；
- **离线演示模式（默认）**：文本生成方式 = 离线模板，无需任何 Key；
- **在线 LLM 润色**：侧边栏选 OpenAI 兼容服务或 Anthropic，会话内填 Key / 模型即可；
  也可 `cp .env.example .env` 配置（环境变量方式仍保留）。

⚠️ **环境注意**：系统 anaconda base 环境的 pandas/numpy 已损坏。本项目所有 Python 操作一律使用项目内 `.venv/bin/python`（Python 3.12），不要在 base 环境运行。

## 3. 架构与代码地图

五层诊断流水线（与 notebook 一一对应）：

```
数仓层  src/mock_data.py        确定性 mock 生成器（blake2b 派生种子，跨进程一致）
契约层  src/data_provider.py    ReportRequest / ReportData 契约 + MockDataProvider
                                （OdpsDataProvider 占位，公开部署禁止启用）
文本化  src/metrics.py          数字唯一入口 display_number / display_metrics（LLM 不做算术）
分析层  src/analysis_channel.py 渠道分析（ONLINE/OFFLINE/二级渠道，for_human/for_llm 双轨）
        src/analysis_funnel.py  DTC-RCMP 销售分析 + Sales Tree（纯 HTML/CSS）
        src/analysis_drilldown.py PA→Family→Article 三级归因 + 潜力识别规则引擎
        src/prompts.py          全部 prompt（业务词典 / 两段式 / few-shot / 负向约束）
        src/llm.py              LLMConfig 三 Provider（template/openai_compatible/anthropic）
                                + 错误分类降级，错误文本不回显 Key
ML 层   src/ml_insights.py      LightGBM+SHAP 归因（缺失时相关系数兜底）、轻量 7 天预测
渲染层  src/report.py           报告装配（业绩总结置顶，markdown2 → HTML，标注数据源/锚点/模式）
入口    app.py                  Streamlit 双 Tab；会话内 Key 配置；报告按参数缓存
落地页  site/index.html         Cloudflare Pages 静态站点（iframe 懒加载 + 骨架屏 + 新窗口备用入口）
```

配套文档：`README.md`（PRD-lite + 部署架构 + 隐私声明）、`demo_script.md`（3 分钟演示动线）。

## 4. v2（2026-07-23）变更清单

1. **app.py 重写**：文本生成方式三选一（默认离线模板）；在线模式 Key 为密码框、仅存
   `st.session_state`，页面明确提示"Key 会发送到 Streamlit 服务端，建议低额度可撤销 Key"；
   Key/模型为空自动降级模板；ML 开关默认关闭；报告 HTML 按参数 `st.cache_data` 缓存，
   Key 仅参与缓存键哈希；
2. **新增 site/ 落地页**：项目价值 / 五层架构 / 三步操作 / 技术取舍 / 数据与隐私声明 /
   个人职责；iframe `?embed=true` + IntersectionObserver 懒加载 + 骨架屏 20s 兜底 +
   新窗口备用入口；移动端响应式；
3. **依赖固定**：requirements.txt 全部 pin 版本（Python 3.12），干净 venv 验证通过；
4. **仓库治理**：`.gitignore` 补 `.venv/` / `.pytest_cache/` / 模型 / 本地报告；
   README 增加在线访问表、部署架构图、隐私与安全声明；
   代码已推送 `github.com/Howieu/reportagent`（Private）；
5. **测试**：17 项全绿 —— Mock 跨进程确定性、Provider 契约、401/429/超时降级、
   Key 不出现在异常/HTML/repr、AppTest 页面加载/报告生成/HTML 下载。

## 5. 关键设计决策（面试叙事核心）

1. **幻觉防控**：报告里每个数字都由代码计算，LLM 只负责语言组织；
2. **双轨渲染**：同一数据分别产出人读明细（HTML）与模型输入（纯文本）；
3. **业务词典 prompt**：ind.LY / PIP / Conv. Rate 等口径内置，禁止"优化定价"等越权建议；
4. **降级设计**：LLM 无 Key/失败 → 规则模板；SHAP 缺失 → 相关系数；演示永不中断；
5. **Key 最小暴露**：会话级保存、不落盘、不进日志/URL/报告，错误信息只回分类；
6. **风险披露**：页面保留"报告中的文字说明由AI生成"标注。

## 6. 与原始 notebook 的差异（有意为之）

| 改动 | 原因 |
|---|---|
| ODPS 取数 → 确定性 mock 数据生成器 | 剥离内网依赖；字段名完全一致，分析代码零改动 |
| 四模型融合归因 → 单模型 LightGBM+SHAP（默认关闭） | 演示速度；完整模式逻辑保留 |
| Prophet 预测 → 28 天按星期均值外推 | 依赖重、慢；轻量版秒级出结果 |
| graphviz Sales Tree → 纯 HTML/CSS | graphviz 需系统二进制，不可移植 |
| `display_number` ×100 启发式阈值修正 | **修复了原 notebook 的真实 bug**（-1.2 → -120 误放大） |
| wkhtmltopdf PDF → HTML 报告 + 浏览器打印 | wkhtmltopdf 硬编码 Windows 路径，不可交付 |

## 7. 验证记录（2026-07-23）

- ✅ `pytest` 17 项全绿（Mock 跨进程确定性 / LLM 降级 / Key 不泄漏 / AppTest 三场景）；
- ✅ ML 开启 + qty 口径冒烟：HFB 01 报告正常渲染；
- ✅ 干净 venv 按 pin 版本安装导入验证通过；
- ✅ secret 模式扫描无命中（无明文密钥、无内网地址、无个人路径残留）；
- ✅ 代码推送 GitHub 私有仓库成功。

## 8. 待办（需本人操作的外部事项）

1. **轮换原 notebook 中暴露的 ODPS/Azure 凭证**（最高优先级）；
2. **Streamlit Cloud**：连接 `Howieu/reportagent`，从 `app.py` 部署，
   自定义子域名设为 `ikea-report-agent`；
3. **Cloudflare Pages**：连接同一仓库，构建目录设为 `site/`，绑定 `demo.<个人域名>`；
4. 域名确定后替换 README 在线访问表中的 `demo.<个人域名>` 占位；
5. 仓库转 Public 前再跑一次 secret scan（如安装 gitleaks：`gitleaks dir .`）；
6. 验收：移动端打开落地页、休眠唤醒后 iframe 与"新窗口打开"均可用、三步内生成首份报告。

## 9. 已知限制

- 单份报告生成约 18 秒（ML 模式），演示前建议预生成一次预热（缓存已按参数生效）；
- mock 数据为静态快照（时间锚点 2025-07-06），周次选择仅为展示参数；
- `st.components.v1.html` 有弃用警告（st.iframe 仅支持 URL，无法替代 srcdoc 渲染），功能无碍；
- 商品图为 base64 SVG 占位图（离线可用）；接真实环境时换回 `pic_url`；
- Streamlit Cloud 空闲休眠：不使用心跳绕过，落地页已提供唤醒提示与新窗口入口。

## 10. 后续路线（如继续迭代）

1. 单一域名 / 持续在线需求出现时：同一应用 Docker 化部署 Render / Cloud Run，Cloudflare 域名不变；
2. IM 推送：飞书/企微定时推送 PDF（触达一线店长的真实形态）；
3. 追问式分析：报告上对话追问（"为什么 PA 013 上升？"）；
4. 评估闭环：结论准确率抽检 + 业务采纳率回流，迭代 prompt 与规则阈值；
5. 若接回真实数仓：实现 `OdpsDataProvider.load()` 即可，分析层无需改动。
