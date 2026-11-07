"""报告渲染：HTML（Jinja2 自动转义）和 PDF（本机 Chrome 无头打印）。"""

import base64
import html
import math
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from .narrative import FACTOR_NAMES, fi, money, num, signed
from .warehouse import parse_week, week_of

BOLD = re.compile(r"\*\*(.+?)\*\*")
HERE = Path(__file__).parent
CHROME_PATHS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]


def rich(text):
    """转义后只放行 **加粗**。"""
    return Markup(BOLD.sub(r"<strong>\1</strong>", html.escape(text or "")))


def delta(value, baseline=100):
    """指数：高于基准绿色，低于基准红色，接近持平不着色。数字本身就能看出高低，不依赖颜色。"""
    if value is None:
        return Markup('<span class="flat">—</span>')
    cls = "down" if value < baseline - 0.5 else "up" if value > baseline + 0.5 else "flat"
    return Markup(f'<span class="{cls}">{round(value)}</span>')


def _status(value, baseline=100):
    """指数对基准的状态，图表和文字共用同一套颜色。"""
    return "--down" if value < baseline - 0.5 else "--up" if value > baseline + 0.5 else "--flat"


def _ticks(low, high, count=3):
    """取整的坐标刻度，步长为 1、2、5 乘 10 的幂，刻度范围覆盖 low 到 high。"""
    rough = (high - low) / count or 1
    power = 10 ** math.floor(math.log10(rough))
    step = next(k * power for k in (1, 2, 5, 10) if k * power >= rough)
    first, last = math.floor(low / step), math.ceil(high / step)
    return [n * step for n in range(first, last + 1)]


def spark(values, labels, width=156, height=42, fmt="{:.0f}"):
    """趋势折线：左侧数值轴、浅网格、深蓝细线，末点标值。"""
    points = [(i, v) for i, v in enumerate(values) if v is not None]
    if len(points) < 2:
        return Markup("")
    series = [v for _, v in points]
    ticks = _ticks(min(series), max(series))
    left, right, top, bottom = 8 + 6 * max(len(fmt.format(t)) for t in ticks), 8, 8, 18

    def x(i):
        return left + 6 + i * (width - left - right - 6) / (len(values) - 1)

    def y(v):
        return height - bottom - (v - ticks[0]) * (height - bottom - top) / (ticks[-1] - ticks[0])

    grid = "".join(f'<line x1="{left}" x2="{width}" y1="{y(t):.1f}" y2="{y(t):.1f}" stroke="var(--border)" stroke-width="1"/>'
                   f'<text x="{left - 5}" y="{y(t) + 3.5:.1f}" font-size="10" text-anchor="end" fill="var(--muted)">{fmt.format(t)}</text>' for t in ticks)
    grid += "".join(f'<text x="{x(i):.1f}" y="{height - 4}" font-size="10" text-anchor="middle" fill="var(--muted)">{w}</text>' for i, w in enumerate(labels))
    path = " ".join(f"{'M' if n == 0 else 'L'}{x(i):.1f} {y(v):.1f}" for n, (i, v) in enumerate(points))
    last = points[-1][0]
    dots = "".join(f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="{3 if i == last else 2.2}" fill="{"var(--line)" if i == last else "var(--surface)"}" stroke="var(--line)" stroke-width="1.5"><title>{fmt.format(v)}</title></circle>' for i, v in points)
    dots += f'<text x="{x(last):.1f}" y="{y(series[-1]) - 8:.1f}" font-size="11" font-weight="600" text-anchor="end" fill="var(--fg)">{fmt.format(series[-1])}</text>'
    return Markup(f'<svg class="spark" viewBox="0 0 {width} {height}" role="img" aria-label="趋势折线">{grid}'
                  f'<path d="{path}" fill="none" stroke="var(--line)" stroke-width="1.75" stroke-linejoin="round"/>{dots}</svg>')


def index_chart(overall, key, comp_key):
    """IKEA 版的指数柱状图：财年累计、滚动 4 周、本周，黑色短线是对标，横线是 100。"""
    rows = [("财年累计", overall["ytd"]), ("滚动 4 周", overall["r4"]), ("本周", overall["week"])]
    values = [v for _, o in rows for v in (o[key], o[comp_key]) if v is not None]
    if not values:
        return Markup("")
    width, height, top, base = 300, 176, 24, 152
    scale = (base - top) / max(*values, 100)
    parts = [f'<line x1="0" x2="{width}" y1="{base - 100 * scale:.1f}" y2="{base - 100 * scale:.1f}" stroke="var(--border-strong)" stroke-width="1"/>',
             f'<text x="{width}" y="{base - 100 * scale - 4:.1f}" font-size="10" text-anchor="end" fill="var(--muted)">100</text>',
             f'<line x1="0" x2="{width}" y1="{base}" y2="{base}" stroke="var(--border-strong)" stroke-width="1"/>']
    for n, (name, o) in enumerate(rows):
        center = 50 + n * 92
        value, comp = o[key], o[comp_key]
        if value is not None:
            h = value * scale
            parts.append(f'<path d="M{center - 16} {base} V{base - h + 4:.1f} Q{center - 16} {base - h:.1f} {center - 12} {base - h:.1f} H{center + 12} Q{center + 16} {base - h:.1f} {center + 16} {base - h + 4:.1f} V{base} Z" fill="var({_status(value)})"><title>{name} {round(value)}</title></path>')
            parts.append(f'<text x="{center}" y="{base - h - 5:.1f}" font-size="13" font-weight="600" text-anchor="middle" fill="var(--fg)">{round(value)}</text>')
        if comp is not None:
            yy = base - comp * scale
            parts.append(f'<line x1="{center - 25}" x2="{center + 25}" y1="{yy:.1f}" y2="{yy:.1f}" stroke="var(--fg)" stroke-width="2"><title>对标 {round(comp)}</title></line>')
            parts.append(f'<text x="{center + 27}" y="{yy + 3.5:.1f}" font-size="10" fill="var(--muted)">{round(comp)}</text>')
        parts.append(f'<text x="{center}" y="{base + 16}" font-size="12" text-anchor="middle" fill="var(--muted)">{name}</text>')
    return Markup(f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="指数柱状图">{"".join(parts)}</svg>')


NODE_NAMES = {**FACTOR_NAMES, "sales": "Sales", "ab": "AB", "qty": "Qty"}
NODE_W, NODE_H = 184, 92
TREE_COLUMNS = (2, 252, 502)
TREE_ROWS = (2, 102, 202, 302)


def _tree_node(key, x, y, tree, shares, scale, on_path):
    """驱动树的一个方框：指数、近 4 周折线（灰线为 100）、贡献条。"""
    value = tree["nodes"][key]["vs_ly"]
    share = shares.get(key)
    pad = 12
    color = "--up-text" if (value or 100) > 100.5 else "--down-text" if (value or 100) < 99.5 else "--fg"
    fill, stroke, weight = ("--highlight", "--line", 1.5) if on_path else ("--surface", "--border-strong", 1)
    parts = [f'<rect x="{x}" y="{y}" width="{NODE_W}" height="{NODE_H}" rx="6" fill="var({fill})" stroke="var({stroke})" stroke-width="{weight}"/>',
             f'<text x="{x + pad}" y="{y + 21}" font-size="12" fill="var(--muted)">{NODE_NAMES[key]} vs LY</text>',
             f'<text x="{x + NODE_W - pad}" y="{y + 25}" font-size="{24 if key == "sales" else 19}" font-weight="600" text-anchor="end" fill="var({color})">{"—" if value is None else round(value)}</text>']
    points = [(i, v) for i, v in enumerate(tree["trend"][key]) if v is not None]
    if len(points) >= 2:
        top, height = y + 38, NODE_H - (66 if share is not None else 50)
        low, high = min(*(v for _, v in points), 100), max(*(v for _, v in points), 100)

        def px(i):
            return x + pad + i * (NODE_W - 2 * pad) / (len(tree["trend"][key]) - 1)

        def py(v):
            return top + height - (v - low) * height / ((high - low) or 1)

        line = " ".join(f"{px(i):.1f},{py(v):.1f}" for i, v in points)
        last_i, last_v = points[-1]
        parts.append(f'<line x1="{x + pad}" x2="{x + NODE_W - pad}" y1="{py(100):.1f}" y2="{py(100):.1f}" stroke="var(--border-strong)"/>'
                     f'<polyline points="{line}" fill="none" stroke="var(--line)" stroke-width="1.6" stroke-linejoin="round"/>'
                     f'<circle cx="{px(last_i):.1f}" cy="{py(last_v):.1f}" r="2.8" fill="var(--line)"/>')
    if share is not None:
        bar_y, track = y + NODE_H - 17, NODE_W - 2 * pad - 46
        bar = "--data-alt" if share < 0 else "--line" if on_path else "--line-soft"
        parts.append(f'<rect x="{x + pad}" y="{bar_y}" width="{track}" height="5" rx="2" fill="var(--border)"/>'
                     f'<rect x="{x + pad}" y="{bar_y}" width="{max(track * abs(share) / scale, 2):.1f}" height="5" rx="2" fill="var({bar})"/>'
                     f'<text x="{x + NODE_W - pad}" y="{bar_y + 6}" font-size="11" text-anchor="end" fill="var(--muted)">{share:+.0f}%</text>')
    return "".join(parts)


def _tree_link(x1, y1, x2, y2, on_path):
    middle = (x1 + x2) / 2
    stroke, weight = ("--line", 2) if on_path else ("--border-strong", 1)
    return f'<path d="M{x1} {y1} H{middle} V{y2} H{x2}" fill="none" stroke="var({stroke})" stroke-width="{weight}"/>'


def driver_tree(tree):
    """销售驱动树：Sales → Trans / AB → 下层因素。主要驱动因素的路径用蓝色标出，贡献条橙色表示与总变化反向。"""
    nodes = tree["nodes"]
    leaves = {c["factor"]: c["share"] for c in tree["contributions"]}
    groups = {"tickets": [k for k in ("traffic", "cr") if k in nodes], "ab": [k for k in ("ai", "price") if k in nodes]}
    shares = dict(leaves)
    for key, children in groups.items():
        known = [leaves[k] for k in children if k in leaves]
        if known:
            shares[key] = sum(known)
    scale = max((abs(v) for v in shares.values()), default=1) or 1
    driver = tree["driver"]
    path = {"sales", driver} | {g for g, children in groups.items() if driver in children}
    c1, c2, c3 = TREE_COLUMNS
    half = NODE_H / 2
    group_y = {"tickets": (TREE_ROWS[0] + TREE_ROWS[1]) / 2, "ab": (TREE_ROWS[2] + TREE_ROWS[3]) / 2}
    sales_y = sum(group_y.values()) / 2
    links, boxes = [], [_tree_node("sales", c1, sales_y, tree, {}, scale, True)]
    for slot, (key, children) in enumerate(groups.items()):
        y = group_y[key]
        links.append((key in path, _tree_link(c1 + NODE_W, sales_y + half, c2, y + half, key in path)))
        boxes.append(_tree_node(key, c2, y, tree, shares, scale, key in path))
        for n, child in enumerate(children):
            child_y = TREE_ROWS[slot * 2 + n]
            links.append((child in path, _tree_link(c2 + NODE_W, y + half, c3, child_y + half, child in path)))
            boxes.append(_tree_node(child, c3, child_y, tree, shares, scale, child in path))
    links.sort(key=lambda item: item[0])  # 高亮路径画在最上层
    qty = nodes.get("qty", {}).get("vs_ly")
    extra = "" if qty is None else (f'<text x="{c1 + NODE_W / 2}" y="{sales_y + NODE_H + 24}" font-size="12" text-anchor="middle" fill="var(--muted)">'
                                    f'Qty vs LY <tspan font-weight="600" fill="var(--fg)">{round(qty)}</tspan></text>')
    label = f"Sales 驱动树，主要驱动因素是 {NODE_NAMES.get(driver, '—')}"
    return Markup(f'<svg class="driver-tree" viewBox="0 0 688 396" role="img" aria-label="{label}">{"".join(link for _, link in links)}{"".join(boxes)}{extra}</svg>')


def contribution_bars(items):
    """以 0 为基线的横向条：蓝色为正，橙色为负。"""
    if not items:
        return Markup("")
    top = max(abs(c["share"]) for c in items) or 1
    rows = []
    for c in sorted(items, key=lambda c: -abs(c["share"])):
        w = abs(c["share"]) / top * 46
        side = f"left:50%;width:{w:.1f}%" if c["share"] >= 0 else f"right:50%;width:{w:.1f}%"
        cls = "" if c["share"] >= 0 else ' class="neg"'
        rows.append(f'<div class="cbar"><span class="cname">{FACTOR_NAMES.get(c["factor"], c["factor"])}</span>'
                    f'<span class="ctrack"><i{cls} style="{side}"></i></span>'
                    f'<span class="cval">{c["share"]:+.0f}%</span></div>')
    return Markup("".join(rows))


def mix_bars(items):
    """品类结构：本报告分析的品类用蓝色，其余用灰色。"""
    if not items:
        return Markup("")
    top = max(x["share"] or 0 for x in items) or 1
    rows = []
    for x in items:
        cls = "hbar selected" if x.get("selected") else "hbar"
        name = html.escape(str(x["name"]))
        rows.append(f'<div class="{cls}"><span>{name}</span><span class="track"><i style="width:{(x["share"] or 0) / top * 100:.1f}%"></i></span>'
                    f'<span class="val">{x["share"]:.1f}% · vs LY {delta(x["sales_vs_ly"])}</span></div>')
    return Markup("".join(rows))


_env = Environment(loader=FileSystemLoader(HERE), autoescape=select_autoescape(["html.j2"]),
                   trim_blocks=True, lstrip_blocks=True)
_env.filters.update(fi=fi, signed=signed, money=money, num=num, rich=rich, delta=delta, spark=spark,
                    bars=contribution_bars, mix_bars=mix_bars, driver_tree=driver_tree)
# 横幅实景图（CC0，来源 rawpixel.com/image/5941607，裁切并轻微虚化）。内嵌成 data URI，PDF 和离线 HTML 都不依赖外部图片；换图只需替换这个文件。
_env.globals["scene_image"] = "data:image/jpeg;base64," + base64.b64encode((HERE / "report_scene.jpg").read_bytes()).decode()


def points(value):
    """百分点变化。"""
    if value is None:
        return Markup('<span class="flat">—</span>')
    cls = "down" if value < -0.005 else "flat"
    return Markup(f'<span class="{cls}">{value:+.2f} pct</span>')


def render_funnel(result, base="/funnel"):
    def drill(value):
        next_dim = result["next_dimension"]
        query = {"week": result["week"], "dimension": next_dim, **result["filters"], result["dimension"]: value}
        return f"{base}?{urlencode(query)}"

    return _env.get_template("funnel.html.j2").render(f=result, base=base, drill=drill, pts=points)


def forecast_chart(history, rows, fmt, width=760, height=230):
    """近期实际（实线）+ 预测（虚线）+ 80% 区间（浅色带），带数值轴和浅网格。"""
    actual = [h["value"] for h in history]
    bounds = [v for r in rows for v in (r["forecast"], r["low"], r["high"]) if v is not None]
    ticks = _ticks(0, max([*actual, *bounds, 1]), 4)
    count = len(actual) + len(rows)
    left, right, top, bottom = 8 + 7 * max(len(fmt(t)) for t in ticks), 8, 8, 22

    def x(i):
        return left + 6 + i * (width - left - right - 6) / (count - 1)

    def y(v):
        return height - bottom - v * (height - bottom - top) / ticks[-1]

    start = len(actual) - 1
    line = " ".join(f"{'M' if i == 0 else 'L'}{x(i):.1f} {y(v):.1f}" for i, v in enumerate(actual))
    future = [(start, actual[-1]), *[(start + 1 + i, r["forecast"]) for i, r in enumerate(rows)]]
    dashed = " ".join(f"{'M' if i == 0 else 'L'}{x(n):.1f} {y(v):.1f}" for i, (n, v) in enumerate(future))
    known = [(start + 1 + i, r) for i, r in enumerate(rows) if r["low"] is not None]
    band = ""
    if known:
        edge = [f"{x(n):.1f},{y(r['high']):.1f}" for n, r in known] + [f"{x(n):.1f},{y(r['low']):.1f}" for n, r in reversed(known)]
        band = f'<polygon points="{" ".join(edge)}" fill="var(--data-alt-tint)"/>'
    grid = "".join(f'<line x1="{left}" x2="{width}" y1="{y(t):.1f}" y2="{y(t):.1f}" stroke="{"var(--border-strong)" if t == 0 else "var(--border)"}" stroke-width="1"/>'
                   f'<text x="{left - 6}" y="{y(t) + 3.5:.1f}" font-size="11" text-anchor="end" fill="var(--muted)">{fmt(t)}</text>' for t in ticks)
    weeks = [h["week"] for h in history] + [r["week"] for r in rows]
    labels = "".join(f'<text x="{x(i):.1f}" y="{height - 6}" font-size="11" fill="var(--muted)" text-anchor="{"end" if i == count - 1 else "middle"}">{w}</text>'
                     for i, w in enumerate(weeks) if (i % 4 == 0 and i < count - 2) or i == count - 1)
    return Markup(f'<svg class="fchart" viewBox="0 0 {width} {height}" role="img" aria-label="近期实际和未来预测">{grid}{band}'
                  f'<path d="{line}" fill="none" stroke="var(--line)" stroke-width="1.75" stroke-linejoin="round"/>'
                  f'<path d="{dashed}" fill="none" stroke="var(--data-alt)" stroke-width="1.75" stroke-dasharray="5 4"/>{labels}</svg>')


def render_forecast(result, stores, categories, scope, source_name, synthetic=False, base="/forecast", scenario=None, scenario_error=None, lever_names=None, events=0):
    fmt = result["fmt"]

    def signed_value(v):
        return ("+" if v >= 0 else "") + fmt(v)

    return _env.get_template("forecast.html.j2").render(
        f=result, fmt=fmt, signed_value=signed_value, stores=stores, categories=categories, scope=scope, base=base,
        source_name=source_name, synthetic=synthetic, chart=forecast_chart(result["history"], result["rows"], fmt),
        scenario=scenario, scenario_error=scenario_error, lever_names=lever_names or {}, events=events)


def render_checkup(result, stores, categories, scope, source_name, synthetic=False, base="/checkup"):
    fmt = result["fmt"]

    def signed_value(v):
        return ("+" if v >= 0 else "") + fmt(v)

    def link(item):
        return "/forecast?" + urlencode({"store": item["store"], "category": item["category"], "metric": result["metric"]})

    return _env.get_template("checkup.html.j2").render(c=result, fmt=fmt, signed_value=signed_value, link=link, stores=stores, categories=categories,
                                                       scope=scope, base=base, source_name=source_name, synthetic=synthetic)


def _titles(r):
    """商品和区域两节没有文字段落，用一句结论开头。"""
    labels, week = r["labels"], r["overall"]["week"]
    sales = week["sales_vs_ly"] or 100
    subs = r["drill"]["up"] if sales >= 100 else r["drill"]["down"]
    word = "上升" if sales >= 100 else "下降"
    regions = [x for x in r["regions"] if x["level"] == "region" and x["sales_vs_ly"] is not None]
    best = max(regions, key=lambda x: x["sales_vs_ly"]) if regions else None
    worst = min(regions, key=lambda x: x["sales_vs_ly"]) if regions else None
    drill = (f"{word}主要来自{labels['subcategory']} {subs[0]['name']}（贡献 {fi(subs[0]['contribution'])}%）" if subs
             else f"排除新品后没有{labels['subcategory']}朝{word}方向变化，变化主要来自新品")
    driver = next((c for c in r["tree"]["contributions"] if c["factor"] == r["tree"]["driver"]), None)
    sales_index = r["tree"]["nodes"]["sales"]["vs_ly"]
    return {
        "tree": f"Sales vs LY {fi(sales_index)}，主要驱动因素是 {FACTOR_NAMES[driver['factor']]}（贡献 {driver['share']:+.0f}%）。" if driver else f"Sales vs LY {fi(sales_index)}。",
        "drill": f"{drill}。",
        "region": (f"{best['name']}同比最高（vs LY {fi(best['sales_vs_ly'])}），{worst['name']}最低（vs LY {fi(worst['sales_vs_ly'])}）。" if best and best is not worst else ""),
    }


def _follow_ups(r):
    out = []
    for direction, word in (("down", "下降"), ("up", "上升")):
        for sub in r["drill"][direction]:
            items = [i for f in sub["families"] for i in f["items"]] + sub["others"]
            for item in items:
                if item["potential"]:
                    out.append(f"{item['name']}（{sub['name']}，{word}方向，vs LY {fi(item['vs_ly'])}）：{item['reason']}。")
    return out[:8]


def render_html(report, sections, queries=()):
    monday = parse_week(report["week"])
    week_labels = [week_of(monday - timedelta(days=7 * i))[-2:] for i in range(3, -1, -1)]
    return _env.get_template("report.html.j2").render(
        r=report, s=sections, queries=list(queries), titles=_titles(report), follow_ups=_follow_ups(report),
        generated=datetime.now().strftime("%Y-%m-%d %H:%M"), week_labels=week_labels, index_chart=index_chart)


def find_chrome():
    configured = os.environ.get("CHROME_PATH")
    if configured:
        return configured
    for path in CHROME_PATHS:
        if Path(path).exists():
            return path
    return shutil.which("chromium") or shutil.which("google-chrome") or shutil.which("chrome")


def html_to_pdf(html_text, pdf_path):
    chrome = find_chrome()
    if not chrome:
        raise RuntimeError("未找到 Chrome 或 Chromium，请安装后重试，或设置 CHROME_PATH。HTML 报告不受影响。")
    pdf_path = Path(pdf_path).resolve()
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "report.html"
        src.write_text(html_text, encoding="utf-8")
        args = [chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--user-data-dir={tmp}/profile"]
        if os.environ.get("CHROME_NO_SANDBOX") == "1":  # 容器里以 root 运行时 Chromium 只能关沙箱；页面有 CSP 且不含脚本
            args += ["--no-sandbox", "--disable-dev-shm-usage"]
        try:
            subprocess.run([*args, f"--print-to-pdf={pdf_path}", src.as_uri()], check=True, capture_output=True, timeout=120)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError("PDF 生成失败，请稍后重试。HTML 报告不受影响。") from exc
    return pdf_path


def html_to_pdf_bytes(html_text):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "out.pdf"
        html_to_pdf(html_text, path)
        return path.read_bytes()
