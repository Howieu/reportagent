from types import SimpleNamespace

from src.llm import (
    AnthropicProvider,
    LLMConfig,
    OpenAICompatibleProvider,
    generate_text,
)


def test_template_mode_never_requires_a_key():
    response = generate_text(
        LLMConfig(provider="template"),
        [{"role": "user", "content": "hello"}],
    )

    assert response.status == "template"
    assert response.text == ""
    assert response.provider == "template"


def test_openai_compatible_provider_normalizes_text_and_usage():
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="分析完成"))],
                usage=SimpleNamespace(prompt_tokens=12, completion_tokens=5),
                _request_id="req_openai",
            )

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )
    config = LLMConfig(
        provider="openai_compatible",
        api_key="secret-value",
        base_url="https://example.test/v1",
        model="example-model",
        temperature=0.2,
        max_tokens=321,
    )

    response = OpenAICompatibleProvider(config, client=fake_client).generate(
        [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "question"},
        ]
    )

    assert response.status == "success"
    assert response.text == "分析完成"
    assert response.usage == {"input_tokens": 12, "output_tokens": 5}
    assert captured["model"] == "example-model"
    assert captured["max_tokens"] == 321
    assert captured["messages"][0]["role"] == "system"


def test_anthropic_provider_separates_system_message():
    captured = {}

    class FakeMessages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text="Claude 分析")],
                usage=SimpleNamespace(input_tokens=9, output_tokens=4),
                _request_id="req_anthropic",
            )

    fake_client = SimpleNamespace(messages=FakeMessages())
    config = LLMConfig(
        provider="anthropic",
        api_key="secret-value",
        model="claude-example",
    )

    response = AnthropicProvider(config, client=fake_client).generate(
        [
            {"role": "system", "content": "system rules"},
            {"role": "user", "content": "question"},
        ]
    )

    assert response.status == "success"
    assert response.text == "Claude 分析"
    assert captured["system"] == "system rules"
    assert captured["messages"] == [{"role": "user", "content": "question"}]


def test_failed_provider_call_never_echoes_api_key():
    class LeakyClient:
        class Chat:
            class Completions:
                def create(self, **kwargs):
                    raise RuntimeError("request failed for secret-value")

            completions = Completions()

        chat = Chat()

    config = LLMConfig(
        provider="openai_compatible",
        api_key="secret-value",
        model="example-model",
    )

    response = generate_text(
        config,
        [{"role": "user", "content": "question"}],
        client=LeakyClient(),
    )

    assert response.status == "error"
    assert "secret-value" not in response.error_message
    assert "secret-value" not in repr(config)

