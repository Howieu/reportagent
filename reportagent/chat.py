"""对话编排：工具循环，边执行边产出事件，最终回答过数字校验。"""

import difflib
import json
import re

from .funnel import latest_funnel_week
from .narrative import ENTITY_DOWN, ENTITY_UP, check_text
from .tools import SCHEMAS, ToolError, Tools

MAX_ROUNDS = 4
TOOL_LABEL = {"query_metrics": "取数问题", "explain_change": "归因分析", "generate_report": "生成报告", "list_values": "查询维度取值", "funnel_analysis": "漏斗分析"}


def match_verified(question, semantic):
    best, score = None, 0.0
    for item in semantic.verified_questions:
        s = difflib.SequenceMatcher(None, question, item["question"]).ratio()
        if s > score:
            best, score = item, s
    return best if score >= 0.6 else None


def normalize_ranking(args, question):
    """排名方向和条数不完全交给模型：实测它会把“下滑最多”查成增长最多。"""
    if re.search(r"下滑|下降|下跌|最低|最差|最少|倒数|Bottom", question, re.IGNORECASE):
        args["ascending"] = True
    found = re.search(r"(?:前|Top\s*|最\S{0,4}的?\s*)(\d+)|(\d+)\s*(?:个|家|款|条)", question, re.IGNORECASE)
    if not args.get("limit") and found:
        args["limit"] = int(found.group(1) or found.group(2))


def describe_call(name, args):
    if name == "query_metrics":
        parts = [f"指标 {'、'.join(args.get('metrics') or [])}"]
        if args.get("dimensions"):
            parts.append(f"按 {'、'.join(args['dimensions'])} 分组")
        if args.get("filters"):
            parts.append("筛选 " + "，".join(f"{k}={v}" for k, v in args["filters"].items()))
        if args.get("week"):
            parts.append(f"第 {args['week']} 周")
        return "；".join(parts)
    if name == "funnel_analysis":
        return "按" + str(args.get("dimension") or "默认维度") + "拆分" + (f"；第 {args['week']} 周" if args.get("week") else "")
    if name in {"explain_change", "generate_report"}:
        return f"{args.get('store', '')} · {args.get('category', '')}" + (f" · 第 {args['week']} 周" if args.get("week") else "")
    return f"查看 {args.get('dimension', '')}"


def system_prompt(semantic, tools: Tools, latest_week):
    stores = tools.wh.stores()
    store_list = "、".join(f"{r['store']} {r['name']}" for _, r in stores.head(30).iterrows())
    examples = "\n".join(
        f"- “{q['question']}” → {q['tool']} {json.dumps(q['args'], ensure_ascii=False)}" for q in semantic.verified_questions)
    glossary = "\n".join(f"- {x}" for x in [*semantic.glossary, *semantic.constraints])
    labels = "、".join(f"{k}={v}" for k, v in semantic.labels.items())
    funnel_line = ""
    if semantic.has("funnel"):
        funnel_line = (f"漏斗问题用 funnel_analysis，最近完整周是 {latest_funnel_week(tools.wh)}，和销售周次不同。"
                       "它的数据是另一家公司的行为日志，不要和销售数字放在一起算。")
    return f"""你是零售数据分析助手，通过工具回答 {semantic.name} 的问题。

目标：给出准确、简短、能核对的回答。
数据范围：门店 {store_list}。品类：{'、'.join(tools.values('category'))}。渠道：{'、'.join(tools.values('channel'))}。
销售数据最近完整周是 {latest_week}，“上周”就是这一周。
{funnel_line}

维度含义：{labels}。例如“品牌”对应 family，“子类”对应 subcategory。

规则：
- 只要涉及数据就调用工具，不要凭记忆回答。
- 问“为什么、什么原因、涨跌”时，只要有门店和品类，就调用一次 explain_change，它已经包含分解和下钻，不需要再拆查询。
- 能一次查完就不要多查。
- 问题有歧义、缺少必要信息（比如要报告但没说门店），先追问一句。周次和渠道可以用默认值。
- 问题超出销售、目标、客流、库存的范围，直接说明做不到，并说能回答什么。
- 工具返回错误时，根据提示修正参数或问用户。
- 工具结果会以表格和图表展示给用户，你只需写 1 到 3 句结论，不要重复表格。
- 引用数字必须照抄工具结果里的写法，不得换算、四舍五入或计算新数字。
- vs LY 119 表示是去年的 119%，不能写成增长 119%，也不要换算成增幅。
- 不要编造原因。工具结果没有说明的，就不要下因果结论。
- 不要用 Markdown 表格，不要把表格内容逐行重复一遍。
- 不要自己给对象下“最佳、最差”的判断，除非工具结果明确这样写。
- “排除新品后下降”不等于整体下降，要照原话说。

术语：
{glossary}

示例：
{examples}
"""


class ChatAgent:
    def __init__(self, app):
        self.app = app
        self.tools = Tools(app)

    def run(self, question, history=(), assist=False):
        """生成事件字典：thinking / matched / task / result / answer / error。"""
        llm = self.app.llm
        if not llm or not llm.enabled:
            yield {"type": "error", "message": "没有配置 LLM_API_KEY，对话不可用。你仍然可以用“生成报告”直接出报告。"}
            return
        semantic = self.app.semantic
        latest_week = self.app.wh.latest_complete_week()
        messages = [{"role": "system", "content": system_prompt(semantic, self.tools, latest_week)}]
        messages += [{"role": m["role"], "content": m["content"]} for m in list(history)[-8:] if m.get("content")]
        matched = match_verified(question, semantic)
        if matched:
            yield {"type": "matched", "question": matched["question"]}
            messages.append({"role": "system", "content": (
                f"问答库里有已核对的相似问题“{matched['question']}”，做法是 {matched['tool']}，参数示例 "
                f"{json.dumps(matched['args'], ensure_ascii=False)}。除非用户问的范围不同，否则照此调用。")})
        messages.append({"role": "user", "content": question})

        if assist:
            yield {"type": "thinking", "status": "running"}
            thought = self._think(messages)
            yield {"type": "thinking", "status": "done", "text": thought}
            if thought:
                messages.append({"role": "assistant", "content": thought})
                messages.append({"role": "user", "content": "按这个思路调用工具完成。"})

        results, facts = [], [question, latest_week]
        task_no = 0
        for _ in range(MAX_ROUNDS):
            try:
                message = llm.chat(messages, tools=SCHEMAS, temperature=0.1)
            except Exception as exc:
                yield {"type": "error", "message": f"模型调用失败（{type(exc).__name__}），请稍后重试。"}
                return
            calls = message.tool_calls or []
            if not calls:
                text = message.content or ""
                problem = self._problem(text, results, facts)
                if problem and results:  # 给一次修正机会，还不行再用规则结论
                    try:
                        text = llm.chat([*messages, {"role": "assistant", "content": text}, {"role": "user", "content": (
                            f"这段回答没通过校验：{problem}。请重写，数字必须照抄工具结果，不要换算。")}], temperature=0).content or ""
                    except Exception:
                        pass
                yield from self._finish(text, results, facts, question)
                return
            messages.append({"role": "assistant", "content": message.content or "", "tool_calls": [
                {"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments}}
                for c in calls]})
            pending = []
            for call in calls:
                task_no += 1
                try:
                    args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                if call.function.name == "query_metrics":
                    normalize_ranking(args, question)
                pending.append((task_no, call, args))
                yield {"type": "task", "id": task_no, "status": "running", "label": TOOL_LABEL.get(call.function.name, call.function.name),
                       "text": describe_call(call.function.name, args)}
            for number, call, args in pending:
                try:
                    result = self.tools.call(call.function.name, args)
                except ToolError as exc:
                    yield {"type": "task", "id": number, "status": "retry", "message": str(exc)}
                    messages.append({"role": "tool", "tool_call_id": call.id, "content": f"错误：{exc}"})
                    continue
                except Exception as exc:
                    yield {"type": "task", "id": number, "status": "failed", "message": f"执行异常（{type(exc).__name__}）"}
                    messages.append({"role": "tool", "tool_call_id": call.id, "content": "错误：查询执行失败，请换一种方式或告知用户。"})
                    continue
                yield {"type": "task", "id": number, "status": "done"}
                public = {k: v for k, v in result.items() if k not in {"facts", "fallback", "verbatim"}}
                if result["kind"] != "values":
                    yield {"type": "result", **public}
                results.append(result)
                facts.append(result["facts"])
                messages.append({"role": "tool", "tool_call_id": call.id, "content": result["facts"][:6000]})
            if results and all(r.get("verbatim") for r in results):
                yield from self._finish("", results, facts, question)
                return
        yield from self._finish("", results, facts, question)

    def _think(self, messages):
        try:
            prompt = messages + [{"role": "user", "content": (
                "先不要调用工具。用 2 到 4 句写出你对问题的理解、涉及的指标和维度、准备怎么取数。不要写任何具体数值，不用 Markdown。")}]
            text = (self.app.llm.chat(prompt, temperature=0.2, max_tokens=300).content or "").strip()
        except Exception:
            return ""
        text = text.replace("**", "")
        return "" if check_text(text, "\n".join(m["content"] for m in messages)) else text

    def _problem(self, text, results, facts):
        problem = check_text(text, "\n".join(facts), banned=self.app.semantic.banned_phrases)
        if not problem and not results and (re.search(ENTITY_UP, text) or re.search(ENTITY_DOWN, text)):
            problem = "没有取数却给出了涨跌结论"
        return problem

    def _finish(self, text, results, facts, question):
        text = (text or "").strip()
        verbatim = next((r for r in reversed(results) if r.get("verbatim")), None)
        if verbatim and not text:
            text = verbatim["fallback"]
        problem = self._problem(text, results, facts)
        mode = "model"
        if problem:
            mode = "fallback"
            if results:
                text = results[-1]["fallback"]
            else:
                text = "这个问题我暂时回答不了。我可以查询销售、目标、客流和库存，或者生成周度诊断报告。"
        suggestions = next((r["suggestions"] for r in reversed(results) if r.get("suggestions")), [])
        yield {"type": "answer", "text": text, "mode": mode, "note": problem, "suggestions": suggestions[:3]}
