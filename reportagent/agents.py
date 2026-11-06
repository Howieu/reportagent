"""产品里的 Agent 按职责命名。模型和服务商只通过环境变量配置，不写进代码。"""

REWRITE_AGENT = "问题改写 Agent"  # 把依赖上下文的追问改写成独立问题
PLANNING_AGENT = "辅助思考 Agent"  # 开关打开时，先梳理对问题的理解和取数思路
INTENT_AGENT = "意图识别 Agent"  # 判断用户要什么，选择工具并给出结构化参数，最后组织回答
REPAIR_AGENT = "回答修正 Agent"  # 回答没过校验时重写一次
WRITER_AGENT = "报告撰写 Agent"  # 把分析结果写成报告文字
