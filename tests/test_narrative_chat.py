import json
from types import SimpleNamespace as NS

from reportagent.analysis import analyze
from reportagent.chat import ChatAgent, normalize_ranking
from reportagent.narrative import check_text, forbids_for, write_sections
from reportagent.render import render_html


def test_number_and_direction_guards():
    assert check_text("Sales vs LY 119", "vs LY 119") is None
    assert "没有的数字" in check_text("增长到 120", "vs LY 119")
    assert check_text("同比上升 119%", "vs LY 119") == "把指数写成了增幅"
    assert check_text("Sales 高于去年同期", "vs LY 90", forbids_for([90]))
    assert check_text("未达成目标", "x", forbids_for([], [90])) is None
    assert check_text("各渠道均优于目标", "x", forbids_for([], [90, 110]))
    assert check_text("APP 表现优于去年同期", "x", entities=[("APP", 79)]) == "APP 的方向写反了"
    assert check_text("建议降价", "x", banned=["降价"]) == "命中禁用词：降价"


def test_ranking_normalization():
    a = {}
    normalize_ranking(a, "上周同比下滑最多的 5 个品牌")
    assert a == {"ascending": True, "limit": 5}
    b = {"ascending": False, "limit": 3}
    normalize_ranking(b, "下滑最多的 5 个")
    assert b == {"ascending": True, "limit": 3}


class FakeLLM:
    enabled = True
    model = "fake"

    def __init__(self, script):
        self.script = list(script)

    def chat(self, messages, tools=None, **_):
        return self.script.pop(0)


def call(name, args, id="c1"):
    return NS(content="", tool_calls=[NS(id=id, function=NS(name=name, arguments=json.dumps(args)))])


def text(s):
    return NS(content=s, tool_calls=None)


def run(app, script, q="上周各品类销售额"):
    old = app.llm
    app.llm = FakeLLM(script)
    try:
        return list(ChatAgent(app).run(q))
    finally:
        app.llm = old


def test_chat_query_answer_passes_with_copied_numbers(demo_app):
    agent = ChatAgent(demo_app)
    table = agent.tools.query_metrics({"metrics": ["sales", "sales_vs_ly"], "dimensions": ["category"]})
    first = table["display"][0]
    ev = run(demo_app, [call("query_metrics", {"metrics": ["sales", "sales_vs_ly"], "dimensions": ["category"]}),
                        text(f"{first['category']} 最高，Sales {first['sales']}。")])
    types = [e["type"] for e in ev]
    assert "result" in types and ev[-1]["type"] == "answer" and ev[-1]["mode"] == "model"


def test_chat_fabricated_number_falls_back(demo_app):
    ev = run(demo_app, [call("query_metrics", {"metrics": ["sales"], "dimensions": ["category"]}),
                        text("销售额 123456789 元"), text("还是 123456789 元")])
    assert ev[-1]["mode"] == "fallback" and "123456789" not in ev[-1]["text"]
    assert "排在第一" in ev[-1]["text"]


def test_chat_bad_filter_returns_retry_hint(demo_app):
    ev = run(demo_app, [call("query_metrics", {"metrics": ["sales"], "filters": {"store": "火星"}}), text("没有这家门店，请换一家。")])
    retry = [e for e in ev if e.get("status") == "retry"]
    assert retry and "火星" in retry[0]["message"]


def test_chat_store_name_and_synonym_resolve(demo_app):
    tools = ChatAgent(demo_app).tools
    assert tools.resolve("store", "静安") == "S01"
    assert tools.resolve("category", "护肤") == "SKINCARE"


def test_chat_trend_is_chronological(demo_app):
    t = ChatAgent(demo_app).tools.query_metrics({"metrics": ["sales"], "dimensions": ["week"], "last_weeks": 6, "filters": {"region": "华东"}})
    weeks = [r["week"] for r in t["rows"]]
    assert weeks == sorted(weeks) and len(weeks) == 6 and t["chart"]["type"] == "line"


def test_chat_region_rollup_matches_store_sum(demo_app):
    tools = ChatAgent(demo_app).tools
    by_region = tools.query_metrics({"metrics": ["sales"], "dimensions": ["region"], "limit": 50})
    by_store = tools.query_metrics({"metrics": ["sales"], "dimensions": ["store"], "limit": 50})
    assert sum(r["sales"] for r in by_region["rows"]) == sum(r["sales"] for r in by_store["rows"])


def test_goal_grain_is_rejected_not_wrong(demo_app):
    import pytest

    from reportagent.tools import ToolError
    with pytest.raises(ToolError, match="vs Goal"):
        ChatAgent(demo_app).tools.query_metrics({"metrics": ["sales_vs_goal"], "dimensions": ["family"]})


def test_no_llm_chat_explains(demo_app):
    ev = list(ChatAgent(demo_app).run("你好"))
    assert ev[0]["type"] == "error"


def test_report_renders_with_synthetic_label_and_escapes(demo_app, week):
    r = analyze(demo_app.wh, "S01", "SKINCARE", week)
    r["store_name"] = "<script>alert(1)</script>"
    html = render_html(r, write_sections(r, demo_app.semantic, None))
    assert "模拟数据" in html and "<script>alert" not in html and "业绩总结" in html


def test_server_endpoints_isolate_visitors(demo_app, week):
    from fastapi.testclient import TestClient

    from reportagent.server import create_app
    api = create_app(demo_app)
    client, other = TestClient(api), TestClient(api)
    meta = client.get("/api/meta").json()
    assert meta["week"] == week and meta["synthetic"] is True
    made = client.post("/api/reports", json={"store": "S01", "category": "SKINCARE", "week": week}).json()
    page = client.get(f"/reports/{made['id']}")
    assert page.status_code == 200 and "default-src 'none'" in page.headers["content-security-policy"]
    assert client.post("/api/reports", json={"store": "S01", "category": "SKINCARE", "week": "209901"}).status_code == 400
    assert client.get("/reports/not-a-report").status_code == 404
    chat = client.post("/api/chat", json={"message": "你好"})
    assert "error" in chat.text
    convs = [c for c in client.get("/api/conversations").json() if c["id"] != made["conversation"]]
    assert len(convs) == 1
    assert other.get("/api/conversations").json() == []                 # 其他访客看不到
    assert other.get(f"/api/conversations/{convs[0]['id']}").status_code == 404
    other.delete(f"/api/conversations/{convs[0]['id']}")
    assert len(client.get("/api/conversations").json()) == 2            # 也删不掉
    assert client.delete(f"/api/conversations/{convs[0]['id']}").status_code == 200
    assert [c["id"] for c in client.get("/api/conversations").json()] == [made["conversation"]]


def test_projects_group_tasks_and_are_owner_scoped(demo_app, week):
    from fastapi.testclient import TestClient

    from reportagent.server import create_app
    api = create_app(demo_app)
    client, other = TestClient(api), TestClient(api)
    project = client.post("/api/projects", json={"name": "华东复盘"}).json()
    made = client.post("/api/reports", json={"store": "S01", "category": "SKINCARE", "week": week, "project": project["id"]}).json()
    task = next(c for c in client.get("/api/conversations").json() if c["id"] == made["conversation"])
    assert task["project"] == project["id"]
    blocks = client.get(f"/api/conversations/{task['id']}").json()["messages"][1]["blocks"]
    assert any(b.get("kind") == "report" for b in blocks)              # 可以回放并打开报告
    assert other.get("/api/projects").json() == []
    other.delete(f"/api/projects/{project['id']}")
    assert len(client.get("/api/projects").json()) == 1                # 其他访客删不掉
    other_task = other.post("/api/reports", json={"store": "S01", "category": "SKINCARE", "week": week, "project": project["id"]}).json()
    assert next(c for c in other.get("/api/conversations").json() if c["id"] == other_task["conversation"])["project"] is None
    client.patch(f"/api/conversations/{task['id']}", json={"project": None, "move": True})
    assert next(c for c in client.get("/api/conversations").json() if c["id"] == task["id"])["project"] is None
    client.patch(f"/api/conversations/{task['id']}", json={"project": project["id"], "move": True})
    client.delete(f"/api/projects/{project['id']}")
    assert client.get("/api/projects").json() == []
    assert next(c for c in client.get("/api/conversations").json() if c["id"] == task["id"])["project"] is None  # 任务保留


def test_rate_limit():
    from reportagent.server import RateLimiter
    limit = RateLimiter(2)
    assert limit.allow("a") and limit.allow("a") and not limit.allow("a") and limit.allow("b")
