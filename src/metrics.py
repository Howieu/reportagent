# -*- coding: utf-8 -*-
"""
指标格式化工具（从 notebook 原样提炼）
======================================
display_number / display_metrics 是全系统的"数字唯一入口"：
报告里出现的每一个数字都由这里的代码计算和格式化，LLM 从不做算术，
只做语言组织——这是本 Demo 幻觉防控设计的核心。
"""

import pandas as pd


def display_number(num, fmt):
    """
    格式化数值，支持多种格式（整数百分比、带小数百分比、千单位等）

    参数:
    - num: 待格式化的数值
    - fmt: 格式化方式，支持 '%'/'%+'/'0'/'K'/'1%' 等
    """
    if pd.isna(num):
        return "≤0"
    if abs(num) < 1e-6:
        num = 0.0

    # 智能处理百分比格式
    if fmt in ['%', '%+', '1%']:
        # 仅 '1%'（Sales Share 等小数口径存储的字段）需要乘以 100。
        # 注：原 notebook 对 '%'/'%+' 也有 <10 则 ×100 的启发式，会把 100 口径下
        # 的真实小差值误放大（如 -1.2 显示为 -120），此处已修正——Demo 数据统一
        # 使用 100 口径（ind.LY=106 存为 106），无需缩放。
        if fmt == '1%' and abs(num) < 2:
            num = num * 100

        if fmt == '%':
            return f"{int(round(num, 0))}"  # 整数百分比
        elif fmt == '%+':
            val = int(round(num, 0))
            return f"+{val}" if val > 0 else f"{val}"  # 带符号整数百分比
        elif fmt == '1%':
            return f"{num:.1f}%"  # 带一位小数的百分比

    elif fmt == '0':
        return f"{int(round(num, 0))}"  # 整数
    elif fmt == 'K':
        num_k = num / 1000
        return f"{int(round(num_k, 0))}K"  # 千单位整数
    else:
        formatted = f"{num:.1f}"
        return formatted.replace('-0.0', '0.0')  # 默认保留一位小数


def display_metrics(metrics, perf, rolling_perf=None, avg_perf=None, name_mapping=None):
    """生成指标文本，支持多种格式和名称映射"""
    results = []

    for metric_name, others in metrics.items():
        # 解析参数：vs（对比项）、number_format（格式）、special（特殊标记）
        vs, number_format, special = (list(others) + [None, None])[:3]
        # 默认为'%'格式，确保兼容原有调用
        fmt = number_format if number_format is not None else '%'

        if pd.notna(perf[metric_name]):
            # 使用映射名称（如果提供了映射）
            display_name = name_mapping.get(metric_name, metric_name) if name_mapping else metric_name

            # 格式化数值
            result = f"{display_name}: {display_number(perf[metric_name], fmt)}"

            # 对比项逻辑不变
            if vs and len(vs) > 0:
                vs_result = []
                for comp in vs:
                    if comp.endswith("WKs") and rolling_perf is not None:
                        roll_val = rolling_perf.get(metric_name)
                        if pd.notna(roll_val):
                            diff = perf[metric_name] - roll_val
                            vs_result.append(f"{display_number(diff, '%+')} vs. {comp}")
                    elif comp == "avg" and avg_perf is not None:
                        avg_val = avg_perf.get(metric_name)
                        if pd.notna(avg_val):
                            diff = perf[metric_name] - avg_val
                            vs_result.append(f"{display_number(diff, '%+')} vs. {comp}")
                if vs_result:
                    result += f" ({'，'.join(vs_result)})"

            results.append(result)

    return '；'.join(results)
