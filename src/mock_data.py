# -*- coding: utf-8 -*-
"""
Mock 数据生成器
=================
按 notebook 依赖的 5 张 ODPS 预聚合表的真实 schema 生成仿真数据，字段名与线上表完全一致，
保证分析代码零改动迁移。固定随机种子，结果可复现。

生成的 5 份数据集（缓存为 data/*.pkl）：
  1. channel    —— tmp_online_pdf_hfbanalysis_weekly_saleschannel（渠道周表）
  2. funnel     —— tmp_online_pdf_hfbanalysis_weekly_userfunnel（线上漏斗周表）
  3. drilldown  —— tmp_online_pdf_hfbanalysis_weekly_articledeepdive（PA/Family/Article 下钻周表）
  4. pa_pred    —— online_pa_prediction_fy25_v2_online（PA 级日粒度预测特征表）
  5. article_pred —— online_pa_prediction_fy25_v2_online_article（Article 级日粒度预测特征表）

设计原则：数据是"有故事"的——每个 HFB 预设 2 个显著下降 PA、2 个显著上升 PA，
部分商品预设缺货 / 环比趋势显著向上，保证归因、预测、潜力识别每次演示都有看点。
"""

import base64
import hashlib
import json
import os

import numpy as np
import pandas as pd

SEED = 42
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

HFB_LIST = [f"{i:02d}" for i in range(1, 11)]          # HFB 01-10
PA_PER_HFB = 6
FAMILY_PER_PA = 4
ARTICLE_PER_FAMILY = 6

FAMILY_POOL = [
    "EKHOLMA", "FINTSEN", "LUDDHAGTORN", "BJÅRSEN", "HULN", "SKOVELSJÖN",
    "LUDDROS", "ÄNGSKORN", "VALLENTUNA", "KIVIK", "FRIHETEN", "LANDSKRONA",
]
LABEL_POOL = ["4A1K", "NLP", "News", "Top30", "Basic", "FamilyOffer"]

# 预测特征表使用的驱动特征（sale_net_amt 由这些特征显式生成，SHAP 归因才有真实信号）
DRIVER_FEATURES = ["daily_pip", "conv_rate", "avg_price", "discount_depth", "stock_rate"]

# 固定的"当前周"结束日（mock 数据的时间锚点，与周次选择解耦）
END_DATE = pd.Timestamp("2025-07-06")
DAYS = 450


def _rng(*keys):
    """按 key 派生独立随机流，保证任一实体改动不影响其他实体。"""
    payload = json.dumps(
        [SEED, *keys], ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    stable_seed = int.from_bytes(
        hashlib.blake2b(payload, digest_size=8).digest(), "big"
    ) % (2**32)
    return np.random.default_rng(stable_seed)


def _placeholder_img(text, bg="#0058a3", fg="#ffffff"):
    """生成 base64 内联 SVG 占位商品图（离线可用，下载的 HTML 中也能正常显示）。"""
    svg = (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='300' height='200'>"
        f"<rect width='300' height='200' fill='{bg}' rx='8'/>"
        f"<text x='150' y='105' font-size='20' fill='{fg}' text-anchor='middle'"
        f" font-family='Arial'>{text}</text></svg>"
    )
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


# ---------------------------------------------------------------------------
# 1. 渠道周表
# ---------------------------------------------------------------------------
def _gen_channel() -> pd.DataFrame:
    rows = []
    for hfb in HFB_LIST:
        r = _rng("channel", hfb)
        # 一级渠道：ONLINE / OFFLINE，Weekly 与 Rolling 4wks 各一行
        for channel in ["ONLINE", "OFFLINE"]:
            base_goal = float(r.normal(95, 10))
            base_ly = float(r.normal(100, 15))
            for date_type in ["Weekly", "Rolling 4wks"]:
                jitter = r.normal(0, 3, 3) if date_type == "Rolling 4wks" else np.zeros(3)
                rows.append({
                    "hfb_no": hfb, "sales_channel": channel, "date_type": date_type,
                    "sales_ind_goal": base_goal + jitter[0],
                    "sales_ind_ly": base_ly + jitter[1],
                    "qty_ind_ly": base_ly + jitter[2] + r.normal(5, 8),
                })
        # 二级渠道：DTC / RCMP / TMALL（仅 Weekly，与原 notebook 口径一致）
        shares = r.dirichlet([5, 3, 2])
        for i, channel in enumerate(["DTC", "RCMP", "TMALL"]):
            rows.append({
                "hfb_no": hfb, "sales_channel": channel, "date_type": "Weekly",
                "sales_share": float(shares[i]),
                "sales_ind_goal": float(r.normal(95, 12)),
                "sales_ind_ly": float(r.normal(100, 20)),
                "qty_ind_ly": float(r.normal(100, 20)),
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 2. 线上漏斗周表
# ---------------------------------------------------------------------------
def _gen_funnel() -> pd.DataFrame:
    rows = []
    for hfb in HFB_LIST:
        r = _rng("funnel", hfb)
        weekly = {
            "sales_ind_ly": r.normal(105, 18), "qty_ind_ly": r.normal(105, 15),
            "pip_ind_ly": r.normal(105, 20), "ticket_ind_ly": r.normal(105, 15),
            "ticket_conv_ind_ly": r.normal(100, 10), "atc_ind_ly": r.normal(105, 18),
            "pip_conv_ind_ly": r.normal(100, 8), "checkout_ind_ly": r.normal(105, 15),
            "checkout_conv_ind_ly": r.normal(100, 8), "buyer_ind_ly": r.normal(105, 15),
            "buy_conv_ind_ly": r.normal(100, 8), "atv_ind_ly": r.normal(100, 8),
            "itemperticket_ty": r.normal(2.0, 0.2), "priceperitem_ty": r.normal(85, 8),
        }
        weekly["itemperticket_lyr"] = weekly["itemperticket_ty"] / r.normal(1.0, 0.05)
        weekly["itemperticket_ind_ly"] = weekly["itemperticket_ty"] / weekly["itemperticket_lyr"] * 100
        weekly["priceperitem_lyr"] = weekly["priceperitem_ty"] / r.normal(1.0, 0.05)
        weekly["priceperitem_ind_ly"] = weekly["priceperitem_ty"] / weekly["priceperitem_lyr"] * 100

        for date_type in ["Weekly", "Rolling 4wks"]:
            row = {"hfb_no": hfb, "date_type": date_type}
            for k, v in weekly.items():
                row[k] = float(v if date_type == "Weekly" else v + r.normal(0, 2))
            rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 3. PA / Family / Article 下钻周表
# ---------------------------------------------------------------------------
def _ind_metrics(rng, base_ly):
    """生成一组 focus=sales / qty 的 ind / dif 字段。"""
    out = {}
    for base in ["sales", "qty"]:
        ind_ly = base_ly + rng.normal(0, 5)
        out[f"{base}_ind_ly"] = float(ind_ly)
        out[f"{base}_exc_ind_ly"] = float(ind_ly + rng.normal(0, 6))      # 排除 News/UTG
        dif = (ind_ly - 100) * 1000 * rng.uniform(0.5, 1.5)
        out[f"{base}_dif"] = float(dif)
        out[f"{base}_exc_dif"] = float(dif * rng.uniform(0.8, 1.0))
        out[f"{base}_offline_exc_dif"] = float(dif * rng.uniform(0.3, 0.7))
    return out


def _gen_drilldown() -> pd.DataFrame:
    rows = []
    for hfb in HFB_LIST:
        r = _rng("drill", hfb)
        pa_ids = [f"{hfb}{i}" for i in range(1, PA_PER_HFB + 1)]
        # 故事线预设：前 2 个 PA 显著下降，中间 2 个显著上升，其余平淡
        pa_story = {pa_ids[0]: -80_000, pa_ids[1]: -50_000,
                    pa_ids[2]: 120_000, pa_ids[3]: 60_000}
        families = list(r.choice(FAMILY_POOL, size=FAMILY_PER_PA, replace=False))

        for pa in pa_ids:
            dif_target = pa_story.get(pa, float(r.normal(0, 8_000)))
            pa_base_ly = 100 + dif_target / 2500.0

            # --- PA 行（TOTAL/TOTAL），Weekly + Rolling ---
            for date_type in ["Weekly", "Rolling 4wks"]:
                m = _ind_metrics(r, pa_base_ly if date_type == "Weekly" else pa_base_ly * 0.6 + 40)
                rows.append({"hfb_no": hfb, "pa_no": pa, "item_family": "TOTAL",
                             "item_id": "TOTAL", "date_type": date_type, **m})

            # --- Family 行（item_id == 'TOTAL'）---
            fam_weights = r.dirichlet(np.ones(FAMILY_PER_PA))
            for fi, family in enumerate(families):
                fam_dif = dif_target * fam_weights[fi]
                fam_base_ly = 100 + fam_dif / 600.0
                for date_type in ["Weekly", "Rolling 4wks"]:
                    m = _ind_metrics(r, fam_base_ly if date_type == "Weekly" else fam_base_ly * 0.6 + 40)
                    rows.append({"hfb_no": hfb, "pa_no": pa, "item_family": family,
                                 "item_id": "TOTAL", "date_type": date_type, **m})

                # --- Article 行 ---
                art_weights = r.dirichlet(np.ones(ARTICLE_PER_FAMILY))
                for ai in range(ARTICLE_PER_FAMILY):
                    item_id = str(int(r.integers(10_000_000, 99_999_999)))
                    art_dif = fam_dif * art_weights[ai]
                    art_base_ly = 100 + art_dif / 300.0
                    label = LABEL_POOL[ai % len(LABEL_POOL)]
                    # 部分商品预设"潜力剧本"：临时缺货 or 环比趋势显著向上
                    is_star = art_dif > 8_000          # 显著上升
                    is_stockout = art_dif < -8_000     # 显著下降 → 归因于缺货
                    weekly_avail = 35.0 if is_stockout else float(r.uniform(85, 100))
                    rolling_avail = 0.0 if (is_stockout and r.random() < 0.3) else float(r.uniform(85, 100))
                    weekly_ly = art_base_ly + (60 if is_star else 0)
                    rolling_ly = art_base_ly
                    qty_1k_cus = 130.0 if is_star else (80.0 if is_stockout else float(r.uniform(90, 110)))

                    for date_type in ["Weekly", "Rolling 4wks"]:
                        ly = weekly_ly if date_type == "Weekly" else rolling_ly
                        m = _ind_metrics(r, ly)
                        rows.append({
                            "hfb_no": hfb, "pa_no": pa, "item_family": family,
                            "item_id": item_id, "date_type": date_type, **m,
                            "item_name": f"{family} 商品 {ai + 1}",
                            "product_label_ty": label,
                            "pic_url": _placeholder_img(family),
                            "available_percent": weekly_avail if date_type == "Weekly" else rolling_avail,
                            "qty_1k_cus_ind_ly": qty_1k_cus,
                        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 4 & 5. 日粒度预测特征表（PA 级 / Article 级）
# ---------------------------------------------------------------------------
def _gen_daily(entity_ids, entity_col):
    """sale_net_amt 由驱动特征显式生成，保证 SHAP / 相关性归因有真实信号。"""
    dates = pd.date_range(END_DATE - pd.Timedelta(days=DAYS - 1), END_DATE, freq="D")
    dow_season = np.array([0.85, 0.9, 0.95, 1.0, 1.1, 1.3, 1.2])   # 周末高峰
    frames = []
    for eid in entity_ids:
        r = _rng("daily", eid)
        n = len(dates)
        daily_pip = r.lognormal(7, 0.3, n)
        conv_rate = np.clip(r.normal(0.08, 0.015, n), 0.01, 0.2)
        avg_price = np.clip(r.normal(80, 10, n), 20, 300)
        discount = np.where(r.random(n) < 0.15, r.uniform(0.1, 0.3, n), 0.0)   # 15% 日子促销
        stock = np.clip(r.normal(0.95, 0.08, n), 0.3, 1.0)
        sale = (daily_pip * conv_rate * avg_price * (1 + discount)
                * dow_season[dates.dayofweek] * stock / 100.0 * 50)
        sale *= r.lognormal(0, 0.1, n)                              # 噪声
        frames.append(pd.DataFrame({
            entity_col: eid, "payment_date": dates,
            "sale_net_amt": sale, "daily_pip": daily_pip,
            "conv_rate": conv_rate, "avg_price": avg_price,
            "discount_depth": discount, "stock_rate": stock,
            "week_of_year": dates.isocalendar().week.astype(int),
        }))
    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
_CACHE_FILES = {
    "channel": "channel.pkl",
    "funnel": "funnel.pkl",
    "drilldown": "drilldown.pkl",
    "pa_pred": "pa_pred.pkl",
    "article_pred": "article_pred.pkl",
}


def load_all(force_regenerate: bool = False) -> dict:
    """加载（或首次生成并缓存）全部 5 份 mock 数据集。"""
    os.makedirs(DATA_DIR, exist_ok=True)
    paths = {k: os.path.join(DATA_DIR, v) for k, v in _CACHE_FILES.items()}
    if not force_regenerate and all(os.path.exists(p) for p in paths.values()):
        return {k: pd.read_pickle(p) for k, p in paths.items()}

    channel = _gen_channel()
    funnel = _gen_funnel()
    drilldown = _gen_drilldown()

    pa_ids = sorted(drilldown["pa_no"].unique())
    article_ids = sorted(drilldown.loc[drilldown["item_id"] != "TOTAL", "item_id"].unique())
    pa_pred = _gen_daily(pa_ids, "pa_no")
    article_pred = _gen_daily(article_ids, "item_id")

    data = {"channel": channel, "funnel": funnel, "drilldown": drilldown,
            "pa_pred": pa_pred, "article_pred": article_pred}
    for k, df in data.items():
        df.to_pickle(paths[k])
    return data


if __name__ == "__main__":
    datasets = load_all(force_regenerate=True)
    for name, df in datasets.items():
        print(f"{name}: {df.shape}")
