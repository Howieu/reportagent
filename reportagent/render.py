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

from .narrative import FACTOR_NAMES, fi, money, num, signed

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
    """指数相对基准的状态：图标 + 文字，不只靠颜色。"""
    if value is None:
        return Markup('<span class="flat">—</span>')
    cls, icon = ("up", "↗") if value > baseline + 0.5 else ("down", "↘") if value < baseline - 0.5 else ("flat", "→")
    return Markup(f'<span class="{cls}">{icon} {round(value)}</span>')


def gap(value):
    if value is None:
        return Markup('<span class="flat">—</span>')
    cls = "up" if value > 0.5 else "down" if value < -0.5 else "flat"
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
                  f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>{dots}</svg>')


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


_env = Environment(loader=FileSystemLoader(HERE), autoescape=select_autoescape(["j2"]),
                   trim_blocks=True, lstrip_blocks=True)
_env.filters.update(fi=fi, signed=signed, money=money, num=num, rich=rich, delta=delta, gap=gap, spark=spark,
                    bars=contribution_bars)


def points(value):
    """百分点变化。"""
    if value is None:
        return Markup('<span class="flat">—</span>')
    cls = "up" if value > 0.005 else "down" if value < -0.005 else "flat"
    return Markup(f'<span class="{cls}">{value:+.2f} pct</span>')


def render_funnel(result, base="/funnel"):
    def drill(value):
        next_dim = result["next_dimension"]
        query = {"week": result["week"], "dimension": next_dim, **result["filters"], result["dimension"]: value}
        return f"{base}?{urlencode(query)}"

    return _env.get_template("funnel.html.j2").render(f=result, base=base, drill=drill, pts=points)


def render_html(report, sections, queries=()):
    node_labels = {"sales": "Sales", "tickets": "Trans", "ab": "AB", "traffic": "Traffic", "cr": "CR",
                   "ai": "AI", "price": "Price/item", "qty": "Qty"}
    return _env.get_template("report.html.j2").render(
        r=report, s=sections, queries=list(queries), node_labels=node_labels,
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
        subprocess.run(
            [chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--user-data-dir={tmp}/profile",
             f"--print-to-pdf={pdf_path}", src.as_uri()],
            check=True, capture_output=True, timeout=120)
    return pdf_path


def html_to_pdf_bytes(html_text):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "out.pdf"
        html_to_pdf(html_text, path)
        return path.read_bytes()
