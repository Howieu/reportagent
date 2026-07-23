"""报告数据契约与公开 Demo 的确定性数据提供层。"""

from dataclasses import dataclass, field

import pandas as pd

from . import mock_data


class DataValidationError(ValueError):
    """输入数据不满足报告生成契约。"""


@dataclass(frozen=True)
class ReportRequest:
    store_id: str
    hfb_ids: tuple[str, ...]
    week_info: str
    focus: str
    as_of_date: str = "2025-07-06"

    def __post_init__(self):
        if self.focus not in {"sales", "qty"}:
            raise ValueError("focus 仅支持 sales 或 qty")
        if not self.hfb_ids:
            raise ValueError("至少需要一个 HFB")


@dataclass(frozen=True)
class ReportData:
    channel: pd.DataFrame
    funnel: pd.DataFrame
    drilldown: pd.DataFrame
    pa_prediction: pd.DataFrame
    article_prediction: pd.DataFrame
    metadata: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, pd.DataFrame]:
        return {
            "channel": self.channel,
            "funnel": self.funnel,
            "drilldown": self.drilldown,
            "pa_pred": self.pa_prediction,
            "article_pred": self.article_prediction,
        }


_REQUIRED_COLUMNS = {
    "channel": {
        "hfb_no",
        "sales_channel",
        "date_type",
        "sales_ind_goal",
        "sales_ind_ly",
    },
    "funnel": {"hfb_no", "date_type", "sales_ind_ly", "qty_ind_ly"},
    "drilldown": {
        "hfb_no",
        "pa_no",
        "item_family",
        "item_id",
        "date_type",
        "sales_ind_ly",
        "qty_ind_ly",
    },
    "pa_pred": {"pa_no", "payment_date", "sale_net_amt"},
    "article_pred": {"item_id", "payment_date", "sale_net_amt"},
}


def validate_report_data(data: dict[str, pd.DataFrame], request: ReportRequest) -> None:
    for name, required in _REQUIRED_COLUMNS.items():
        if name not in data:
            raise DataValidationError(f"缺少数据集: {name}")
        missing = required.difference(data[name].columns)
        if missing:
            raise DataValidationError(
                f"{name} 缺少字段: {', '.join(sorted(missing))}"
            )
        if data[name].empty:
            raise DataValidationError(f"{name} 数据为空")

    available_hfbs = set(data["channel"]["hfb_no"].astype(str))
    for hfb in request.hfb_ids:
        if hfb not in available_hfbs:
            raise DataValidationError(f"HFB {hfb} 无可用数据")

    for hfb in request.hfb_ids:
        for name in ("channel", "funnel", "drilldown"):
            rows = data[name][data[name]["hfb_no"].astype(str) == hfb]
            date_types = set(rows["date_type"].astype(str))
            if not {"Weekly", "Rolling 4wks"}.issubset(date_types):
                raise DataValidationError(
                    f"HFB {hfb} 的 {name} 缺少 Weekly 或 Rolling 4wks"
                )


class MockDataProvider:
    """公开 Demo 数据源；可替换为未来的 OdpsDataProvider。"""

    def load(self, request: ReportRequest) -> ReportData:
        data = mock_data.load_all()
        validate_report_data(data, request)
        return ReportData(
            channel=data["channel"],
            funnel=data["funnel"],
            drilldown=data["drilldown"],
            pa_prediction=data["pa_pred"],
            article_prediction=data["article_pred"],
            metadata={
                "source": "deterministic_mock",
                "as_of_date": request.as_of_date,
                "store_scope": "simulated",
                "week_scope": "display_parameter",
            },
        )


class OdpsDataProvider:
    """真实数仓适配器占位；公开 Demo 禁止启用。"""

    def load(self, request: ReportRequest) -> ReportData:
        raise NotImplementedError("公开 Demo 未启用 ODPS 数据源")
