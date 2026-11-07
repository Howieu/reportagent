"""报告渲染：HTML（Jinja2 自动转义）和 PDF（本机 Chrome 无头打印）。"""

import html
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from .narrative import FACTOR_NAMES, fi, money, num, signed, verdict_ly

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
    """指数：低于基准用深红，其余黑色。数字本身就能看出高低，不依赖颜色。"""
    if value is None:
        return Markup('<span class="flat">—</span>')
    cls = "down" if value < baseline - 0.5 else "flat"
    return Markup(f'<span class="{cls}">{round(value)}</span>')


def gap(value):
    if value is None:
        return Markup('<span class="flat">—</span>')
    cls = "down" if value < -0.5 else "flat"
    return Markup(f'<span class="{cls}">{round(value):+d}</span>')


def spark(values, labels=None, width=156, height=42):
    """单系列折线，末点标记；原生 <title> 提供悬停值。"""
    points = [(i, v) for i, v in enumerate(values) if v is not None]
    if len(points) < 2:
        return Markup("")
    low, high = min(v for _, v in points), max(v for _, v in points)
    span = (high - low) or 1
    def x(i):
        return 6 + i * (width - 12) / (len(values) - 1)

    def y(v):
        return height - 7 - (v - low) * (height - 14) / span

    path = " ".join(f"{'M' if n == 0 else 'L'}{x(i):.1f} {y(v):.1f}" for n, (i, v) in enumerate(points))
    dots = "".join(
        f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="{3.5 if i == points[-1][0] else 9}" '
        f'fill="{"var(--accent)" if i == points[-1][0] else "transparent"}">'
        f"<title>vs LY {round(v)}</title></circle>" for i, v in points)
    return Markup(f'<svg class="spark" viewBox="0 0 {width} {height}" role="img" '
                  f'aria-label="近四周 vs LY 趋势"><path d="{path}" fill="none" stroke="var(--accent)" '
                  f'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>{dots}</svg>')


def contribution_bars(items):
    """销售树对数分解：以 0 为基线的横向条。"""
    if not items:
        return Markup("")
    top = max(abs(c["share"]) for c in items) or 1
    rows = []
    for c in sorted(items, key=lambda c: -abs(c["share"])):
        w = abs(c["share"]) / top * 46
        side = f"left:50%;width:{w:.1f}%" if c["share"] >= 0 else f"right:50%;width:{w:.1f}%"
        rows.append(f'<div class="cbar"><span class="cname">{FACTOR_NAMES.get(c["factor"], c["factor"])}</span>'
                    f'<span class="ctrack"><i style="{side}"></i></span>'
                    f'<span class="cval">{c["share"]:+.0f}%</span></div>')
    return Markup("".join(rows))


_env = Environment(loader=FileSystemLoader(HERE), autoescape=select_autoescape(["html.j2"]),
                   trim_blocks=True, lstrip_blocks=True)
_env.filters.update(fi=fi, signed=signed, money=money, num=num, rich=rich, delta=delta, gap=gap, spark=spark,
                    bars=contribution_bars)


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
        band = f'<polygon points="{" ".join(edge)}" fill="#ddd"/>'
    weeks = [h["week"] for h in history] + [r["week"] for r in rows]
    ticks = "".join(f'<text x="{x(i):.1f}" y="{height - 6}" font-size="11" text-anchor="{"start" if i == 0 else "end" if i == count - 1 else "middle"}">{w}</text>'
                    for i, w in enumerate(weeks) if (i % 4 == 0 and i < count - 2) or i == count - 1)
    return Markup(f'<svg class="fchart" viewBox="0 0 {width} {height}" role="img" aria-label="近期实际和未来预测">{band}'
                  f'<line x1="8" x2="{width - 8}" y1="{height - 22}" y2="{height - 22}" stroke="#999" stroke-width=".75"/>'
                  f'<path d="{line}" fill="none" stroke="#111" stroke-width="1.6"/>'
                  f'<path d="{dashed}" fill="none" stroke="#111" stroke-width="1.6" stroke-dasharray="5 4"/>{ticks}</svg>')


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


def _note(item):
    if item.get("potential"):
        return f"潜力高：{item['reason']}"
    parts = []
    if item.get("core_vs_ly") is not None:
        parts.append(f"排除新品后 vs LY {fi(item['core_vs_ly'])}")
    if item.get("available") is not None:
        parts.append(f"可售率 {fi(item['available'])}%")
    if item.get("reason"):
        parts.append(item["reason"])
    return "；".join(parts)


def _annotate(drill):
    for direction in ("up", "down"):
        for sub in drill[direction]:
            sub["note_text"] = _note(sub)
            for fam in sub["families"]:
                fam["note_text"] = _note(fam)
                for item in fam["items"]:
                    item["note_text"] = _note(item)
            for item in sub["others"]:
                item["note_text"] = _note(item)


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
    _annotate(report["drill"])
    return _env.get_template("report.html.j2").render(
        r=report, s=sections, queries=list(queries), node_labels=node_labels, titles=_titles(report), follow_ups=_follow_ups(report),
        factor_names=FACTOR_NAMES, generated=datetime.now().strftime("%Y-%m-%d %H:%M"))


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
