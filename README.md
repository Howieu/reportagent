# ReportAgent

ReportAgent 连接零售数仓，让业务同学用对话查数，或者选好门店、品类和周次，直接生成一份可下载的周度诊断报告。

报告和表格里的数字都由代码计算。模型只写文字，写出的内容还要通过校验。

**在线体验：** [Vercel](https://reportagent.vercel.app) · [Render](https://reportagent-api.onrender.com)

线上数据来自公开数据集：报告用 Olist 巴西电商订单（2017-01 至 2018-08），漏斗用 RetailRocket 行为日志（2015 年）。两者来自不同公司，产品里分开展示，不互相换算。

## 功能

| 功能 | 说明 |
|---|---|
| 对话问数 | 统计、排名、趋势和归因。回答附表格、图表和实际执行的 SQL |
| 诊断报告 | 摘要 → 整体 → 渠道 → 销售树 → 子类 → 品牌 → 商品 → 区域，可导出 PDF |
| 漏斗分析 | 浏览 → 加购 → 成交，可选维度并逐级下钻 |
| 销量预测 | 预测未来 1 到 4 周的销售额或销量，附 80% 区间、回测对比和 SHAP 归因。回测赢过简单基线才用模型的数字 |
| 项目管理 | 按项目组织任务，对话和报告都归在任务里 |
| 联网搜索 | 输入框的开关，默认关闭。打开后可查外部公开信息，回答附来源 |
| 追问改写 | 问题改写 Agent 把依赖上下文的追问改成独立问题，并在回答里展示 |
| 批量生成 | 命令行批量导出 HTML 和 PDF，可接入定时任务 |

## 架构图

**系统分层**

![系统分层：入口、服务、编排、能力、外部依赖](docs/architecture/1-overview.png)

**提问进入：解析、改写和辅助思考**

![提问进入模型前的链路](docs/architecture/2-query.png)

**意图识别与工具：什么时候调用什么**

![意图识别 Agent 与工具循环](docs/architecture/3-tools.png)

**形成报告：两个入口，一条流水线**

![报告生成链路](docs/architecture/4-report.png)

Agent 分工表和 19 种情况的走法对照见 [完整版](docs/architecture.html)（下载后用浏览器打开）。

## 快速开始

需要 Python 3.11+、Node.js 和 [uv](https://docs.astral.sh/uv/)。下面用合成数据运行，不需要模型密钥，但对话功能要配置密钥后才能用。

```bash
uv venv --python 3.12 .venv
```

```bash
uv pip install -e ".[dev]" --python .venv/bin/python
```

```bash
(cd web && npm ci && npm run build)
```

```bash
.venv/bin/reportagent demo
```

```bash
REPORTAGENT_DB_URL=duckdb:///data/demo.duckdb .venv/bin/reportagent --semantic semantic.demo.yaml serve
```

打开 <http://127.0.0.1:8501>。合成数据的界面和报告都会显示明确标记。

要启用对话，复制 `.env.example` 为 `.env`，填写 `AGENT_API_KEY`、`AGENT_BASE_URL` 和 `AGENT_MODEL`。接口需要兼容 OpenAI，模型需要支持工具调用。`.env.example` 默认指向真实公开数据，用合成数据时要保留上面命令里的连接设置。

### 使用公开数据

从 Kaggle 下载 [Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) 和 [RetailRocket](https://www.kaggle.com/datasets/retailrocket/ecommerce-dataset)，分别解压到 `data/raw/olist` 和 `data/raw/retailrocket`，然后导入：

```bash
.venv/bin/reportagent load-real
```

```bash
REPORTAGENT_DB_URL=duckdb:///data/real.duckdb .venv/bin/reportagent --semantic semantic.real.yaml serve
```

Olist 没有实体门店和销售渠道，这里用最接近的真实字段映射：门店对应卖家所在州，渠道对应同州或跨州配送，品牌对应卖家。

## 接入自己的数仓

**1. 写语义配置。** 只有销售事实表必填：

```yaml
name: 我的零售数仓
sources:
  sales:
    table: dwd.fact_sales
    date: biz_date
    store: store_id
    channel: channel
    category: category
    subcategory: subcategory
    family: brand
    item: item_id
    sales: net_sales
    qty: qty
    ticket: order_id
```

目标、客流、商品、门店、库存和漏斗都是可选数据源。完整写法见 [semantic.demo.yaml](semantic.demo.yaml) 和 [semantic.real.yaml](semantic.real.yaml)。日期存成字符串时，在 `calendar.date_format` 里写明格式。

**2. 配置连接。** 建议使用只读账号：

| 数仓 | `REPORTAGENT_DB_URL` | 验证情况 |
|---|---|---|
| DuckDB | `duckdb:///data/my.duckdb` | 已运行 |
| Postgres | `postgresql+psycopg://user:pass@host:5432/db` | 已在 Supabase 运行 |
| MySQL | `mysql+pymysql://user:pass@host:3306/db` | 仅编译过 SQL，需安装 `.[mysql]` |
| MaxCompute | `odps://ACCESS_ID:SECRET@PROJECT/?endpoint=ENDPOINT` | 仅编译过 SQL，需安装 `.[maxcompute]` |

**3. 检查字段映射：**

```bash
.venv/bin/reportagent --semantic my.yaml check
```

## 命令行

```bash
.venv/bin/reportagent --semantic semantic.real.yaml report --store SP,RJ --category all --week 201834 --out reports
```

| 参数 | 说明 |
|---|---|
| `--store` / `--category` | 逗号分隔，或写 `all` |
| `--week` | ISO 周次 `YYYYWW`，默认最近完整周 |
| `--channel` / `--focus` | 下钻渠道；分析指标 `sales` 或 `qty` |
| `--no-llm` | 只用规则文字，不调用模型 |
| `--no-pdf` | 只输出 HTML。生成 PDF 需要本机有 Chrome 或 Chromium |

预测未来 4 周，并把报告存成 HTML：

```bash
.venv/bin/reportagent --semantic semantic.real.yaml forecast --store SP --category 美妆个护 --metric sales --out reports
```

`--store` 和 `--category` 不填表示全部；`--metric` 可选 `sales`（销售额）或 `qty`（销量）；`--week` 指定预测起点。

## 销量预测和 SHAP 归因

- **防泄漏：** 特征只用预测起点及之前的数据，训练样本的目标周不晚于训练截止周，不使用同期指标。测试会改动未来数据，确认更早的预测不变。
- **模型：** 门店 × 品类、门店合计、品类合计和全部合计一起训练，提前 1 到 4 周各一个 LightGBM 模型。特征是近期销售、价格变化、大盘走势、去年同期季节性和经营规模。
- **基线门槛：** 对每个范围回测最近 12 周，和上周值、近 4 周均值、近 8 周均值比较。模型赢了才用模型的数字，否则用基线，并在结果里写明。
- **SHAP：** 用 LightGBM 内置的精确 TreeSHAP，把下周的模型预测拆成近 8 周周均、历史平均趋势和各因素贡献，各项相加等于模型预测。它解释模型依赖什么，不代表因果。

线上数据（Olist，起点 2018 年第 33 周）的回测结果，表中是模型赢过基线的范围占比：

| 范围 | 提前 1 周 | 提前 2 周 | 提前 3 周 | 提前 4 周 |
|---|---|---|---|---|
| 全部（1 个） | 1/1（误差 13.6%，基线 17.2%） | 0/1 | 0/1 | 0/1 |
| 品类（9 个） | 44% | 33% | 0% | 11% |
| 卖家州（19 个） | 53% | 37% | 32% | 37% |
| 州 × 品类（105 个） | 59% | 51% | 44% | 50% |

提前 2 周以上，模型大多赢不了简单基线，所以多数范围显示的是基线数字。这份数据没有促销、节假日和库存特征，回测窗口也只有 12 周，这些比例只说明这段时间的情况。

Olist 最后一周（2018 年第 34 周）的销售只有前 4 周均值的 49%，疑似数据没入齐。没有指定起点时，全仓最新一周低于前 4 周均值的 60% 就退回一周，并在结果里写明。

## 部署

Render 和 Vercel 是两种独立的部署方式，任选其一都能运行完整产品。线上两个站点共用一个 Supabase 项目。

| | Render | Vercel |
|---|---|---|
| 配置 | `Dockerfile` | `app.py` + `vercel.json` |
| PDF | 服务端用 Chromium 生成 | 浏览器打印窗口存储为 PDF |
| 预测依赖 | 镜像已安装 `libgomp1` | 构建脚本打包 `libgomp`；加载失败时只给基线，没有 SHAP，页面写明原因 |
| 启动 | 免费实例休眠后，首次打开可能要等一分钟左右 | 刚部署或闲置后，首次访问实测约 22 秒 |
| 进程内状态 | 单实例 | 限流和缓存按实例计算，不是严格的全局限制 |

数仓表放在 `warehouse` schema，会话和报告放在 `app` schema，都不在 Supabase API 默认暴露的 `public` 里。用 [`reportagent/push.py`](reportagent/push.py) 可以把本地 DuckDB 导入 Postgres，并创建只读账号和应用账号。

| 环境变量 | 说明 |
|---|---|
| `REPORTAGENT_DB_URL` | 数仓连接，线上用只读账号 |
| `REPORTAGENT_APP_DB_URL` | 会话和报告的存储库，不设置时用本地 SQLite |
| `REPORTAGENT_SEMANTIC` | 语义配置文件 |
| `AGENT_API_KEY` / `AGENT_BASE_URL` | Agent 模型的密钥和接口地址 |
| `AGENT_MODEL` | 问题改写、辅助思考、意图识别、回答修正 Agent 的模型，必须支持工具调用 |
| `WRITER_AGENT_MODEL` | 报告撰写 Agent 的模型，不设置时同 `AGENT_MODEL` |
| `AGENT_FALLBACK_MODEL` | 被限流时切换的模型，付费模型会产生费用 |
| `AGENT_EXTRA_BODY` | 传给模型接口的附加参数（JSON） |
| `WEB_SEARCH_URL` / `WEB_SEARCH_ENGINE` | 联网搜索服务地址和引擎，不配置时不显示开关 |
| `REPORTAGENT_COOKIE_SECURE` | HTTPS 环境设为 `1` |
| `REPORTAGENT_CHAT_PER_HOUR` | 每位访客每小时提问上限，默认 30 |
| `REPORTAGENT_REPORTS_PER_HOUR` | 每位访客每小时报告上限，默认 30 |
| `REPORTAGENT_WEB_PER_HOUR` | 每位访客每小时开启联网的提问上限，默认 10 |
| `WEB_SEARCH_API_KEY` | 联网搜索密钥，不设置时用 `AGENT_API_KEY`。可能按次计费 |

## 开发

```bash
.venv/bin/python -m pytest
```

```bash
.venv/bin/ruff check .
```

前端开发时运行 `cd web && npm run dev`，接口会转发到 `127.0.0.1:8501`。对公开数据的核对测试需要 `data/real.duckdb` 和原始 CSV，缺少时自动跳过。

```text
reportagent/   后端：语义配置、SQL 生成、分析、对话、报告模板、服务
web/           前端：React 工作台
tests/         测试：手算数据、演示数仓、公开数据核对
```

## 已知限制

- 回答校验能拦截错误数字和部分方向错误，拦不住所有语义错误，重要结论仍要对照表格。
- 没有账号体系，靠随机 cookie 区分访客。清除 cookie 或换站点后，看不到原来的项目和任务。
- 漏斗是同周期各步 UV 之比，不是同一用户的顺序路径。
- 周次只支持 ISO 周，不支持自定义财年周历。
- 预测没有促销、节假日、客流和库存特征，无法预判这些事件带来的波动。
- 各范围分别预测，门店或品类的预测加起来不一定等于全部的预测。
- 预测的训练结果缓存在进程内，首次预测要等几秒，配置低的实例会更久。

## 许可与致谢

本项目暂未声明开源许可。第三方内容各有条款：

- [morphicons](https://github.com/guillermolg00/morphicons)（MIT）：图标变形。
- [ReactDrops](https://reactdrops.dev)：`web/src/vendor/reactdrops` 里的 Liquid Glass Orb，遵循同目录的 `LICENSE`，只作为本应用的一部分使用，不单独分发。
- [Olist 数据集](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce)：CC BY-NC-SA 4.0，限非商业使用。
- [RetailRocket 数据集](https://www.kaggle.com/datasets/retailrocket/ecommerce-dataset)：使用前请核对 Kaggle 页面上的许可。
