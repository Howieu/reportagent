"""把两份真实公开数据集装进一个数仓。

- Olist（巴西电商订单）：驱动周度诊断报告。没有目标、客流和库存，这些指标不显示，也不伪造。
- RetailRocket（电商行为日志）：驱动漏斗分析。

两份数据来自不同公司，品类和用户无法关联，产品里分开展示。

Olist 没有实体门店和销售渠道，这里用最接近的真实字段映射：
  门店 → 卖家所在州；渠道 → 同州或跨州配送；二级渠道 → 买家所在大区；
  品类 → 由 71 个原始类目归并的大类（规则见 group_of）；子类 → 原始类目；品牌 → 卖家。
"""

from pathlib import Path

import duckdb
import pandas as pd

# 2018-08-26 之后订单骤减（数据集截止），2017 年前样本太少。这里只留完整周。
START, END = "2017-01-01", "2018-08-26"
NEW_SINCE = "2018-01-01"

STATES = {
    "SP": ("圣保罗州", "东南"), "RJ": ("里约热内卢州", "东南"), "MG": ("米纳斯吉拉斯州", "东南"), "ES": ("圣埃斯皮里图州", "东南"),
    "PR": ("巴拉那州", "南部"), "SC": ("圣卡塔琳娜州", "南部"), "RS": ("南里奥格兰德州", "南部"),
    "BA": ("巴伊亚州", "东北"), "PE": ("伯南布哥州", "东北"), "CE": ("塞阿拉州", "东北"), "MA": ("马拉尼昂州", "东北"),
    "PB": ("帕拉伊巴州", "东北"), "RN": ("北里奥格兰德州", "东北"), "PI": ("皮奥伊州", "东北"), "SE": ("塞尔希培州", "东北"),
    "AL": ("阿拉戈斯州", "东北"), "GO": ("戈亚斯州", "中西"), "DF": ("联邦区", "中西"), "MS": ("南马托格罗索州", "中西"),
    "MT": ("马托格罗索州", "中西"), "AM": ("亚马孙州", "北部"), "PA": ("帕拉州", "北部"), "RO": ("朗多尼亚州", "北部"),
    "AC": ("阿克里州", "北部"), "AP": ("阿马帕州", "北部"), "RR": ("罗赖马州", "北部"), "TO": ("托坎廷斯州", "北部"),
}
GROUPS = [
    ("美妆个护", ("health_beauty", "perfumery", "diapers_and_hygiene")),
    ("时尚配饰", ("fashio", "watches", "luggage", "fashion", "cool_stuff")),
    ("家居家具", ("furniture", "bed_bath", "housewares", "home_", "kitchen", "garden", "flowers", "christmas", "la_cuisine")),
    ("家电数码", ("appliances", "computers", "electronics", "telephony", "tablets", "consoles", "audio", "cine_photo",
                  "fixed_telephony", "signaling", "air_conditioning", "small_appliances")),
    ("运动母婴", ("sports", "baby", "toys", "pet_shop")),
    ("文娱办公", ("books", "cds", "dvds", "music", "art", "party", "stationery", "office", "musical", "agro", "industry")),
    ("建材工具", ("construction", "auto", "security")),
    ("食品饮料", ("food", "drinks")),
]


def group_of(name):
    name = str(name)
    for group, prefixes in GROUPS:
        if any(name.startswith(p) or p in name for p in prefixes):
            return group
    return "其他"


def load_olist(con, src):
    src = Path(src)
    def read(name):
        return f"read_csv_auto('{(src / name).as_posix()}', header=true)"

    translate = con.execute(f"SELECT * FROM {read('product_category_name_translation.csv')}").df()
    translate.columns = ["raw", "english"]
    groups = translate.assign(category=translate["english"].map(group_of))
    con.register("_cats", groups)
    con.execute(f"""
    CREATE OR REPLACE TABLE warehouse.fact_sales AS
    WITH base AS (
      SELECT CAST(o.order_purchase_timestamp AS DATE) AS biz_date, s.seller_state AS store_id,
             c.customer_state, i.order_id, i.product_id AS item_id, i.seller_id, i.price AS net_sales,
             COALESCE(t.english, p.product_category_name, 'unknown') AS subcategory, COALESCE(t.category, '其他') AS category
      FROM {read('olist_order_items_dataset.csv')} i
      JOIN {read('olist_orders_dataset.csv')} o ON i.order_id = o.order_id
      JOIN {read('olist_sellers_dataset.csv')} s ON i.seller_id = s.seller_id
      JOIN {read('olist_customers_dataset.csv')} c ON o.customer_id = c.customer_id
      LEFT JOIN {read('olist_products_dataset.csv')} p ON i.product_id = p.product_id
      LEFT JOIN _cats t ON p.product_category_name = t.raw
      WHERE o.order_status NOT IN ('canceled', 'unavailable')
        AND CAST(o.order_purchase_timestamp AS DATE) BETWEEN DATE '{START}' AND DATE '{END}'
    )
    SELECT biz_date, store_id,
           CASE WHEN customer_state = store_id THEN '同州' ELSE '跨州' END AS channel,
           customer_state AS customer_state, category, subcategory,
           'S-' || substr(seller_id, 1, 6) AS brand, item_id, net_sales, 1 AS qty, order_id
    FROM base
    """)
    regions = pd.DataFrame([(k, v[1]) for k, v in STATES.items()], columns=["state", "region"])
    con.register("_regions", regions)
    con.execute("""
    CREATE OR REPLACE TABLE warehouse.fact_sales AS
    SELECT f.biz_date, f.store_id, f.channel, COALESCE(r.region, '其他') || '买家' AS subchannel, f.category, f.subcategory,
           f.brand, f.item_id, f.net_sales, f.qty, f.order_id
    FROM warehouse.fact_sales f LEFT JOIN _regions r ON f.customer_state = r.state
    """)
    stores = pd.DataFrame([(k, f"{v[0]}（{k}）", "ALL", v[1], v[0]) for k, v in STATES.items()],
                          columns=["store_id", "store_name", "peer_group", "region", "city"])
    con.register("_stores", stores)
    con.execute("CREATE OR REPLACE TABLE warehouse.dim_store AS SELECT * FROM _stores WHERE store_id IN (SELECT DISTINCT store_id FROM warehouse.fact_sales)")
    con.execute(f"""
    CREATE OR REPLACE TABLE warehouse.dim_item AS
    SELECT item_id, any_value(subcategory) || ' ' || substr(item_id, 1, 6) AS item_name,
           min(biz_date) >= DATE '{NEW_SINCE}' AS is_new
    FROM warehouse.fact_sales GROUP BY item_id
    """)
    for name in ("_cats", "_regions", "_stores"):
        con.unregister(name)


def _ancestors(tree):
    """叶子品类 → (一级, 二级)。"""
    parents = dict(zip(tree["categoryid"], tree["parentid"]))
    out = {}
    for cat in tree["categoryid"]:
        path, current, seen = [], cat, set()
        while current == current and current in parents and current not in seen:  # current == current 排除 NaN
            seen.add(current)
            path.append(current)
            current = parents[current]
        path.reverse()
        out[int(cat)] = (int(path[0]), int(path[1]) if len(path) > 1 else int(path[0]))
    return out


def load_retailrocket(con, src):
    src = Path(src)
    tree = pd.read_csv(src / "category_tree.csv")
    rows = [(leaf, f"品类 {a}", f"品类 {b}", f"品类 {leaf}") for leaf, (a, b) in _ancestors(tree).items()]
    con.register("_tree", pd.DataFrame(rows, columns=["leaf", "category_l1", "category_l2", "category_id"]))
    parts = ", ".join(f"'{(src / f).as_posix()}'" for f in ("item_properties_part1.csv", "item_properties_part2.csv"))
    con.execute(f"""
    CREATE OR REPLACE TABLE warehouse.fact_funnel AS
    WITH item_cat AS (
      SELECT itemid, TRY_CAST(arg_max(value, timestamp) AS BIGINT) AS leaf
      FROM read_csv_auto([{parts}], header=true, types={{'value': 'VARCHAR'}})
      WHERE property = 'categoryid' GROUP BY itemid
    )
    SELECT CAST(make_timestamp(e.timestamp * 1000) AS DATE) AS biz_date, CAST(e.visitorid AS VARCHAR) AS visitor_id,
           e.event, CAST(e.itemid AS VARCHAR) AS item_id,
           COALESCE(t.category_l1, '未分类') AS category_l1, COALESCE(t.category_l2, '未分类') AS category_l2,
           COALESCE(t.category_id, '未分类') AS category_id
    FROM read_csv_auto('{(src / 'events.csv').as_posix()}', header=true) e
    LEFT JOIN item_cat c ON e.itemid = c.itemid
    LEFT JOIN _tree t ON c.leaf = t.leaf
    """)
    con.unregister("_tree")


def build(path="data/real.duckdb", olist="data/raw/olist", retailrocket="data/raw/retailrocket"):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute("CREATE SCHEMA IF NOT EXISTS warehouse")
    load_olist(con, olist)
    load_retailrocket(con, retailrocket)
    summary = {t: con.execute(f"SELECT count(*) FROM warehouse.{t}").fetchone()[0] for t in ("fact_sales", "dim_store", "dim_item", "fact_funnel")}
    con.close()
    return summary
