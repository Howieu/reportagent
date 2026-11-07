"""命令行入口：演示数仓、连接检查、批量出报告、启动工作台。"""

import argparse
import os
import sys
from pathlib import Path


def _split(text):
    return [x.strip() for x in text.split(",") if x.strip()]


def cmd_demo(args):
    from .demo import TARGET_WEEK, build

    rows = build(args.path)
    print(f"已生成 {args.path}（{rows:,} 行销售明细，数据全部为合成），目标周 {TARGET_WEEK}")


def cmd_load_real(args):
    from .realdata import build

    print(build(args.path, args.olist, args.retailrocket))


def cmd_check(args):
    from .service import App

    app = App(args.semantic)
    failed = 0
    for name, table, problem in app.wh.check():
        print(f"{'失败' if problem else '通过'}  {name:<13} {table}" + (f"  {problem}" if problem else ""))
        failed += bool(problem)
    if failed:
        return 1
    print(f"最新数据 {app.wh.latest_date()}，最近完整周 {app.wh.latest_complete_week()}")
    return 0


def cmd_report(args):
    from .service import App
    from .warehouse import DataUnavailable

    app = App(args.semantic)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stores = _split(args.store)
    if stores == ["all"]:
        stores = app.wh.stores()["store"].tolist()
    categories = _split(args.category)
    if categories == ["all"]:
        categories = app.wh.distinct_values("sales", "category")
    code = 0
    for store in stores:
        for category in categories:
            try:
                meta, _, sections = app.report(store, category, args.week, args.channel, args.focus, use_llm=not args.no_llm)
            except (DataUnavailable, ValueError) as exc:
                print(f"跳过 {store} {category}：{exc}", file=sys.stderr)
                code = 1
                continue
            name = f"{store}_{category.replace(' ', '')}_wk{meta['week']}"
            (out / f"{name}.html").write_text(app.report_html(meta["id"]), encoding="utf-8")
            line = f"{out / name}.html"
            if not args.no_pdf:
                try:
                    (out / f"{name}.pdf").write_bytes(app.pdf(meta["id"]))
                    line += " + .pdf"
                except Exception as exc:
                    print(f"PDF 失败：{exc}", file=sys.stderr)
                    code = 1
            print(line)
    return code


def cmd_forecast(args):
    from .forecast import forecast
    from .service import App
    from .warehouse import DataUnavailable

    app = App(args.semantic, llm=False)
    try:
        f = forecast(app.wh, args.store, args.category, args.metric, args.week)
        html_text = app.forecast_html(args.store, args.category, args.metric, args.week)
    except (DataUnavailable, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1
    if f["origin_note"]:
        print(f["origin_note"])
    fmt = f["fmt"]
    for r in f["rows"]:
        span = f"{fmt(r['low'])} 至 {fmt(r['high'])}" if r["low"] is not None else "—"
        model = f"{r['model_wape']:.1f}%" if r["model_wape"] is not None else "—"
        print(f"{r['week']}  {fmt(r['forecast'])}  区间 {span}  来源 {r['method']}  回测误差 模型 {model} / {r['baseline_name']} {r['baseline_wape']:.1f}%")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"forecast_{args.store or 'all'}_{(args.category or 'all').replace(' ', '')}_{args.metric}_wk{f['origin']}.html"
    path.write_text(html_text, encoding="utf-8")
    print(path)
    return 0


def cmd_checkup(args):
    from .checkup import checkup
    from .service import App
    from .warehouse import DataUnavailable

    app = App(args.semantic, llm=False)
    try:
        c = checkup(app.wh, args.store, args.category, args.metric, args.week)
        html_text = app.checkup_html(args.store, args.category, args.metric, args.week)
    except (DataUnavailable, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1
    if c["origin_note"]:
        print(c["origin_note"])
    fmt = c["fmt"]
    print(f"第 {c['week']} 周检查 {c['checked']} 条序列，{c['flagged']} 条明显异常")
    for a in c["items"]:
        print(f"{a['store_name']} {a['category']}  实际 {fmt(a['actual'])}  预期 {fmt(a['expected'])}  差 {fmt(a['impact'])}  {a['why']['hint']}")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"checkup_{args.store or 'all'}_{(args.category or 'all').replace(' ', '')}_{args.metric}_wk{c['week']}.html"
    path.write_text(html_text, encoding="utf-8")
    print(path)
    return 0


def cmd_serve(args):
    import uvicorn

    from .config import load_env

    load_env()
    if args.semantic:
        os.environ["REPORTAGENT_SEMANTIC"] = args.semantic
    uvicorn.run("reportagent.server:create_app", factory=True, host=args.host, port=int(os.environ.get("PORT", args.port)),
                proxy_headers=True, forwarded_allow_ips="*")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="reportagent", description="连接零售数仓，对话或直接产出诊断报告")
    parser.add_argument("--semantic", help="语义配置路径，默认 semantic.demo.yaml")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("demo", help="生成合成演示数仓")
    p.add_argument("--path", default="data/demo.duckdb")
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("load-real", help="把 Olist 和 RetailRocket 原始 CSV 导入 DuckDB")
    p.add_argument("--path", default="data/real.duckdb")
    p.add_argument("--olist", default="data/raw/olist")
    p.add_argument("--retailrocket", default="data/raw/retailrocket")
    p.set_defaults(func=cmd_load_real)

    p = sub.add_parser("check", help="检查数仓连接和字段映射")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("report", help="生成报告，可批量")
    p.add_argument("--store", required=True, help="门店 ID，逗号分隔，或 all")
    p.add_argument("--category", required=True, help="品类，逗号分隔，或 all")
    p.add_argument("--week", help="周次 YYYYWW，默认最近完整周")
    p.add_argument("--channel")
    p.add_argument("--focus", choices=["sales", "qty"])
    p.add_argument("--out", default="reports")
    p.add_argument("--no-pdf", action="store_true")
    p.add_argument("--no-llm", action="store_true", help="只用规则模板，不调用模型")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("forecast", help="预测未来 4 周并输出回测和 SHAP 归因")
    p.add_argument("--store", help="门店 ID，不填表示全部")
    p.add_argument("--category", help="品类，不填表示全部")
    p.add_argument("--metric", choices=["sales", "qty"], default="sales", help="sales 销售额，qty 销量")
    p.add_argument("--week", help="预测起点 YYYYWW，默认最近完整周")
    p.add_argument("--out", default="reports")
    p.set_defaults(func=cmd_forecast)

    p = sub.add_parser("checkup", help="经营体检：找出明显偏离预期的范围，并定位原因")
    p.add_argument("--store", help="门店 ID，不填表示全部")
    p.add_argument("--category", help="品类，不填表示全部")
    p.add_argument("--metric", choices=["sales", "qty"], default="sales", help="sales 销售额，qty 销量")
    p.add_argument("--week", help="周次 YYYYWW，默认最近完整周")
    p.add_argument("--out", default="reports")
    p.set_defaults(func=cmd_checkup)

    p = sub.add_parser("serve", help="启动对话和报告工作台")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8501)
    p.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
