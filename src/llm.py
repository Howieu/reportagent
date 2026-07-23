# -*- coding: utf-8 -*-
"""
LLM 抽象层
==========
两种工作模式：
1. **在线模式**：配置了 LLM_API_KEY 时，走 OpenAI 兼容接口（支持 OpenAI/Azure/DeepSeek/
   本地 vLLM 等任意兼容服务），使用 prompts.py 中的业务词典 prompt，保留 notebook 的
   "分析 → 压缩为 ≤100 字总结"两段式多轮对话；
2. **离线模式**（默认）：未配置 Key 或调用失败时，自动降级为规则模板生成结论文字。
   措辞质量略降，但结论结构、数值与在线模式完全一致——保证无网无 Key 也能现场演示。

无论哪种模式，报告中的数字都由代码计算（见 metrics.py），LLM 只负责语言组织。
"""

import os
from dataclasses import dataclass, field
from typing import Any, Protocol

from . import prompts


@dataclass(frozen=True)
class LLMConfig:
    """一次报告生成所使用的 LLM 配置；API Key 不参与 repr。"""

    provider: str = "template"
    api_key: str = field(default="", repr=False)
    base_url: str = "https://api.openai.com/v1"
    model: str = ""
    temperature: float = 0.5
    max_tokens: int = 800
    timeout: float = 60.0

    def __post_init__(self):
        supported = {"template", "openai_compatible", "anthropic"}
        if self.provider not in supported:
            raise ValueError(f"不支持的 LLM provider: {self.provider}")
        if not 0 <= self.temperature <= 2:
            raise ValueError("temperature 需在 0-2 之间")
        if self.max_tokens <= 0:
            raise ValueError("max_tokens 必须大于 0")

    @property
    def enabled(self) -> bool:
        return self.provider != "template" and bool(self.api_key and self.model)


@dataclass(frozen=True)
class LLMResponse:
    text: str = ""
    provider: str = "template"
    model: str = ""
    status: str = "template"
    usage: dict[str, int] = field(default_factory=dict)
    request_id: str = ""
    error_message: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "success" and bool(self.text)


class LLMProvider(Protocol):
    def generate(self, messages: list[dict[str, str]]) -> LLMResponse:
        ...


def _usage_dict(usage: Any, input_name: str, output_name: str) -> dict[str, int]:
    if usage is None:
        return {}
    input_tokens = getattr(usage, input_name, None)
    output_tokens = getattr(usage, output_name, None)
    result = {}
    if input_tokens is not None:
        result["input_tokens"] = int(input_tokens)
    if output_tokens is not None:
        result["output_tokens"] = int(output_tokens)
    return result


class OpenAICompatibleProvider:
    def __init__(self, config: LLMConfig, client=None):
        self.config = config
        if client is None:
            from openai import OpenAI

            client = OpenAI(
                api_key=config.api_key,
                base_url=config.base_url,
                timeout=config.timeout,
                max_retries=1,
            )
        self.client = client

    def generate(self, messages: list[dict[str, str]]) -> LLMResponse:
        response = self.client.chat.completions.create(
            model=self.config.model,
            messages=messages,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )
        text = response.choices[0].message.content or ""
        return LLMResponse(
            text=text.strip(),
            provider=self.config.provider,
            model=self.config.model,
            status="success",
            usage=_usage_dict(response.usage, "prompt_tokens", "completion_tokens"),
            request_id=getattr(response, "_request_id", "") or "",
        )


class AnthropicProvider:
    def __init__(self, config: LLMConfig, client=None):
        self.config = config
        if client is None:
            from anthropic import Anthropic

            client = Anthropic(
                api_key=config.api_key,
                timeout=config.timeout,
                max_retries=1,
            )
        self.client = client

    def generate(self, messages: list[dict[str, str]]) -> LLMResponse:
        system_parts = [
            item["content"] for item in messages if item.get("role") == "system"
        ]
        conversation = [
            {"role": item["role"], "content": item["content"]}
            for item in messages
            if item.get("role") in {"user", "assistant"}
        ]
        kwargs = {
            "model": self.config.model,
            "messages": conversation,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if system_parts:
            kwargs["system"] = "\n\n".join(system_parts)
        response = self.client.messages.create(**kwargs)
        text = "".join(
            getattr(block, "text", "")
            for block in response.content
            if getattr(block, "type", "text") == "text"
        )
        return LLMResponse(
            text=text.strip(),
            provider=self.config.provider,
            model=self.config.model,
            status="success",
            usage=_usage_dict(response.usage, "input_tokens", "output_tokens"),
            request_id=getattr(response, "_request_id", "") or "",
        )


def create_provider(config: LLMConfig, client=None) -> LLMProvider | None:
    if not config.enabled:
        return None
    if config.provider == "openai_compatible":
        return OpenAICompatibleProvider(config, client=client)
    if config.provider == "anthropic":
        return AnthropicProvider(config, client=client)
    return None


def generate_text(
    config: LLMConfig,
    messages: list[dict[str, str]],
    *,
    client=None,
) -> LLMResponse:
    """生成文本；错误信息只返回分类，不回显异常正文或密钥。"""

    provider = create_provider(config, client=client)
    if provider is None:
        return LLMResponse(provider="template", status="template")
    try:
        return provider.generate(messages)
    except Exception as exc:
        status_code = getattr(exc, "status_code", None)
        if status_code == 401:
            message = "API Key 无效或没有模型权限"
        elif status_code == 429:
            message = "请求达到速率或额度限制"
        elif exc.__class__.__name__.lower().find("timeout") >= 0:
            message = "模型服务请求超时"
        else:
            message = "模型服务调用失败"
        return LLMResponse(
            provider=config.provider,
            model=config.model,
            status="error",
            error_message=message,
        )

# ---------------------------------------------------------------------------
# 配置加载（环境变量优先，兼容项目根目录 .env）
# ---------------------------------------------------------------------------

def load_environment_config() -> LLMConfig:
    values = {}
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip()

    def setting(name, default=""):
        return os.environ.get(name, values.get(name, default))

    api_key = setting("LLM_API_KEY")
    model = setting("LLM_MODEL")
    provider = setting("LLM_PROVIDER")
    if not provider:
        provider = "openai_compatible" if api_key and model else "template"
    if not api_key or not model:
        provider = "template"
    return LLMConfig(
        provider=provider,
        api_key=api_key,
        base_url=setting("LLM_BASE_URL", "https://api.openai.com/v1"),
        model=model,
    )


def llm_available(config: LLMConfig | None = None) -> bool:
    return (config or load_environment_config()).enabled


# ---------------------------------------------------------------------------
# GPT_Agent：多轮对话封装（迁移自 notebook，客户端改为 OpenAI 兼容接口）
# ---------------------------------------------------------------------------

class GPT_Agent:
    """兼容原命名的 provider-neutral 多轮会话封装。"""

    def __init__(
        self,
        temperature=0.5,
        system_prompt=None,
        *,
        llm_config: LLMConfig | None = None,
        events: list[LLMResponse] | None = None,
    ):
        config = llm_config or load_environment_config()
        self.config = LLMConfig(
            provider=config.provider,
            api_key=config.api_key,
            base_url=config.base_url,
            model=config.model,
            temperature=temperature,
            max_tokens=config.max_tokens,
            timeout=config.timeout,
        )
        self.events = events if events is not None else []
        if system_prompt is None:
            system_prompt = "Assistant is a large language model trained by OpenAI."
        self.conversation = [{"role": "system", "content": system_prompt}]

    def talk(self, user_prompt) -> LLMResponse:
        self.conversation.append({"role": "user", "content": user_prompt})
        response = generate_text(self.config, self.conversation)
        self.events.append(response)
        if response.ok:
            self.conversation.append({"role": "assistant", "content": response.text})
        return response


# ---------------------------------------------------------------------------
# 离线模板生成器（规则降级，数值与在线模式完全一致）
# ---------------------------------------------------------------------------

def _trend_word(ind_ly):
    return "高于" if ind_ly >= 100 else "低于"


def _goal_word(ind_goal):
    return "超额完成销售目标" if ind_goal >= 100 else "未达销售目标"


def _channel_summary_offline(raw):
    on = raw["ONLINE"]
    off = raw["OFFLINE"]
    l2 = raw["L2"]  # {channel: sales_ind_ly}
    pick = max(l2, key=l2.get) if on["sales_ind_ly"] >= 100 else min(l2, key=l2.get)
    pick_word = "最佳" if on["sales_ind_ly"] >= 100 else "最差"
    return (
        f"ONLINE渠道的Sales{_goal_word(on['sales_ind_goal'])}，且Sales{_trend_word(on['sales_ind_ly'])}去年同期，"
        f"其中表现{pick_word}的二级渠道是{pick}。"
        f"OFFLINE渠道的Sales{_goal_word(off['sales_ind_goal'])}，Sales{_trend_word(off['sales_ind_ly'])}去年同期。"
    )


def _online_summary_offline(raw):
    sales_ly = raw["sales_ind_ly"]
    tree = raw["tree"]  # {指标名: ind_ly}
    if sales_ly >= 100:
        driver = max(tree, key=tree.get)
        direction = "提升"
    else:
        driver = min(tree, key=tree.get)
        direction = "下滑"
    return (
        f"HFB的DTC-RCMP渠道Sales{'同比增长' if sales_ly >= 100 else '同比下滑'}，"
        f"Sales Tree中{driver}的ind.LY{'最高' if sales_ly >= 100 else '最低'}，"
        f"是销售表现{direction}的主要驱动因素。"
    )


def _report_summary_offline(raw):
    ch = raw["channel"]
    on, off = ch["ONLINE"], ch["OFFLINE"]
    l2 = ch["L2"]
    pick = max(l2, key=l2.get) if on["sales_ind_ly"] >= 100 else min(l2, key=l2.get)
    pick_word = "最佳" if on["sales_ind_ly"] >= 100 else "最差"

    tree = raw["online"]["tree"]
    sales_ly = raw["online"]["sales_ind_ly"]
    driver = max(tree, key=tree.get) if sales_ly >= 100 else min(tree, key=tree.get)
    driver_ly = int(round(tree[driver]))
    trend_word = "提升" if sales_ly >= 100 else "下滑"

    top_pa = raw.get("top_pa") or "N/A"
    pa_direction = raw.get("top_pa_direction", "变化")

    return (
        f"1. **ONLINE渠道{_goal_word(on['sales_ind_goal'])}，Sales{_trend_word(on['sales_ind_ly'])}去年同期**"
        f"（ind.Goal: {int(round(on['sales_ind_goal']))}, ind.LY: {int(round(on['sales_ind_ly']))}），"
        f"表现{pick_word}的二级渠道是{pick}。"
        f"**OFFLINE渠道{_goal_word(off['sales_ind_goal'])}**"
        f"（ind.Goal: {int(round(off['sales_ind_goal']))}, ind.LY: {int(round(off['sales_ind_ly']))}）\n"
        f"2. **HFB的DTC-RCMP渠道销售表现{trend_word}，主要驱动因素是{driver}的变化**"
        f"（{driver} ind.LY: {driver_ly}）。\n"
        f"3. **PA {top_pa}是影响DTC-RCMP销售表现{pa_direction}的最主要PA**。"
    )


# ---------------------------------------------------------------------------
# 统一入口：优先在线模式，失败/未配置自动降级
# ---------------------------------------------------------------------------

def channel_summary(
    inputs_l1,
    inputs_l2,
    raw,
    use_llm=True,
    *,
    llm_config: LLMConfig | None = None,
    events: list[LLMResponse] | None = None,
):
    """渠道分析结论（对应 notebook 的 channel_llm）。"""
    config = llm_config or load_environment_config()
    if use_llm and config.enabled:
        agent = GPT_Agent(
            system_prompt=prompts.SYSTEM_PROMPT,
            llm_config=config,
            events=events,
        )
        first = agent.talk(prompts.CHANNEL_TASK_PROMPT.format(
            inputs_channel_l1_online=inputs_l1["ONLINE"],
            inputs_channel_l2_dtc=inputs_l2["DTC"],
            inputs_channel_l2_rcmp=inputs_l2["RCMP"],
            inputs_channel_l2_tmall=inputs_l2["TMALL"],
            inputs_channel_l1_offline=inputs_l1["OFFLINE"],
        ))
        if first.ok:
            second = agent.talk(prompts.SUMMARY_PROMPT)
            if second.ok:
                return second.text
    return _channel_summary_offline(raw)


def online_summary(
    inputs,
    raw,
    use_llm=True,
    *,
    llm_config: LLMConfig | None = None,
    events: list[LLMResponse] | None = None,
):
    """DTC-RCMP 销售分析结论（对应 notebook 的 online_llm）。"""
    config = llm_config or load_environment_config()
    if use_llm and config.enabled:
        agent = GPT_Agent(
            system_prompt=prompts.SYSTEM_PROMPT,
            llm_config=config,
            events=events,
        )
        first = agent.talk(prompts.ONLINE_TASK_PROMPT.format(
            inputs_kpi=inputs[0], inputs_tree=inputs[1]))
        if first.ok:
            second = agent.talk(prompts.SUMMARY_PROMPT)
            if second.ok:
                return second.text
    return _online_summary_offline(raw)


def report_summary(
    full_report_text,
    raw,
    use_llm=True,
    *,
    llm_config: LLMConfig | None = None,
    events: list[LLMResponse] | None = None,
):
    """业绩总结（对应 notebook 的 report_summary，few-shot 强格式约束）。"""
    config = llm_config or load_environment_config()
    if use_llm and config.enabled:
        agent = GPT_Agent(
            system_prompt=prompts.SYSTEM_PROMPT,
            llm_config=config,
            events=events,
        )
        response = agent.talk(
            prompts.REPORT_SUMMARY_TASK_PROMPT.format(inputs=full_report_text)
        )
        if response.ok:
            return response.text
    return _report_summary_offline(raw)
