from streamlit.testing.v1 import AppTest


def _run_app():
    return AppTest.from_file("app.py", default_timeout=60).run()


def test_app_loads_in_template_mode_with_ml_disabled():
    app = _run_app()

    assert not app.exception
    assert next(widget for widget in app.selectbox if widget.label == "文本生成方式").value == "template"
    assert next(widget for widget in app.toggle if widget.label == "启用 ML 归因 / 预测").value is False
    assert any("无需 API Key" in item.value for item in app.info)


def test_openai_compatible_mode_shows_session_key_notice_and_fields():
    app = _run_app()
    provider = next(widget for widget in app.selectbox if widget.label == "文本生成方式")
    provider.set_value("openai_compatible").run()

    labels = {widget.label for widget in app.text_input}
    assert {"API Key", "Base URL", "模型"}.issubset(labels)
    assert any("Streamlit 服务端" in item.value for item in app.warning)


def test_generate_report_exposes_html_download_without_ml_or_key():
    app = _run_app()
    generate = next(button for button in app.button if button.label == "🚀 生成报告")
    generate.click().run()

    assert not app.exception
    assert any(item.label == "HFB 01 报告生成完成" for item in app.status)
    assert any(item.label == "⬇️ 下载 HFB 01 HTML 报告" for item in app.download_button)
