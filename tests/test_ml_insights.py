from src.data_provider import MockDataProvider, ReportRequest
from src.ml_insights import forecast_next_week, top3_features


def _load_predictions():
    request = ReportRequest(store_id="401", hfb_ids=("01",), week_info="202527", focus="sales")
    data = MockDataProvider().load(request)
    pa_ids = data.pa_prediction["pa_no"].unique().tolist()
    return data.pa_prediction, pa_ids


def test_top3_features_covers_every_requested_entity():
    pa_pred, pa_ids = _load_predictions()
    results = top3_features(pa_pred, "pa_no", pa_ids)

    assert set(results.keys()) == set(pa_ids)
    for text in results.values():
        assert isinstance(text, str) and text


def test_top3_features_omits_unknown_entity():
    pa_pred, _ = _load_predictions()
    results = top3_features(pa_pred, "pa_no", ["not-a-real-pa"])
    assert results == {}


def test_forecast_next_week_returns_numeric_totals():
    pa_pred, pa_ids = _load_predictions()
    forecast = forecast_next_week(pa_pred, "pa_no", pa_ids)

    assert set(forecast.keys()) == set(pa_ids)
    for value in forecast.values():
        assert isinstance(value, float)


def test_forecast_next_week_skips_entities_with_too_little_history():
    pa_pred, _ = _load_predictions()
    short_history = pa_pred[pa_pred["pa_no"] == pa_pred["pa_no"].iloc[0]].head(5)
    forecast = forecast_next_week(short_history, "pa_no", [pa_pred["pa_no"].iloc[0]])
    assert forecast == {}
