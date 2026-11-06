"""生成美妆零售合成数仓（DuckDB）。品牌、门店和数字全部虚构，随机种子固定。

预埋异动（store S01、SKINCARE、目标周）用于验证报告能否找到：
- 品牌 LUMERA 的销量约为去年 2.4 倍（上升）
- 品牌 VELOUR 的 SKU 缺货导致销量约为去年 0.35 倍（下降）
- S01 的门店渠道转化上升（客流基本持平）
"""

from datetime import date, timedelta
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

TARGET_WEEK = "202644"
END = date(2026, 11, 1)  # 周日，ISO 202644 最后一天
START = date(2024, 9, 2)
STORES = [
    ("S01", "上海静安店", "A", "华东", "上海"), ("S02", "上海陆家嘴店", "A", "华东", "上海"),
    ("S03", "杭州湖滨店", "A", "华东", "杭州"), ("S04", "南京新街口店", "A", "华东", "南京"),
    ("S05", "北京三里屯店", "A", "华北", "北京"), ("S06", "天津滨江店", "B", "华北", "天津"),
    ("S07", "广州天河店", "A", "华南", "广州"), ("S08", "深圳南山店", "A", "华南", "深圳"),
    ("S09", "成都春熙路店", "A", "西南", "成都"), ("S10", "武汉江汉路店", "B", "华中", "武汉"),
]
CATALOG = {
    "SKINCARE": {"精华": ["LUMERA", "AQUALYS"], "面霜": ["VELOUR", "SOLENNE"], "洁面": ["MIREL", "AQUALYS"],
                 "面膜": ["NOVELLE", "LUMERA"]},
    "MAKE UP": {"口红": ["ROSARA", "CINDRE"], "粉底": ["ROSARA", "ETHERA"], "眼妆": ["CINDRE", "ETHERA"]},
    "FRAGRANCE": {"女香": ["FLEURINE", "OSMANTE"], "男香": ["OSMANTE", "NOIRVA"]},
    "HAIR": {"洗护": ["SERENA", "HALO"], "造型": ["HALO", "SERENA"]},
}
CATEGORY_WEIGHT = {"SKINCARE": 0.52, "MAKE UP": 0.31, "FRAGRANCE": 0.13, "HAIR": 0.04}
CHANNELS = [("RETAIL", "门店", 0.62), ("RETAIL", "智能导购", 0.08), ("ONLINE", "APP", 0.14),
            ("ONLINE", "小程序", 0.10), ("ONLINE", "天猫", 0.06)]


def _catalog(rng):
    rows = []
    sub_id = 0
    for cat, subs in CATALOG.items():
        for sub, brands in subs.items():
            sub_id += 1
            for brand in brands:
                for k in range(3):
                    rows.append({
                        "item_id": f"{cat[:2]}{sub_id:02d}{brand[:2]}{k}", "item_name": f"{brand} {sub} {k + 1}号",
                        "category": cat, "subcategory": sub, "brand": brand,
                        "price": float(rng.choice([98, 168, 238, 328, 458, 680])),
                        "weight": float(rng.gamma(2.0, 1.0)),
                        "is_new": False,
                        "is_hero": k == 0, "is_member_exclusive": k == 2 and brand[0] in "ACLOR",
                    })
    items = pd.DataFrame(rows)
    # 新品：今年才开售，用于验证“排除新品”的同口径
    items.loc[items["item_id"].str.endswith("2") & (items.index % 7 == 0), "is_new"] = True
    return items


def _multiplier(items, store, day):
    """预埋异动的销量乘数。"""
    m = np.ones(len(items))
    week_start = date(2026, 10, 26)
    if store == "S01" and week_start <= day <= END:
        m[(items["brand"] == "LUMERA").to_numpy()] = 2.4
        m[(items["brand"] == "VELOUR").to_numpy()] = 0.35
    return m


def build(path="data/demo.duckdb", seed=42, tickets_per_day=60):
    rng = np.random.default_rng(seed)
    items = _catalog(rng)
    cat_w = items["category"].map(CATEGORY_WEIGHT).to_numpy()
    base_w = items["weight"].to_numpy() * cat_w / items.groupby("category")["weight"].transform("sum").to_numpy()
    days = pd.date_range(START, END).date
    store_scale = {s[0]: 0.7 + 0.6 * i / (len(STORES) - 1) for i, s in enumerate(reversed(STORES))}

    frames, traffic = [], []
    ticket_no = 0
    n_days_total = len(days)
    for store, *_ in STORES:
        for idx, day in enumerate(days):
            season = 1 + 0.25 * np.sin(2 * np.pi * idx / 365) + (0.8 if day.month == 11 and day.day <= 11 else 0)
            growth = 1 + 0.08 * idx / n_days_total
            weekend = 1.35 if day.weekday() >= 5 else 1.0
            n = rng.poisson(tickets_per_day * store_scale[store] * season * growth * weekend)
            mult = _multiplier(items, store, day)
            p = base_w * mult
            launched = ~items["is_new"].to_numpy() | (day >= date(2026, 3, 1))
            p = p * launched
            p = p / p.sum()
            if store == "S01" and date(2026, 10, 26) <= day <= END:
                n = int(n * 1.10)
            counts = rng.integers(1, 4, size=n)  # 每单 1-3 件
            line_items = rng.choice(len(items), size=int(counts.sum()), p=p)
            ticket_ids = np.repeat(np.arange(ticket_no, ticket_no + n), counts)
            ticket_no += n
            ch_idx = rng.choice(len(CHANNELS), size=n, p=[c[2] for c in CHANNELS])
            ticket_ch = np.repeat(ch_idx, counts)
            qty = np.ones(len(line_items), dtype=int)
            price = items["price"].to_numpy()[line_items] * rng.uniform(0.85, 1.0, len(line_items))
            frames.append(pd.DataFrame({
                "biz_date": day, "store_id": store,
                "channel": [CHANNELS[c][0] for c in ticket_ch],
                "subchannel": [CHANNELS[c][1] for c in ticket_ch],
                "item_id": items["item_id"].to_numpy()[line_items],
                "net_sales": np.round(price, 2), "qty": qty,
                "order_id": [f"T{t}" for t in ticket_ids],
            }))
            retail_tickets = int((ch_idx <= 1).sum())
            online_tickets = n - retail_tickets
            drop = 0.82 if store == "S01" and date(2026, 10, 26) <= day <= END else 1.0
            traffic.append((day, store, "RETAIL", int(retail_tickets / rng.uniform(.16, .2) * drop)))
            traffic.append((day, store, "ONLINE", int(online_tickets / rng.uniform(.03, .05))))

    sales = pd.concat(frames, ignore_index=True).merge(
        items[["item_id", "category", "subcategory", "brand"]], on="item_id")
    traffic_df = pd.DataFrame(traffic, columns=["biz_date", "store_id", "channel", "visitors"])
    stores_df = pd.DataFrame(STORES, columns=["store_id", "store_name", "peer_group", "region", "city"])

    # 周目标 = 去年同周实际 × 1.12，加噪声（门店×品类×渠道）
    wk = sales.assign(week_start=pd.to_datetime(sales["biz_date"]).dt.to_period("W").dt.start_time.dt.date)
    goals = wk.groupby(["week_start", "store_id", "category", "channel"], as_index=False)["net_sales"].sum()
    goals["week_start"] = goals["week_start"].map(lambda d: d + timedelta(days=364))
    goals["sales_goal"] = (goals["net_sales"] * rng.uniform(1.04, 1.18, len(goals))).round(2)
    goals = goals.drop(columns="net_sales")

    # 周度库存：VELOUR 目标周在 S01 缺货
    weeks = sorted({d - timedelta(days=d.weekday()) for d in days if d >= date(2026, 9, 1)})
    avail = pd.MultiIndex.from_product([weeks, [s[0] for s in STORES], items["item_id"]],
                                       names=["week_start", "store_id", "item_id"]).to_frame(index=False)
    avail["available_pct"] = rng.uniform(88, 100, len(avail)).round(1)
    velour = set(items.loc[items["brand"] == "VELOUR", "item_id"])
    mask = (avail["store_id"] == "S01") & avail["item_id"].isin(velour) & (avail["week_start"] == date(2026, 10, 26))
    avail.loc[mask, "available_pct"] = 32.0

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).unlink(missing_ok=True)
    con = duckdb.connect(str(path))
    dim_items = items[["item_id", "item_name", "is_new", "is_hero", "is_member_exclusive"]]
    for name, df in [("fact_sales", sales), ("fact_traffic", traffic_df), ("fact_goal", goals),
                     ("dim_store", stores_df), ("dim_item", dim_items), ("fact_availability", avail)]:
        con.register("_df", df)
        con.execute(f"CREATE TABLE {name} AS SELECT * FROM _df")
        con.unregister("_df")
    rows = con.execute("SELECT count(*) FROM fact_sales").fetchone()[0]
    con.close()
    return rows
