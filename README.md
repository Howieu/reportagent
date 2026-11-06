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
| 项目管理 | 按项目组织任务，对话和报告都归在任务里 |
| 联网搜索 | 输入框的开关，默认关闭。打开后可查外部公开信息，回答附来源 |
| 追问改写 | 把依赖上下文的追问改写成独立问题，并在回答里展示 |
| 批量生成 | 命令行批量导出 HTML 和 PDF，可接入定时任务 |

## 工作原理

```text
semantic.yaml（表和字段的映射）
        ↓
代码生成 SQL，在数仓里聚合
        ↓
确定性分析：同比、对标、销售树分解、下钻、潜力规则
        ↓
模型组织文字 → 校验不过就改用规则文字
        ↓
工作台 / HTML / PDF
```

- **模型不写 SQL：** 模型只能调用固定工具并传结构化参数。筛选值会先对应到数仓里的真实取值。
- **文字要过校验：** 出现数据里没有的数字、把指数写成增幅、涨跌方向明显写反或命中禁用词时，会退回规则文字。
- **没有的数据不编造：** 没配置目标、客流或库存表时，相关指标不显示。

校验拦不住所有语义错误，重要结论仍要对照表格。

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

要启用对话，复制 `.env.example` 为 `.env` 并填写 `LLM_API_KEY`。接口兼容 OpenAI，默认使用模型服务。`.env.example` 默认指向真实公开数据，用合成数据时要保留上面命令里的连接设置。

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

## 部署

Render 和 Vercel 是两种独立的部署方式，任选其一都能运行完整产品。线上两个站点共用一个 Supabase 项目。

| | Render | Vercel |
|---|---|---|
| 配置 | `Dockerfile` | `app.py` + `vercel.json` |
| PDF | 服务端用 Chromium 生成 | 浏览器打印窗口存储为 PDF |
| 启动 | 免费实例休眠后，首次打开可能要等一分钟左右 | 刚部署或闲置后，首次访问实测约 22 秒 |
| 进程内状态 | 单实例 | 限流和缓存按实例计算，不是严格的全局限制 |

数仓表放在 `warehouse` schema，会话和报告放在 `app` schema，都不在 Supabase API 默认暴露的 `public` 里。用 [`reportagent/push.py`](reportagent/push.py) 可以把本地 DuckDB 导入 Postgres，并创建只读账号和应用账号。

| 环境变量 | 说明 |
|---|---|
| `REPORTAGENT_DB_URL` | 数仓连接，线上用只读账号 |
| `REPORTAGENT_APP_DB_URL` | 会话和报告的存储库，不设置时用本地 SQLite |
| `REPORTAGENT_SEMANTIC` | 语义配置文件 |
| `LLM_API_KEY` / `LLM_BASE_URL` | 模型密钥和接口地址 |
| `LLM_MODEL` | 对话模型，必须支持工具调用，默认 `agent-model` |
| `LLM_TEXT_MODEL` | 报告文字模型，不设置时同对话模型 |
| `LLM_FALLBACK_MODEL` | 被限流时切换的模型，付费模型会产生费用 |
| `REPORTAGENT_COOKIE_SECURE` | HTTPS 环境设为 `1` |
| `REPORTAGENT_CHAT_PER_HOUR` | 每位访客每小时提问上限，默认 30 |
| `REPORTAGENT_REPORTS_PER_HOUR` | 每位访客每小时报告上限，默认 30 |
| `REPORTAGENT_WEB_PER_HOUR` | 每位访客每小时开启联网的提问上限，默认 10 |
| `WEB_SEARCH_API_KEY` | 联网搜索密钥，不设置时用 `LLM_API_KEY`。搜索按次计费 |

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

- 没有账号体系，靠随机 cookie 区分访客。清除 cookie 或换站点后，看不到原来的项目和任务。
- 漏斗是同周期各步 UV 之比，不是同一用户的顺序路径。
- 周次只支持 ISO 周，不支持自定义财年周历。
- 第一版不做销量预测和 SHAP 归因。

## 许可与致谢

本项目暂未声明开源许可。第三方内容各有条款：

- [morphicons](https://github.com/guillermolg00/morphicons)（MIT）：图标变形。
- [ReactDrops](https://reactdrops.dev)：`web/src/vendor/reactdrops` 里的 Liquid Glass Orb，遵循同目录的 `LICENSE`，只作为本应用的一部分使用，不单独分发。
- [Olist 数据集](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce)：CC BY-NC-SA 4.0，限非商业使用。
- [RetailRocket 数据集](https://www.kaggle.com/datasets/retailrocket/ecommerce-dataset)：使用前请核对 Kaggle 页面上的许可。
