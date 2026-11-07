"""报告渲染：HTML（Jinja2 自动转义）和 PDF（本机 Chrome 无头打印）。"""

import html
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

from .narrative import FACTOR_NAMES, fi, money, num, signed, verdict_ly
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


def spark(values, labels=None, width=156, height=42):
    """单系列折线，末点标记。给了周次标签时带刻度和网格线；原生 <title> 提供悬停值。"""
    points = [(i, v) for i, v in enumerate(values) if v is not None]
    if len(points) < 2:
        return Markup("")
    low, high = min(v for _, v in points), max(v for _, v in points)
    span = (high - low) or 1
    left, bottom = (30, 18) if labels else (6, 7)

    def x(i):
        return left + i * (width - left - 8) / (len(values) - 1)

    def y(v):
        return height - bottom - (v - low) * (height - bottom - 8) / span

    axis = ""
    if labels:
        ticks = [low, (low + high) / 2, high]
        axis = "".join(f'<line x1="{left}" x2="{width - 8}" y1="{y(t):.1f}" y2="{y(t):.1f}" stroke="#e6e2d8" stroke-width="1"/>'
                       f'<text x="{left - 4}" y="{y(t) + 3:.1f}" font-size="9" text-anchor="end" fill="#5b6673">{t:.0f}</text>' for t in ticks)
        axis += "".join(f'<text x="{x(i):.1f}" y="{height - 4}" font-size="9" text-anchor="middle" fill="#5b6673">{w}</text>' for i, w in enumerate(labels))
    path = " ".join(f"{'M' if n == 0 else 'L'}{x(i):.1f} {y(v):.1f}" for n, (i, v) in enumerate(points))
    dots = "".join(
        f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="{3.5 if i == points[-1][0] else 9}" '
        f'fill="{"var(--series)" if i == points[-1][0] else "transparent"}">'
        f"<title>{round(v)}</title></circle>" for i, v in points)
    return Markup(f'<svg class="spark" viewBox="0 0 {width} {height}" role="img" aria-label="趋势折线">{axis}'
                  f'<path d="{path}" fill="none" stroke="var(--series)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>{dots}</svg>')


def index_chart(overall, key, comp_key):
    """IKEA 版的指数柱状图：财年累计、滚动 4 周、本周，橙色标记是对标。"""
    rows = [("财年累计", overall["ytd"]), ("滚动 4 周", overall["r4"]), ("本周", overall["week"])]
    values = [v for _, o in rows for v in (o[key], o[comp_key]) if v is not None]
    if not values:
        return Markup("")
    width, height, top, base = 340, 190, 22, 164
    scale = (base - top) / (max(values) * 1.05 or 1)
    parts = [f'<line x1="14" x2="{width - 14}" y1="{base}" y2="{base}" stroke="#cfd6df"/>',
             f'<line x1="{width - 74}" x2="{width - 52}" y1="10" y2="10" stroke="var(--series2)" stroke-width="2.5"/>'
             f'<text x="{width - 46}" y="14" font-size="11" fill="#1c2430">对标</text>']
    for n, (name, o) in enumerate(rows):
        center = 62 + n * 108
        value, comp = o[key], o[comp_key]
        if value is not None:
            h = value * scale
            color = "--bar-down" if value < 99.5 else "--bar-up" if value > 100.5 else "--bar-flat"
            parts.append(f'<rect x="{center - 21}" y="{base - h:.1f}" width="42" height="{h:.1f}" rx="2" fill="var({color})"><title>{name} {round(value)}</title></rect>')
            label_y = base - h / 2 + 4 if h > 24 else base - h - 4
            label_fill = "#ffffff" if h > 24 else "#1c2430"
            parts.append(f'<text x="{center}" y="{label_y:.1f}" font-size="13" font-weight="700" text-anchor="middle" fill="{label_fill}">{round(value)}</text>')
        if comp is not None:
            yy = base - comp * scale
            parts.append(f'<line x1="{center - 31}" x2="{center + 31}" y1="{yy:.1f}" y2="{yy:.1f}" stroke="var(--series2)" stroke-width="2.5"><title>对标 {round(comp)}</title></line>'
                         f'<path d="M{center - 4} {yy - 1:.1f} L{center + 4} {yy - 1:.1f} L{center} {yy - 7:.1f} Z" fill="var(--series2)"/>')
        parts.append(f'<text x="{center}" y="{base + 16}" font-size="12" text-anchor="middle" fill="#1c2430">{name}</text>')
    return Markup(f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="指数柱状图">{"".join(parts)}</svg>')


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
                    bars=contribution_bars, mix_bars=mix_bars)


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


def forecast_chart(history, rows, width=760, height=190):
    """近期实际（实线）+ 预测（虚线）+ 80% 区间（灰带）。"""
    actual = [h["value"] for h in history]
    bounds = [v for r in rows for v in (r["forecast"], r["low"], r["high"]) if v is not None]
    top = max([*actual, *bounds, 1]) * 1.05
    count = len(actual) + len(rows)

    def x(i):
        return 8 + i * (width - 16) / (count - 1)

    def y(v):
        return height - 22 - v / top * (height - 32)

    start = len(actual) - 1
    line = " ".join(f"{'M' if i == 0 else 'L'}{x(i):.1f} {y(v):.1f}" for i, v in enumerate(actual))
    future = [(start, actual[-1]), *[(start + 1 + i, r["forecast"]) for i, r in enumerate(rows)]]
    dashed = " ".join(f"{'M' if i == 0 else 'L'}{x(n):.1f} {y(v):.1f}" for i, (n, v) in enumerate(future))
    known = [(start + 1 + i, r) for i, r in enumerate(rows) if r["low"] is not None]
    band = ""
    if known:
        edge = [f"{x(n):.1f},{y(r['high']):.1f}" for n, r in known] + [f"{x(n):.1f},{y(r['low']):.1f}" for n, r in reversed(known)]
        band = f'<polygon points="{" ".join(edge)}" fill="var(--series2-tint)"/>'
    weeks = [h["week"] for h in history] + [r["week"] for r in rows]
    ticks = "".join(f'<text x="{x(i):.1f}" y="{height - 6}" font-size="11" text-anchor="{"start" if i == 0 else "end" if i == count - 1 else "middle"}">{w}</text>'
                    for i, w in enumerate(weeks) if (i % 4 == 0 and i < count - 2) or i == count - 1)
    return Markup(f'<svg class="fchart" viewBox="0 0 {width} {height}" role="img" aria-label="近期实际和未来预测">{band}'
                  f'<line x1="8" x2="{width - 8}" y1="{height - 22}" y2="{height - 22}" stroke="#cfd6df" stroke-width="1"/>'
                  f'<path d="{line}" fill="none" stroke="var(--series)" stroke-width="2"/>'
                  f'<path d="{dashed}" fill="none" stroke="var(--series2)" stroke-width="2" stroke-dasharray="5 4"/>{ticks}</svg>')


def render_forecast(result, stores, categories, scope, source_name, synthetic=False, base="/forecast", scenario=None, scenario_error=None, lever_names=None, events=0):
    fmt = result["fmt"]

    def signed_value(v):
        return ("+" if v >= 0 else "") + fmt(v)

    return _env.get_template("forecast.html.j2").render(
        f=result, fmt=fmt, signed_value=signed_value, stores=stores, categories=categories, scope=scope, base=base,
        source_name=source_name, synthetic=synthetic, chart=forecast_chart(result["history"], result["rows"]),
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
    """标题写结论：只读标题也能看懂整份报告。"""
    labels, week = r["labels"], r["overall"]["week"]
    channels = [c for c in r["channels"] if c["sales_vs_ly"] is not None]
    top_channel = max(channels, key=lambda c: c["sales_vs_ly"]) if channels else None
    driver_key = r["tree"]["driver"]
    driver = next((c for c in r["tree"]["contributions"] if c["factor"] == driver_key), None)
    sales = week["sales_vs_ly"] or 100
    subs = r["drill"]["up"] if sales >= 100 else r["drill"]["down"]
    word = "上升" if sales >= 100 else "下降"
    regions = [x for x in r["regions"] if x["level"] == "region" and x["sales_vs_ly"] is not None]
    best = max(regions, key=lambda x: x["sales_vs_ly"]) if regions else None
    worst = min(regions, key=lambda x: x["sales_vs_ly"]) if regions else None
    drill = (f"{word}主要来自{labels['subcategory']} {subs[0]['name']}（贡献 {fi(subs[0]['contribution'])}%）" if subs
             else f"排除新品后没有{labels['subcategory']}朝{word}方向变化，变化主要来自新品")
    return {
        "overall": f"整体表现：Sales {verdict_ly(week['sales_vs_ly'])}（vs LY {fi(week['sales_vs_ly'])}），排名第 {week['rank']}",
        "channel": (f"分{labels['channel']}：{top_channel['channel']}同比最高（vs LY {fi(top_channel['sales_vs_ly'])}）" if top_channel else f"分{labels['channel']}表现"),
        "tree": (f"驱动拆解：{FACTOR_NAMES.get(driver_key, driver_key)} 是 Sales 变化的最大因素（贡献 {driver['share']:.0f}%）" if driver else "驱动拆解"),
        "drill": f"商品归因：{drill}",
        "region": (f"区域对比：{best['name']}同比最高（{fi(best['sales_vs_ly'])}），{worst['name']}最低（{fi(worst['sales_vs_ly'])}）" if best and best is not worst else "区域对比"),
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
    node_labels = {"sales": "Sales", "tickets": "Trans", "ab": "AB", "traffic": "Traffic", "cr": "CR",
                   "ai": "AI", "price": "Price/item", "qty": "Qty"}
    nodes = report["tree"]["nodes"]
    bottom = ["traffic", "cr", "ai", "price"] if "traffic" in nodes else ["ai", "price"]
    tree_rows = [[k for k in row if k in nodes] for row in (["sales"], ["tickets", "qty", "ab"], bottom)]
    monday = parse_week(report["week"])
    week_labels = [week_of(monday - timedelta(days=7 * i))[-2:] for i in range(3, -1, -1)]
    return _env.get_template("report.html.j2").render(
        r=report, s=sections, queries=list(queries), node_labels=node_labels, titles=_titles(report), follow_ups=_follow_ups(report),
        factor_names=FACTOR_NAMES, generated=datetime.now().strftime("%Y-%m-%d %H:%M"), tree_rows=tree_rows, week_labels=week_labels, index_chart=index_chart)


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
