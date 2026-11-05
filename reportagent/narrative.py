"""文字层：规则模板打底，LLM 只负责润色；校验不过就退回模板。"""

import os
import re
from concurrent.futures import ThreadPoolExecutor

NUMBER = re.compile(r"\d+(?:\.\d+)?")
LIST_PREFIX = re.compile(r"^\s*\d+[.、]\s*", re.MULTILINE)
UP_WORDS = r"(高于去年|同比增长|同比上升|好于去年|超过去年)"
DOWN_WORDS = r"(低于去年|同比下降|同比下滑|不及去年|差于去年)"
HIT_GOAL = r"((?<![未没不])达成目标|(?<![未没不])完成目标|超额|超过目标)"
MISS_GOAL = r"(未达成?目标|未完成目标|低于目标|没有达到目标)"
ALL_HIT_GOAL = r"(各|所有|全部|均|都).{0,10}(优于目标|高于目标|达成目标|完成目标|超过目标)"
# vs LY 119 是去年的 119%，写成“增长 119%”是错的。事实里只有指数，没有增幅。
INDEX_AS_GROWTH = re.compile(r"(上升|增长|提升|上涨|下降|下滑|下跌|减少)了?\s*\d+(\.\d+)?\s*%")
ENTITY_UP = r"(优于去年|高于去年|增长|上升|强劲|提升)"
ENTITY_DOWN = r"(低于去年|不及去年|下滑|下降|疲软|下跌)"


def fi(x):
    return "—" if x is None else f"{round(x)}"


def signed(x):
    return "—" if x is None else f"{round(x):+d}"


CURRENCY = {"symbol": "¥"}  # ponytail: 单进程单语义配置；多租户时改成随请求传递


def money(x):
    if x is None:
        return "—"
    c = CURRENCY["symbol"]
    sign, x = ("-", -x) if x < 0 else ("", x)
    return sign + (f"{c}{x / 1e6:.2f}M" if x >= 1e6 else f"{c}{x / 1e3:.0f}K" if x >= 1e4 else f"{c}{x:,.0f}")


def num(x):
    if x is None:
        return "—"
    return f"{x / 1e3:.1f}K" if abs(x) >= 1e4 else f"{x:,.0f}"


def verdict_ly(v):
    if v is None:
        return "无法与去年比较"
    return "高于去年同期" if v > 100.5 else "低于去年同期" if v < 99.5 else "与去年同期持平"


def verdict_goal(v):
    return "达成目标" if v >= 100 else "未达目标"


def goal_ly(goal, ly):
    """目标没配置时只说同比。"""
    return f"{verdict_goal(goal)}，{verdict_ly(ly)}" if goal is not None else verdict_ly(ly)


def goal_metric(goal):
    return f"vs Goal {fi(goal)}、" if goal is not None else ""


FACTOR_NAMES = {"traffic": "Traffic", "cr": "CR", "ai": "AI", "price": "Price/item", "tickets": "Trans"}


class LLM:
    """OpenAI 兼容接口。未配置 Key 时 enabled 为 False，调用方走模板。"""

    def __init__(self, client=None, model=None):
        self.model = model or os.environ.get("LLM_MODEL", "agent-model")
        self.client = client
        key = os.environ.get("LLM_API_KEY")
        if client is None and key:
            from openai import OpenAI

            self.client = OpenAI(api_key=key, base_url=os.environ.get("LLM_BASE_URL"), timeout=60, max_retries=4)

    @property
    def enabled(self):
        return self.client is not None

    def chat(self, messages, tools=None, temperature=0.2, max_tokens=900):
        kwargs = {"model": self.model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        if self.model.startswith("agent-model") and "flash-" not in self.model:
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}  # 关掉模型思考，降低延迟
        if tools:
            kwargs["tools"] = tools
        return self.client.chat.completions.create(**kwargs).choices[0].message


def check_entities(text, entities):
    """按分句检查：提到某对象时，涨跌表述不能与它的指数相反。"""
    for clause in re.split(r"[，。；,;\n]", text):
        for name, value in entities:
            if value is None or name not in clause:
                continue
            if value < 99.5 and re.search(ENTITY_UP, clause):
                return f"{name} 的方向写反了"
            if value > 100.5 and re.search(ENTITY_DOWN, clause):
                return f"{name} 的方向写反了"
    return None


def check_text(text, facts, forbid=(), banned=(), entities=()):
    """返回校验失败原因；None 表示通过。"""
    if not text or not text.strip():
        return "空回复"
    allowed = set(NUMBER.findall(facts)) | {"100"}
    body = LIST_PREFIX.sub("", text)
    for n in NUMBER.findall(body):
        if n not in allowed:
            return f"出现事实中没有的数字 {n}"
    if INDEX_AS_GROWTH.search(body):
        return "把指数写成了增幅"
    for pattern in forbid:
        if re.search(pattern, body):
            return "结论方向与数据不一致"
    for phrase in banned:
        if phrase in body:
            return f"命中禁用词：{phrase}"
    return check_entities(body, entities)


def forbids_for(values_ly, values_goal=()):
    """所有范围方向一致时才能判定矛盾。"""
    out = []
    ly = [v for v in values_ly if v is not None]
    if ly and all(v < 99.5 for v in ly):
        out.append(UP_WORDS)
    if ly and all(v > 100.5 for v in ly):
        out.append(DOWN_WORDS)
    goal = [v for v in values_goal if v is not None]
    if goal and all(v < 100 for v in goal):
        out.append(HIT_GOAL)
    if goal and all(v >= 100 for v in goal):
        out.append(MISS_GOAL)
    if goal and any(v < 100 for v in goal):
        out.append(ALL_HIT_GOAL)
    return out


def system_prompt(semantic):
    lines = [
        "你是零售数据分析师，根据给定事实写周报文字。",
        "只能使用事实中出现的数字，不能计算新数字，不能编造原因。",
        "用中文写，英文指标名（Sales、AB、AI、CR、Trans、Traffic）保持原样。",
        "表述要准确：说“Sales 低于去年同期”，不要说“Sales vs LY 低于去年同期”。",
        "vs LY 119 表示是去年的 119%，不能写成增长 119%，也不要换算成增幅。",
        *semantic.glossary, *semantic.constraints,
    ]
    return "\n".join(f"- {x}" for x in lines)


def facts_overall(r):
    w, y = r["overall"]["week"], r["overall"]["ytd"]
    return (f"本周 Sales {goal_metric(w['sales_vs_goal'])}vs LY {fi(w['sales_vs_ly'])}，Qty vs LY {fi(w['qty_vs_ly'])}，"
            f"对标门店 vs LY {fi(w['sales_vs_ly_comp'])}，排名第 {w['rank']}。\n"
            f"财年累计 Sales {goal_metric(y['sales_vs_goal'])}vs LY {fi(y['sales_vs_ly'])}，排名第 {y['rank']}。")


def tpl_overall(r):
    w, y = r["overall"]["week"], r["overall"]["ytd"]
    trend = "好于" if (w["sales_vs_ly"] or 0) > (y["sales_vs_ly"] or 0) else "弱于"
    return (f"本周 Sales {goal_ly(w['sales_vs_goal'], w['sales_vs_ly'])}；"
            f"财年累计 Sales {goal_ly(y['sales_vs_goal'], y['sales_vs_ly'])}。"
            f"本周同比表现{trend}财年累计水平。")


def facts_channel(r):
    lines = []
    for c in r["channels"]:
        subs = "；".join(f"{s['name']} vs LY {fi(s['sales_vs_ly'])} 占比 {s['share']:.1f}%" for s in c["subs"])
        lines.append(f"{c['channel']}: Sales {goal_metric(c['sales_vs_goal'])}vs LY {fi(c['sales_vs_ly'])}，"
                     f"{c['pick_word'] or ''}{r['labels']['subchannel']} {c['pick'] or '无'}。{subs}")
    return "\n".join(lines)


def tpl_channel(r):
    sub_label = r["labels"]["subchannel"]
    parts = []
    for c in r["channels"]:
        pick = f"，表现{c['pick_word']}的{sub_label}是 {c['pick']}" if c["pick"] else ""
        parts.append(f"{c['channel']} Sales {goal_ly(c['sales_vs_goal'], c['sales_vs_ly'])}{pick}。")
    return "".join(parts)


def facts_tree(r):
    t = r["tree"]
    nodes = "，".join(f"{k} vs LY {fi(v['vs_ly'])}" for k, v in t["nodes"].items())
    driver = FACTOR_NAMES.get(t["driver"], t["driver"])
    return f"{r['channel']}：{nodes}。对 Sales 变化影响最大的因素是 {driver}。"


def tpl_tree(r):
    t = r["tree"]
    sales = t["nodes"]["sales"]["vs_ly"]
    driver = FACTOR_NAMES.get(t["driver"], t["driver"] or "—")
    return f"{r['channel']} Sales {verdict_ly(sales)}，拆解销售树后，影响最大的因素是 {driver}。"


def _top_sub(r):
    sales = r["overall"]["week"]["sales_vs_ly"] or 100
    rows = r["drill"]["up"] if sales >= 100 else r["drill"]["down"]
    return (rows[0], "上升" if sales >= 100 else "下降") if rows else (None, "")


def facts_summary(r):
    sub, word = _top_sub(r)
    label = r["labels"]["subcategory"]
    extra = f"影响最大的{label}是 {sub['name']}，vs LY {fi(sub['vs_ly'])}，方向：{word}。" if sub else "排除新品后没有子类朝这个方向变化。"
    return "\n".join([facts_overall(r), facts_channel(r), facts_tree(r), extra])


def tpl_summary(r):
    w, y = r["overall"]["week"], r["overall"]["ytd"]
    node = r["tree"]["nodes"]
    driver_key = r["tree"]["driver"]
    driver = FACTOR_NAMES.get(driver_key, driver_key or "—")
    driver_vs = node.get(driver_key, {}).get("vs_ly")
    sales = node["sales"]["vs_ly"]
    channels = []
    for c in r["channels"]:
        pick = f"，表现{c['pick_word']}的是 {c['pick']}" if c["pick"] else ""
        channels.append(f"**{c['channel']}** {goal_metric(c['sales_vs_goal'])}vs LY {fi(c['sales_vs_ly'])}{pick}")
    sub, word = _top_sub(r)
    trend = "好于" if (w["sales_vs_ly"] or 0) > (y["sales_vs_ly"] or 0) else "弱于"
    label = r["labels"]["subcategory"]
    if sub:
        last = f"对变化影响最大的{label}是 **{sub['name']}**（vs LY {fi(sub['vs_ly'])}），方向为{word}。"
    elif r["drill"]["has_exclusion"]:
        last = f"排除新品后没有{label}朝这个方向变化，这次变化主要来自新品。"
    else:
        last = f"没有明显影响变化的{label}。"
    return "\n".join([
        f"1. **整体** Sales {goal_metric(w['sales_vs_goal'])}vs LY {fi(w['sales_vs_ly'])}，同比表现{trend}财年累计。",
        "2. " + "；".join(channels) + "。",
        f"3. **{r['channel']}** Sales {verdict_ly(sales)}，主要因素是 **{driver}**（vs LY {fi(driver_vs)}）。",
        f"4. {last}",
    ])


SECTIONS = {
    "overall": (facts_overall, tpl_overall, "不超过 70 字，不加标题和 Markdown。"),
    "channel": (facts_channel, tpl_channel, "不超过 90 字，不加标题和 Markdown。"),
    "tree": (facts_tree, tpl_tree, "不超过 70 字，可以补一条不涉及定价的关注方向，不加标题和 Markdown。"),
    "summary": (facts_summary, tpl_summary, "保留 4 条的结构，每条一行，以“1. ”到“4. ”开头，主要结论用 **加粗**。不要写其他内容。"),
}


def _forbid(key, r):
    w = r["overall"]["week"]
    if key == "overall":
        return forbids_for([w["sales_vs_ly"]], [w["sales_vs_goal"]])
    if key == "tree":
        return forbids_for([r["tree"]["nodes"]["sales"]["vs_ly"]])
    if key == "channel":
        return forbids_for([c["sales_vs_ly"] for c in r["channels"]], [c["sales_vs_goal"] for c in r["channels"]])
    return forbids_for([w["sales_vs_ly"], *[c["sales_vs_ly"] for c in r["channels"]]])


def _write(key, r, semantic, llm):
    facts_fn, tpl_fn, task = SECTIONS[key]
    fallback = tpl_fn(r)
    if not llm or not llm.enabled:
        return {"text": fallback, "mode": "模板"}
    facts = facts_fn(r)
    try:
        message = llm.chat([{"role": "system", "content": system_prompt(semantic)},
                            {"role": "user", "content": (
                                f"事实：\n{facts}\n\n初稿：\n{fallback}\n\n"
                                f"请把初稿改得更自然。只改措辞，不得增加初稿没有的结论或对象。要求：{task}")}])
        text = (message.content or "").strip()
    except Exception as exc:
        return {"text": fallback, "mode": "模板", "note": f"模型调用失败（{type(exc).__name__}）"}
    entities = [(c["channel"], c["sales_vs_ly"]) for c in r["channels"]]
    entities += [(x["name"], x["sales_vs_ly"]) for c in r["channels"] for x in c["subs"]]
    if key == "overall":
        entities = []
    problem = check_text(text, facts + "\n" + fallback, _forbid(key, r), semantic.banned_phrases, entities)
    if key == "summary" and not problem and len(LIST_PREFIX.findall(text)) != 4:
        problem = "不是 4 条"
    if problem:
        return {"text": fallback, "mode": "模板", "note": problem}
    return {"text": text, "mode": llm.model}


def write_sections(report, semantic, llm=None):
    with ThreadPoolExecutor(max_workers=2) as pool:  # 免费模型并发高了会限流
        futures = {k: pool.submit(_write, k, report, semantic, llm) for k in SECTIONS}
    return {k: f.result() for k, f in futures.items()}
