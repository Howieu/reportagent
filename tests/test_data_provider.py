import json
import subprocess
import sys

import pytest

from src.data_provider import (
    DataValidationError,
    MockDataProvider,
    ReportData,
    ReportRequest,
)


def test_mock_seed_is_stable_across_python_processes():
    script = (
        "from src.mock_data import _rng; "
        "import json; "
        "print(json.dumps(_rng('channel','01').normal(size=4).tolist()))"
    )
    first = subprocess.check_output([sys.executable, "-c", script], text=True)
    second = subprocess.check_output([sys.executable, "-c", script], text=True)

    assert json.loads(first) == json.loads(second)


def test_mock_provider_returns_valid_report_data():
    request = ReportRequest(
        store_id="401",
        hfb_ids=("01",),
        week_info="202527",
        focus="sales",
        as_of_date="2025-07-06",
    )

    report_data = MockDataProvider().load(request)

    assert isinstance(report_data, ReportData)
    assert report_data.metadata["source"] == "deterministic_mock"
    assert report_data.metadata["as_of_date"] == "2025-07-06"
    assert set(report_data.as_dict()) == {
        "channel",
        "funnel",
        "drilldown",
        "pa_pred",
        "article_pred",
    }


def test_request_rejects_unsupported_focus():
    with pytest.raises(ValueError, match="focus"):
        ReportRequest(
            store_id="401",
            hfb_ids=("01",),
            week_info="202527",
            focus="profit",
            as_of_date="2025-07-06",
        )


def test_provider_rejects_missing_hfb():
    request = ReportRequest(
        store_id="401",
        hfb_ids=("99",),
        week_info="202527",
        focus="sales",
        as_of_date="2025-07-06",
    )

    with pytest.raises(DataValidationError, match="HFB 99"):
        MockDataProvider().load(request)
