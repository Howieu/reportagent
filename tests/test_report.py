from src.data_provider import MockDataProvider, ReportRequest
from src.llm import LLMConfig
from src.report import build_report


def test_report_accepts_report_data_and_discloses_demo_metadata():
    request = ReportRequest(
        store_id="401",
        hfb_ids=("01",),
        week_info="202527",
        focus="sales",
        as_of_date="2025-07-06",
    )
    report_data = MockDataProvider().load(request)

    html = build_report(
        report_data,
        hfb="01",
        week_info="202527",
        focus="sales",
        use_ml=False,
        store="401",
        llm_config=LLMConfig(provider="template"),
    )

    assert "离线模板" in html
    assert "2025-07-06" in html
    assert "确定性仿真数据" in html
    assert "Store 401" in html
    assert "业绩总结" in html
    assert "渠道分析" in html
    assert "DTC-RCMP 销售分析" in html


def test_report_metadata_never_contains_api_key():
    request = ReportRequest(
        store_id="401",
        hfb_ids=("01",),
        week_info="202527",
        focus="sales",
    )
    report_data = MockDataProvider().load(request)
    config = LLMConfig(
        provider="openai_compatible",
        api_key="secret-value",
        model="example-model",
    )

    html = build_report(
        report_data,
        hfb="01",
        week_info="202527",
        focus="sales",
        use_ml=False,
        store="401",
        llm_config=config,
        use_llm=False,
    )

    assert "secret-value" not in html
