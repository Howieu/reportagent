# -*- coding: utf-8 -*-
"""
Prompt 模板库（从 notebook 原样迁移并集中管理）
================================================
设计要点（面试叙事）：
- 每个 prompt 都内置【业务术语词典】（Background Knowledge），LLM 不需要猜指标口径；
- 每个任务都是"分析 → 压缩为 ≤100 字总结"的两段式多轮对话；
- 明确的负向约束：宁可遗漏也不要逻辑混乱、门店无定价权禁止建议优化定价、英文术语不翻译；
- report_summary 使用 Output Format + Output Example 的 few-shot 强约束输出结构。
"""

SYSTEM_PROMPT = """- Role: 数据分析师
- Background: 用户需要将复杂的数据、分析逻辑和背景知识整合成一份智能诊断报告，以便更高效地传达关键信息和洞察。
- Profile: 你是一位经验丰富的数据分析师，擅长将复杂的数据转化为易于理解的报告，能够准确捕捉数据中的关键点，并以逻辑清晰、结构化的方式呈现。
- Skills: 你具备强大的数据处理能力、分析技巧和报告撰写技能，能够运用各种分析工具和方法，从数据中提取有价值的信息，并以报告的形式清晰地展示出来。
- Goals: 我们的目的是分析某家门店的某个HFB在某时段的销售表现。你需要创建一份结构清晰、内容丰富、易于理解的智能诊断报告，帮助用户快速把握数据的核心要点和分析结果。
- Constrains: 报告需要遵循逻辑性和条理性，确保数据的准确性和分析的可靠性，同时报告的格式和内容需要符合用户的具体要求。
"""

SUMMARY_PROMPT = """
- Detailed Requirements:
  - 请对你的回答内容进行概括，总长度不要超过100字。尽量避免直接展示具体数字，但可以提及相关的指标名称。注重提炼核心信息，并突出关键要点。

- Extra Requirements:
  1. 请使用中文回答，但不要将报告所涉及的英文术语翻译为中文，以免产生误解和混淆。
  2. 请参考Background Knowledge以便更好地理解和执行任务。
  3. 宁可遗漏一部分信息，也不要为了加入更多信息而导致逻辑错乱、自相矛盾或语序混乱，以免影响表达的清晰度和准确性。
  4. 表述应保持连贯流畅。例如，不使用"Sales ind.LY低于去年同期"等不准确的说法，而使用"Sales低于去年同期"这种更加准确且易于理解的说法。
  5. 请不要添加标题、加粗等Markdown格式。
"""

CHANNEL_TASK_PROMPT = """
- Background Knowledge:
  - 【Sales】Sales表示销售金额。销售金额通常用货币单位表示，例如美元或人民币，它反映了通过销售产品或服务获得的总收入。
  - 【ind.LY】ind.LY是index to last year的缩写，表示与去年同期之比。例如，ind.LY=123表示指标等于去年同期的123%。ind.LY小于一百表明低于去年同期，ind.LY大于一百表明高于去年同期，ind.LY等于一百表明与去年同期持平。
  - 【ind.Goal】ind.Goal是index to goal的缩写，表示与销售目标之比。例如，ind.Goal=123表示指标等于销售目标的123%。ind.Goal小于一百表明低于销售目标，ind.Goal大于一百表明高于销售目标，ind.Goal等于一百表明与销售目标持平。
  - 【Sales share】表示某一渠道的Sales在全渠道的Sales中的占比。
  - 【一级渠道】ONLINE和OFFLINE为一级渠道，分别表示线上渠道和线下渠道。
  - 【二级渠道】2B、2C(IDS)和2C(非IDS)为OFFLINE的二级渠道。RCMP、DTC和TMALL为ONLINE的二级渠道。
  - 【IB】IB表示对公业务。
  - 【2C(IDS)】2C(IDS)表示面向消费者的全屋定制服务。
  - 【2C(非IDS)】2C(非IDS)表示面向消费者的非IDS业务。
  - 【RCMP】RCMP表示远程销售与服务。
  - 【DTC】DTC表示自有线上渠道。
  - 【TMALL】TMALL表示天猫。
  - 【HFB】HFB是对商品的高层级分类。

- Detailed Requirements：
  - 输入数据描述：所选HFB按一级和二级渠道下钻的销售表现。
  - 任务1：请根据ONLINE的一级渠道的Sales ind.Goal和Sales ind.LY，概括ONLINE渠道的销售表现。
  - 任务2：当ONLINE的Sales ind.LY小于一百时，分析并指出ONLINE渠道中表现最差的二级渠道；当ONLINE的Sales ind.LY大于等于一百时，分析并指出ONLINE渠道中表现最好的二级渠道。
  - 任务3：请根据OFFLINE的一级渠道的Sales ind.Goal和Sales ind.LY，概括OFFLINE渠道的销售表现。

- Input:
 - ONLINE: {inputs_channel_l1_online}
    - DTC: {inputs_channel_l2_dtc}
    - RCMP: {inputs_channel_l2_rcmp}
    - TMALL: {inputs_channel_l2_tmall}
 - OFFLINE: {inputs_channel_l1_offline}
"""

ONLINE_TASK_PROMPT = """
- Background Knowledge:
  - 【Sales】Sales表示销售金额。销售金额通常用货币单位表示，例如美元或人民币，它反映了通过销售产品或服务获得的总收入。
  - 【Qty】Qty表示销售数量。销售数量是以数量单位表示，如件、个、千克等，代表了卖出的产品或服务的总数量。
  - 【ind.LY】ind.LY是index to last year的缩写，表示与去年同期之比。例如，ind.LY=123表示指标等于去年同期的123%。ind.LY小于一百表明低于去年同期，ind.LY大于一百表明高于去年同期，ind.LY等于一百表明与去年同期持平。
  - 【PIP】表示线上商品详情页的访客流量。
  - 【Tickets】表示成交单数。
  - 【Conv. Rate】表示转化率。Conv. Rate = Tickets / PIP。
  - 【Items/ticket】表示客件数。Items/Ticket = Qty / Tickets。
  - 【Price/item】表示件单价。Price/item = Sales / Qty。（注：门店没有对商品的定价权，因此请不要提出"优化定价策略"这一建议。）
  - 【HFB】HFB是对商品的高层级分类。

- Detailed Requirements：
    - 输入数据描述：
      - HFB KPI：所选HFB的DTC-RCMP渠道的KPI。
      - HFB Sales Tree：所选HFB的DTC-RCMP渠道的Sales Tree指标。
    - 任务1：请根据HFB KPI，简要概括HFB的DTC-RCMP渠道的销售表现。
    - 任务2：如果HFB的DTC-RCMP渠道的Sales同比增长，请指出Sales Tree中ind.LY最高的指标，反之，则指出Sales Tree中ind.LY最低的指标。分析DTC-RCMP销售表现变化的主要驱动因素。

- Input:
  - HFB KPI：{inputs_kpi}
  - HFB Sales Tree：{inputs_tree}
"""

REPORT_SUMMARY_TASK_PROMPT = """
- Background Knowledge:
  - 【Sales】Sales表示销售金额。销售金额通常用货币单位表示，例如美元或人民币，它反映了通过销售产品或服务获得的总收入。
  - 【Qty】Qty表示销售数量。销售数量是以数量单位表示，如件、个、千克等，代表了卖出的产品或服务的总数量。
  - 【ind.LY】ind.LY是index to last year的缩写，表示与去年同期之比。例如，ind.LY=123表示指标等于去年同期的123%。ind.LY<100表明低于去年同期，ind.LY>100表明高于去年同期，ind.LY=100表明与去年同期持平。
  - 【ind.Goal】ind.Goal是index to goal的缩写，表示与销售目标之比。例如，ind.Goal=123表示指标等于销售目标的123%。ind.Goal<100表明低于销售目标，ind.Goal>100表明高于销售目标，ind.Goal=100表明与销售目标持平。
  - 【YTD】YTD表示Year to Date，指从财年开始至选定分析时段结束。YTD可以反映当前财年的总体趋势，与所选时段所反映的短期趋势形成对比。
  - 【PIP】表示线上商品详情页的访客流量。
  - 【Tickets】表示成交单数。
  - 【Conv. Rate】表示转化率。Conv. Rate = Tickets / Visitation。
  - 【Items/ticket】表示客件数。Items/Ticket = Qty / Tickets。
  - 【Price/item】表示件单价。Price/item = Sales / Qty。（注：门店没有对商品的定价权，因此请将"优化定价策略"等建议改为"优化商品结构"。）
  - 【HFB】HFB是对商品的高层级分类。

- Detailed Requirements:
  - 请根据要求概括报告内容。输出应仿照Output Format格式，概括为4点，分别对应报告中的3个部分。
    1. 渠道分析：概括HFB的各渠道销售表现。ONLINE渠道和OFFLINE渠道各总结为1个句子，每个句子的括号内应包含对应渠道的Sales ind.Goal和Sales ind.LY。
    2. DTC-RCMP销售分析中的Sales Tree指标：概括影响DTC-RCMP销售表现变化的最主要Sales Tree指标（Sales Tree指标包括PIP、Conv. Rate、Items/ticket和Price/item）。如果HFB的DTC-RCMP渠道的Sales同比增长，请指出Sales Tree中ind.LY最高的指标，反之，则指出Sales Tree中ind.LY最低的指标。
    3. DTC-RCMP销售分析中的重点商品分析：指出影响DTC-RCMP销售表现变化的最主要PA。

- Output Format:
  - 输出应仿照如下格式，分为3点，其中除第1点为2个句子以外，其余每点均为1个句子。
  - 除第2点和第3点外，每个句子包含两个部分。
  - 第一部分（Part1）包含主要信息，文字加粗；第二部分（Part2）包含次要信息，文字不加粗。
  - 在第2至3点的Part1之后，应以括号括起相关指标，不加粗。
  - 输出格式如下，由三对书名号括起：
《《《
  1. **[渠道分析-ONLINE-Part1]**（ind.Goal: x, ind.LY: x），[渠道分析-ONLINE-Part2]。**[渠道分析-OFFLINE-Part1]**（ind.Goal: x, ind.LY: x）
  2. **[DTC-RCMP销售分析中的Sales Tree指标-Part1]**（[重点Sales Tree指标的ind.LY]）。
  3. **[DTC-RCMP销售分析中的重点商品分析-Part1]**。
》》》

- Output Example:
  - 以下为一个输出示例，由三对@符号括起：
@@@
  1. **ONLINE渠道超额完成销售目标，且销售额大幅增长**（ind.Goal: 105, ind.LY: 183），表现最佳的二级渠道是RCMP。**OFFLINE渠道未达到销售目标，但销售额较去年同期显著增长**（ind.Goal: 93, ind.LY: 147）
  2. **HFB的DTC-RCMP渠道销售表现显著提升，主要驱动因素是PIP的增加**（PIP ind.LY: 129）。
  3. **PA 0342是影响DTC-RCMP销售表现变化的最主要PA**。
@@@

- Extra Requirements:
  - 请使用中文回答，但不要将报告所涉及的英文术语翻译为中文，以免产生误解和混淆。
  - 宁可遗漏一部分信息，也不要为了加入更多信息而导致逻辑错乱、自相矛盾或语序混乱，以免影响表达的清晰度和准确性。
  - 再次强调，输出的每个句子的第二部分不要加粗。
  - 不要输出格式以外的内容，如标题、说明文字及符号等。
  - 输出时请不要包含三对书名号。
  - 对于第2、3点，概括时请强调分析范围是DTC-RCMP渠道，表述时请明确所指出的因素对于DTC-RCMP销售表现的影响方向。
  - 对于第2点，请以该格式展示括号内指标："指标名 ind.LY: 数值"。

- Input:
  - 输入内容如下，由三对圆括号括起，这是一份混合了HTML和Markdown格式的完整报告：
（（（
{inputs}
）））
"""
