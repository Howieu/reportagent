"""确定性诊断：报告和对话里的 explain_change 都走这里，数字只由代码计算。

下钻截断（贡献度阈值、条数上限）和潜力规则来自原 notebook 的
pa_for_human / family_for_human / article_for_human / potential_recognition。
"""

import math
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from .warehouse import DataUnavailable, Warehouse, build_periods

SUB_LIMIT, SUB_THRESHOLD = 8, 0.9
FAMILY_LIMIT, FAMILY_THRESHOLD = 5, 0.7
ITEM_LIMIT = 1
# 原 PDF 曾出现 LY=1、TY=9 的“指数 900，潜力高”。去年基数太小的商品不判潜力，阈值可调。
MIN_BASE_FOR_POTENTIAL = 5
POTENTIAL_TREND_GAP = 50
LOW_STOCK_PCT = 50


def idx(a, b):
    """指数：a / b × 100；基数 ≤ 0 时无意义，返回 None。"""
    return None if b is None or b <= 0 or a is None else a / b * 100


def ratio(a, b):
    return None if not b or b <= 0 else a / b


def diff(a, b):
    return None if a is None or b is None else a - b


def _row(df, **where):
    mask = pd.Series(True, index=df.index)
    for k, v in where.items():
        mask &= df[k] == v
    return df[mask].sum(numeric_only=True)


def _is_true(value):
    return str(value).strip().lower() in {"1", "true", "t", "y", "yes"}


def _rank(frame, col, store, peers):
    ordered = frame[frame["store"].isin(peers)].sort_values(col, ascending=False)["store"].tolist()
    return ordered.index(store) + 1 if store in ordered else None, ordered


def _overall(total, whole, goals, store, peers, stores_df):
    names = dict(zip(stores_df["store"], stores_df["name"]))
    others = [s for s in peers if s != store]
    goal_col = "goal__{}"
    out = {}
    for key in ("week", "r4", "ytd"):
        own = _row(total, store=store)
        comp = _row(total[total["store"].isin(others)])
        own_all = _row(whole, store=store)
        group_all = _row(whole[whole["store"].isin(peers)])
        group = _row(total[total["store"].isin(peers)])
        own_goal = goals[goals["store"] == store][goal_col.format(key)].sum() if goals is not None else 0
        comp_goal = goals[goals["store"].isin(others)][goal_col.format(key)].sum() if goals is not None else 0
        sales, sales_ly = own[f"sales__{key}"], own[f"sales__{key}_ly"]
        rank, order = _rank(total, f"sales__{key}", store, peers)
        store_rank, _ = _rank(whole, f"sales__{key}", store, peers)
        prev = order[rank - 2] if rank and rank > 1 else None
        prev_gap = None
        if prev:
            prev_gap = _row(total, store=prev)[f"sales__{key}"] - sales
        share = ratio(sales, group[f"sales__{key}"])
        store_share = ratio(own_all[f"sales__{key}"], group_all[f"sales__{key}"])
        out[key] = {
            "sales": sales,
            "sales_vs_goal": idx(sales, own_goal),
            "sales_vs_goal_comp": idx(comp[f"sales__{key}"], comp_goal),
            "sales_vs_ly": idx(sales, sales_ly),
            "sales_vs_ly_comp": idx(comp[f"sales__{key}"], comp[f"sales__{key}_ly"]),
            "qty_vs_ly": idx(own[f"qty__{key}"], own[f"qty__{key}_ly"]),
            "qty_vs_ly_comp": idx(comp[f"qty__{key}"], comp[f"qty__{key}_ly"]),
            "share": share * 100 if share is not None else None,
            "share_vs_store": diff(share, store_share) * 100 if share is not None and store_share else None,
            "rank": rank,
            "rank_vs_store": diff(rank, store_rank),
            "peer_count": len(peers),
            "prev_store": names.get(prev, prev),
            "prev_gap": prev_gap,
        }
    return out


def _channels(by_channel, subs, goals, store, peers):
    others = [s for s in peers if s != store]
    rows = []
    total = by_channel[by_channel["store"] == store]["sales__week"].sum()
    for channel in sorted(by_channel["channel"].unique()):
        own = _row(by_channel, store=store, channel=channel)
        comp = _row(by_channel[by_channel["store"].isin(others) & (by_channel["channel"] == channel)])
        goal = comp_goal = 0
        if goals is not None:
            g = goals[goals["channel"] == channel]
            goal = g[g["store"] == store]["goal__week"].sum()
            comp_goal = g[g["store"].isin(others)]["goal__week"].sum()
        peer_rows = by_channel[by_channel["channel"] == channel]
        rank, _ = _rank(peer_rows, "sales__week", store, peers)
        item = {
            "channel": channel, "sales": own["sales__week"],
            "share": (ratio(own["sales__week"], total) or 0) * 100,
            "sales_vs_goal": idx(own["sales__week"], goal),
            "sales_vs_goal_comp": idx(comp["sales__week"], comp_goal),
            "sales_vs_ly": idx(own["sales__week"], own["sales__week_ly"]),
            "sales_vs_ly_comp": idx(comp["sales__week"], comp["sales__week_ly"]),
            "qty_vs_ly": idx(own["qty__week"], own["qty__week_ly"]),
            "qty_vs_ly_comp": idx(comp["qty__week"], comp["qty__week_ly"]),
            "rank": rank, "subs": [], "pick": None, "pick_word": None,
        }
        if subs is not None:
            s = subs[subs["channel"] == channel]
            for _, r in s.sort_values("sales__week", ascending=False).iterrows():
                item["subs"].append({
                    "name": r["subchannel"], "sales": r["sales__week"], "sales_ly": r["sales__week_ly"],
                    "share": (ratio(r["sales__week"], total) or 0) * 100,
                    "sales_vs_ly": idx(r["sales__week"], r["sales__week_ly"]),
                    "qty_vs_ly": idx(r["qty__week"], r["qty__week_ly"]),
                })
            valid = [x for x in item["subs"] if x["sales_vs_ly"] is not None]
            if valid:
                up = (item["sales_vs_ly"] or 0) >= 100
                pick = max(valid, key=lambda x: x["sales_vs_ly"]) if up else min(valid, key=lambda x: x["sales_vs_ly"])
                item["pick"], item["pick_word"] = pick["name"], "最佳" if up else "最差"
        rows.append(item)
    return rows


TREE_KEYS = ("sales", "qty", "tickets", "ab", "ai", "price", "traffic", "cr")


def _tree_values(row, traffic, key):
    sales, qty, tickets = row[f"sales__{key}"], row[f"qty__{key}"], row[f"tickets__{key}"]
    t = traffic[f"visitors__{key}"] if traffic is not None else None
    return {
        "sales": sales, "qty": qty, "tickets": tickets,
        "ab": ratio(sales, tickets), "ai": ratio(qty, tickets), "price": ratio(sales, qty),
        "traffic": t if t else None, "cr": ratio(tickets, t) if t else None,
    }


def _tree(by_channel, traffic_df, store, peers, channel):
    def rows_for(stores):
        row = _row(by_channel[by_channel["store"].isin(stores) & (by_channel["channel"] == channel)])
        tr = None
        if traffic_df is not None:
            tr = _row(traffic_df[traffic_df["store"].isin(stores) & (traffic_df["channel"] == channel)])
        return row, tr

    own, own_tr = rows_for([store])
    comp, comp_tr = rows_for([s for s in peers if s != store])
    ty, ly = _tree_values(own, own_tr, "week"), _tree_values(own, own_tr, "week_ly")
    cty, cly = _tree_values(comp, comp_tr, "week"), _tree_values(comp, comp_tr, "week_ly")
    prev = _tree_values(own, own_tr, "w1")
    nodes = {}
    for k in TREE_KEYS:
        if ty[k] is None and ly[k] is None:
            continue
        vs = idx(ty[k], ly[k])
        nodes[k] = {
            "ty": ty[k], "ly": ly[k], "vs_ly": vs,
            "vs_comp": diff(vs, idx(cty[k], cly[k])),
            "wow": diff(idx(ty[k], prev[k]), 100),
        }

    # 趋势：近 4 周各自的同比指数
    trend = {k: [] for k in nodes}
    labels = []
    for offset, key in [(3, "w3"), (2, "w2"), (1, "w1"), (0, "week")]:
        a, b = _tree_values(own, own_tr, key), _tree_values(own, own_tr, f"{key}_ly")
        labels.append(key)
        for k in nodes:
            trend[k].append(idx(a[k], b[k]))

    # 对数分解：ln(Sales) = ln(Traffic) + ln(CR) + ln(AI) + ln(Price)，各项可加总
    factors = ["traffic", "cr", "ai", "price"] if "traffic" in nodes else ["tickets", "ai", "price"]
    sales_ln = math.log(ty["sales"] / ly["sales"]) if ty["sales"] > 0 and ly["sales"] > 0 else None
    contributions = []
    for f in factors:
        n = nodes.get(f)
        if n and n["vs_ly"] and n["vs_ly"] > 0 and sales_ln:
            ln = math.log(n["vs_ly"] / 100)
            contributions.append({"factor": f, "vs_ly": n["vs_ly"], "ln": ln, "share": ln / sales_ln * 100})
    driver = None
    if contributions and sales_ln:
        aligned = [c for c in contributions if c["ln"] * sales_ln > 0]
        driver = max(aligned or contributions, key=lambda c: abs(c["ln"]))["factor"]
    return {"nodes": nodes, "trend": trend, "trend_labels": labels, "contributions": contributions, "driver": driver}


def _pick(frame, col, direction, limit, threshold):
    """按方向筛选并计算贡献度，累计到阈值或条数上限为止。"""
    picked = frame[frame[col] < 0] if direction == "down" else frame[frame[col] > 0]
    total = picked[col].abs().sum()
    if picked.empty or total == 0:
        return []
    picked = picked.assign(contribution=picked[col].abs() / total).sort_values("contribution", ascending=False)
    rows, cumulative = [], 0.0
    for _, row in picked.iterrows():
        if len(rows) >= limit or cumulative >= threshold:
            break
        rows.append(row)
        cumulative += float(row["contribution"])
    return rows


def _level(own, peers_df, keys, m, channel):
    """把商品粒度上卷到 keys 粒度，算诊断指标。"""
    focus = own[own["channel"] == channel]
    other = own[own["channel"] != channel]
    agg = {f"{m}__{p}": "sum" for p in ("week", "week_ly", "r4", "r4_ly")}
    frame = focus.groupby(keys, as_index=False).agg(agg)
    core = focus[~focus["excluded"]].groupby(keys, as_index=False).agg(agg)
    other_core = other[~other["excluded"]].groupby(keys, as_index=False).agg(agg)
    comp = peers_df.groupby(keys, as_index=False).agg(agg)

    frame = frame.merge(core, on=keys, how="left", suffixes=("", "_core")).fillna(0)
    frame = frame.merge(other_core, on=keys, how="left", suffixes=("", "_other")).fillna(0)
    frame = frame.merge(comp, on=keys, how="left", suffixes=("", "_comp")).fillna(0)
    frame["dif"] = frame[f"{m}__week_core"] - frame[f"{m}__week_ly_core"]
    frame["dif_other"] = frame[f"{m}__week_other"] - frame[f"{m}__week_ly_other"]
    return frame


def _describe(row, m, avg_share, category_total):
    ind = idx(row[f"{m}__week"], row[f"{m}__week_ly"])
    r4 = idx(row[f"{m}__r4"], row[f"{m}__r4_ly"])
    comp = idx(row[f"{m}__week_comp"], row[f"{m}__week_ly_comp"])
    own = row[f"{m}__week"]
    group = own + row[f"{m}__week_comp"]
    core_ind = idx(row[f"{m}__week_core"], row[f"{m}__week_ly_core"])
    return {
        "ty": own, "ly": row[f"{m}__week_ly"], "vs_ly": ind, "vs_comp": diff(ind, comp), "vs_r4": diff(ind, r4),
        "share": (own / group * 100) if group > 0 else None,
        "category_share": (own / category_total * 100) if category_total > 0 else None,
        "core_vs_ly": core_ind if abs((core_ind or 0) - (ind or 0)) >= 0.5 else None,
        "dif": row["dif"], "dif_other": row["dif_other"],
        "contribution": float(row["contribution"]) * 100 if "contribution" in row else None,
        "avg_share": avg_share,
    }


def potential(info, direction, qty_1k_vs_ly, available=None, available_r4=None):
    """潜力规则（来自 notebook 的 potential_recognition），返回 (是否高潜, 理由)。"""
    if info["ly"] < MIN_BASE_FOR_POTENTIAL:
        return False, "去年基数太小"
    gap = info["vs_r4"]
    if direction == "down":
        if available_r4 == 0:
            return False, "连续 4 周缺货"
        if available is not None and available < LOW_STOCK_PCT:
            return True, f"临时缺货（可售率 {available:.0f}%）"
        if qty_1k_vs_ly is not None and qty_1k_vs_ly > 100:
            return False, "单客购买量高于去年"
        if gap is not None and gap <= -POTENTIAL_TREND_GAP:
            return True, "环比趋势显著向下"
        if info["share"] is not None and info["avg_share"] is not None and info["share"] < info["avg_share"]:
            return True, "门店占比未达品类平均"
        return False, ""
    if qty_1k_vs_ly is not None and qty_1k_vs_ly < 100:
        return False, "单客购买量低于去年"
    if gap is not None and gap >= POTENTIAL_TREND_GAP:
        return True, "环比趋势显著向上"
    return False, ""


def _drill(wh: Warehouse, periods, store, category, channel, others, m, tree):
    keys = {k: periods[k] for k in ("week", "week_ly", "r4", "r4_ly")}
    dims = ["subcategory", "family", "item", "channel"]
    own = wh.sales(dims, keys, {"store": store, "category": category}, "下钻：本店商品粒度", tickets=False)
    comp = wh.sales(dims[:3], keys, {"store": others, "category": category, "channel": channel},
                    "下钻：对标门店商品粒度", tickets=False) if others else own.iloc[0:0].drop(columns="channel")
    attrs = wh.items(sorted(set(own["item"])))
    own = own.merge(attrs, on="item", how="left")
    own["excluded"] = own["exclude"].map(_is_true) if "exclude" in own else False

    subs = _level(own, comp, ["subcategory"], m, channel)
    families = _level(own, comp, ["subcategory", "family"], m, channel)
    items = _level(own, comp, ["subcategory", "family", "item"], m, channel)
    name_of = attrs.set_index("item")["name"].to_dict() if "name" in attrs else {}
    image_of = attrs.set_index("item")["image_url"].to_dict() if "image_url" in attrs else {}

    category_total = subs[f"{m}__week"].sum()
    group_total = category_total + subs[f"{m}__week_comp"].sum()
    avg_share = category_total / group_total * 100 if group_total > 0 else None

    stock = {}
    if wh.semantic.has("availability"):
        selected = sorted(set(items["item"]))
        if selected:
            df = wh.aggregate("availability", ["item"], {"available": ("avg", "available_pct")},
                              {"week": keys["week"], "r4": keys["r4"]}, {"store": store, "item": selected}, "库存可售率")
            stock = {r["item"]: (r["available__week"], r["available__r4"]) for _, r in df.iterrows()}

    qty_1k = None
    if "traffic" in tree["nodes"]:
        traffic = tree["nodes"]["traffic"]["vs_ly"]
        qty = tree["nodes"]["qty"]["vs_ly"]
        qty_1k = idx(qty, traffic)

    def item_view(row, direction):
        info = _describe(row, m, avg_share, category_total)
        avail, avail_r4 = stock.get(row["item"], (None, None))
        high, reason = potential(info, direction, qty_1k, avail, avail_r4)
        image = image_of.get(row["item"])
        return {**info, "id": row["item"], "name": name_of.get(row["item"], row["item"]),
                "image": image if isinstance(image, str) and image.startswith(("http://", "https://")) else None,
                "available": avail, "potential": high, "reason": reason}

    result = {}
    for direction in ("up", "down"):
        sub_rows = []
        for sub in _pick(subs, "dif", direction, SUB_LIMIT, SUB_THRESHOLD):
            name = sub["subcategory"]
            fam_scope = families[families["subcategory"] == name]
            fam_rows, shown = [], set()
            for fam in _pick(fam_scope, "dif", direction, FAMILY_LIMIT, FAMILY_THRESHOLD):
                item_scope = items[(items["subcategory"] == name) & (items["family"] == fam["family"])]
                picked = [item_view(r, direction) for r in _pick(item_scope, "dif", direction, ITEM_LIMIT, 1.0)]
                shown.update(x["id"] for x in picked)
                fam_rows.append({**_describe(fam, m, avg_share, category_total), "name": fam["family"], "items": picked})
            extra = []
            scope = items[(items["subcategory"] == name) & ~items["item"].isin(shown)]
            for r in _pick(scope, "dif", direction, len(scope) or 1, 1.0):
                view = item_view(r, direction)
                if view["potential"]:
                    extra.append(view)
                    break
            sub_rows.append({**_describe(sub, m, avg_share, category_total), "name": name, "families": fam_rows,
                             "others": extra})
        result[direction] = sub_rows

    segments = []
    focus = own[own["channel"] == channel]
    total = focus["sales__week"].sum()
    for col in [c for c in own.columns if c.startswith("seg:")]:
        s = focus[focus[col].map(_is_true)]
        segments.append({"name": col[4:], "share": (s["sales__week"].sum() / total * 100) if total > 0 else None,
                         "sales_vs_ly": idx(s["sales__week"].sum(), s["sales__week_ly"].sum()),
                         "qty_vs_ly": idx(s["qty__week"].sum(), s["qty__week_ly"].sum())})

    ranked = subs.assign(vs=[idx(a, b) for a, b in zip(subs[f"{m}__week"], subs[f"{m}__week_ly"])])
    ranked = ranked.dropna(subset=["vs"]).sort_values("vs", ascending=False)
    has_exclusion = bool(own["excluded"].any())
    top = ranked.head(3)
    bottom = ranked[~ranked["subcategory"].isin(top["subcategory"])].tail(2).iloc[::-1]
    return {
        "up": result["up"], "down": result["down"], "segments": segments, "has_exclusion": has_exclusion,
        "top": [{"name": r["subcategory"], "vs_ly": r["vs"]} for _, r in top.iterrows()],
        "bottom": [{"name": r["subcategory"], "vs_ly": r["vs"]} for _, r in bottom.iterrows()],
    }


def _regions(total, goals, stores_df):
    df = total.merge(stores_df[["store", "region", "city", "name"]], on="store", how="left")
    if goals is not None:
        g = goals.groupby("store", as_index=False)["goal__week"].sum()
        df = df.merge(g, on="store", how="left").fillna({"goal__week": 0})
    else:
        df["goal__week"] = 0

    def view(frame, name, level):
        s, ly = frame["sales__week"].sum(), frame["sales__week_ly"].sum()
        t, tly = frame["tickets__week"].sum(), frame["tickets__week_ly"].sum()
        return {"name": name, "level": level, "sales": s, "sales_vs_ly": idx(s, ly),
                "sales_vs_goal": idx(s, frame["goal__week"].sum()), "goal_gap": s - frame["goal__week"].sum(),
                "trans": t, "trans_vs_ly": idx(t, tly), "ab": ratio(s, t), "ab_vs_ly": idx(ratio(s, t), ratio(ly, tly))}

    rows = [view(df, "合计", "total")]
    for region, frame in sorted(df.groupby("region"), key=lambda kv: -kv[1]["sales__week"].sum()):
        rows.append(view(frame, region or "未分区", "region"))
    return rows


def analyze(wh: Warehouse, store, category, week, channel=None, focus=None) -> dict:
    sem = wh.semantic
    focus = focus or sem.default_focus
    if focus not in {"sales", "qty"}:
        raise ValueError("focus 仅支持 sales 或 qty")
    periods = build_periods(week, sem)
    latest = wh.latest_date()
    if latest is None or latest < periods["week"].end:
        raise DataUnavailable(f"周次 {week} 还没结束，数据只更新到 {latest}。最近完整周是 {wh.latest_complete_week()}。")

    stores_df = wh.stores()
    if store not in set(stores_df["store"]):
        raise DataUnavailable(f"找不到门店 {store}")
    group = stores_df.loc[stores_df["store"] == store, "peer_group"].iloc[0]
    all_stores = stores_df["store"].tolist()
    peers = stores_df.loc[stores_df["peer_group"] == group, "store"].tolist()
    others = [s for s in peers if s != store]

    main = {k: periods[k] for k in ("week", "week_ly", "r4", "r4_ly", "ytd", "ytd_ly")}
    week_pair = {k: periods[k] for k in ("week", "week_ly")}
    scope = {"store": all_stores, "category": category}
    traffic_filters = {"store": all_stores}
    if sem.has("traffic") and sem.source("traffic").has("category"):
        traffic_filters["category"] = category
    has_subs = sem.source("sales").has("subchannel")
    with ThreadPoolExecutor(max_workers=6) as pool:
        total_f = pool.submit(wh.sales, ["store"], main, scope, "门店 × 品类汇总")
        whole_f = pool.submit(wh.sales, ["store"], main, {"store": all_stores}, "门店全品类汇总", False)
        channel_f = pool.submit(wh.sales, ["store", "channel"], periods, scope, "渠道与销售树")
        goals_f = pool.submit(wh.aggregate, "goals", ["store", "channel"], {"goal": ("sum", "sales_goal")}, main, scope, "目标") if sem.has("goals") else None
        traffic_f = pool.submit(wh.aggregate, "traffic", ["store", "channel"], {"visitors": ("sum", "visitors")}, periods, traffic_filters, "客流") if sem.has("traffic") else None
        subs_f = pool.submit(wh.sales, ["channel", "subchannel"], week_pair, {"store": store, "category": category}, "二级渠道", False) if has_subs else None
        cats_f = pool.submit(wh.sales, ["category"], week_pair, {"store": store}, "门店品类结构", False)
    total = total_f.result()
    if total[total["store"] == store]["sales__week"].sum() <= 0:
        raise DataUnavailable(f"门店 {store} 的 {category} 在 {week} 没有销售数据，请检查门店、品类和周次。")
    whole, by_channel = whole_f.result(), channel_f.result()
    channels_available = sorted(by_channel[by_channel["store"] == store]["channel"].unique())
    channel = channel or sem.default_channel or channels_available[0]
    if channel not in channels_available:
        raise DataUnavailable(f"渠道 {channel} 不存在，可选：{', '.join(channels_available)}")
    goals = goals_f.result() if goals_f else None
    traffic = traffic_f.result() if traffic_f else None
    subs = subs_f.result() if subs_f else None
    cats = cats_f.result()
    cat_total = cats["sales__week"].sum()
    mix = [{"name": r["category"], "sales": r["sales__week"], "share": (ratio(r["sales__week"], cat_total) or 0) * 100,
            "sales_vs_ly": idx(r["sales__week"], r["sales__week_ly"]), "selected": r["category"] == category}
           for _, r in cats.sort_values("sales__week", ascending=False).iterrows()]

    goals_total = goals.groupby("store", as_index=False).sum(numeric_only=True) if goals is not None else None
    overall = _overall(total, whole, goals_total, store, peers, stores_df)
    tree = _tree(by_channel, traffic, store, peers, channel)
    row = stores_df[stores_df["store"] == store].iloc[0]
    return {
        "source": sem.report_source or sem.name, "data_note": sem.data_note, "synthetic": sem.synthetic, "branding": sem.branding, "store": store, "store_name": row["name"], "category": category, "week": str(week),
        "channel": channel, "focus": focus, "labels": sem.labels, "latest_date": str(latest),
        "period": {k: {"start": str(periods[k].start), "end": str(periods[k].end)} for k in ("week", "week_ly", "r4", "ytd")},
        "peers": len(peers), "overall": overall, "mix": mix,
        "channels": _channels(by_channel, subs, goals, store, peers),
        "tree": tree,
        "drill": _drill(wh, periods, store, category, channel, others, focus, tree),
        "regions": _regions(total, goals_total, stores_df),
    }
