# ReportAgent

连上零售数仓，可以对话问数，也可以一键生成周度诊断报告和漏斗看板。报告和表格里的数字都由代码计算，模型只负责写文字。

## 能做什么

- **对话问数：** 统计、排名、趋势、归因。回答附表格、图表和实际执行的 SQL。
- **周度诊断报告：** 整体 → 渠道 → 销售树 → 子类 → 卖家 → 商品，可下载 HTML 和 PDF。
- **漏斗分析：** 浏览 → 加购 → 成交，可选维度并逐级下钻。
- **项目管理：** 按项目组织任务，报告和对话都归在任务里。
- **模型校验：** 回答出现数据里没有的数字、把指数写成增幅或方向写反时，会退回规则文字。

## 本地运行

```bash
uv venv --python 3.12 .venv
uv pip install -e ".[dev]" --python .venv/bin/python
cp .env.example .env   # 按需填写 LLM_API_KEY
(cd web && npm ci && npm run build)
.venv/bin/reportagent demo
REPORTAGENT_DB_URL=duckdb:///data/demo.duckdb REPORTAGENT_SEMANTIC=semantic.demo.yaml .venv/bin/reportagent serve
```

打开 http://127.0.0.1:8501。演示数仓是合成数据，界面和报告会显示“模拟数据”。

### 使用真实公开数据

从 Kaggle 下载 [Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) 和 [RetailRocket](https://www.kaggle.com/datasets/retailrocket/ecommerce-dataset)，解压到 `data/raw/olist` 和 `data/raw/retailrocket`，再运行：

```bash
.venv/bin/reportagent load-real
```

两份数据来自不同公司，产品里分开展示。Olist 没有目标、客流和库存，相关指标不显示。使用前请核对两份数据的许可条款。

## 接自己的数仓

1. 复制 `semantic.demo.yaml`，把表名和字段名改成你的。只有销售事实表必填。
2. 设置 `REPORTAGENT_DB_URL` 和 `REPORTAGENT_SEMANTIC`，建议使用只读账号。
3. 运行检查：

```bash
.venv/bin/reportagent check
```

支持 DuckDB、Postgres、MySQL 和 MaxCompute。其中 MaxCompute 和 MySQL 只验证过 SQL 编译，没有做真实联调。

## 批量生成

```bash
.venv/bin/reportagent report --store SP,RJ --category all --week 201834
```

## 部署

线上地址：https://reportagent.vercel.app

前端在 Vercel（`vercel.json` 把接口转发到 Render），后端在 Render（`Dockerfile`），数据、会话和报告在 Supabase。数仓表放在 `warehouse` schema，应用状态放在 `app` schema，都不经过 Supabase 对外的 API。

| 环境变量 | 说明 |
|---|---|
| `REPORTAGENT_DB_URL` | 只读账号的数仓连接 |
| `REPORTAGENT_APP_DB_URL` | 应用状态库连接 |
| `LLM_API_KEY` | 模型密钥 |
| `LLM_MODEL` | 对话模型，必须支持工具调用，默认 `agent-model` |
| `LLM_TEXT_MODEL` | 报告文字模型 |
| `LLM_FALLBACK_MODEL` | 被限流时切换的模型 |
| `REPORTAGENT_COOKIE_SECURE` | 线上设为 `1` |
| `REPORTAGENT_CHAT_PER_HOUR` | 每个访客每小时提问上限，默认 30 |

## 第三方组件

- [morphicons](https://github.com/guillermolg00/morphicons)（MIT）：图标变形。
- [ReactDrops](https://reactdrops.dev)：`web/src/vendor/reactdrops` 里的 Liquid Glass Orb，遵循同目录 `LICENSE`，只作为本应用的一部分使用，不单独分发。

## 已知限制

- 没有账号体系，靠随机 cookie 隔离访客，清除 cookie 后看不到原来的项目和任务。
- Render 免费实例闲置后会休眠，首次打开需要等待约一分钟；Supabase 免费项目长期闲置可能被暂停。
- 数字校验能拦截错误数字和部分方向错误，拦不住所有语义错误，结论仍需对照表格。
- 漏斗是同周期各步 UV 之比，不是同一用户的顺序路径。
- 财年周历只支持 ISO 周。
