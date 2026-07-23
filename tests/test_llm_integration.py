from src import llm
from src.llm import LLMConfig, LLMResponse


RAW_CHANNEL = {
    "ONLINE": {"sales_ind_goal": 98.0, "sales_ind_ly": 92.0},
    "OFFLINE": {"sales_ind_goal": 101.0, "sales_ind_ly": 105.0},
    "L2": {"DTC": 90.0, "RCMP": 95.0, "TMALL": 80.0},
}


def test_environment_without_key_forces_template(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_MODEL", "claude-example")
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    config = llm.load_environment_config()

    assert config.provider == "template"
    assert not config.enabled


def test_environment_can_select_anthropic(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_MODEL", "claude-example")
    monkeypatch.setenv("LLM_API_KEY", "environment-secret")

    config = llm.load_environment_config()

    assert config.provider == "anthropic"
    assert config.model == "claude-example"
    assert config.enabled


def test_channel_summary_falls_back_and_records_provider_error(monkeypatch):
    events = []

    def fake_generate(config, messages, **kwargs):
        return LLMResponse(
            provider=config.provider,
            model=config.model,
            status="error",
            error_message="API Key 无效或没有模型权限",
        )

    monkeypatch.setattr(llm, "generate_text", fake_generate)
    config = LLMConfig(
        provider="openai_compatible",
        api_key="secret-value",
        model="example-model",
    )

    result = llm.channel_summary(
        {"ONLINE": "on", "OFFLINE": "off"},
        {"DTC": "dtc", "RCMP": "rcmp", "TMALL": "tmall"},
        RAW_CHANNEL,
        llm_config=config,
        events=events,
    )

    assert "ONLINE渠道" in result
    assert events[-1].status == "error"
    assert events[-1].provider == "openai_compatible"


def test_successful_two_turn_summary_records_both_calls(monkeypatch):
    events = []
    responses = iter(["完整分析", "压缩总结"])

    def fake_generate(config, messages, **kwargs):
        return LLMResponse(
            text=next(responses),
            provider=config.provider,
            model=config.model,
            status="success",
        )

    monkeypatch.setattr(llm, "generate_text", fake_generate)
    config = LLMConfig(
        provider="anthropic",
        api_key="secret-value",
        model="claude-example",
    )

    result = llm.channel_summary(
        {"ONLINE": "on", "OFFLINE": "off"},
        {"DTC": "dtc", "RCMP": "rcmp", "TMALL": "tmall"},
        RAW_CHANNEL,
        llm_config=config,
        events=events,
    )

    assert result == "压缩总结"
    assert [event.status for event in events] == ["success", "success"]

