"""Tests for the Quant Dashboard API endpoints."""

from unittest.mock import MagicMock

import pytest
import yaml

from freqtrade.rpc.api_server.api_quant import (
    _get_data_sources,
    _get_factor_correlation,
    _get_factor_detail,
    _get_factor_zscore,
    _get_factors,
    _get_ic_rolling,
    _get_nav,
    _get_ohlcv,
    _get_trades,
)
from freqtrade.rpc.api_server.api_quant_schemas import (
    CorrelationMatrixResponse,
    DataSourcePair,
    DataSourcesResponse,
    FactorDetailResponse,
    FactorMetrics,
    FactorsResponse,
    FactorSummary,
    TimeSeriesResponse,
    TradesResponse,
)
from freqtrade.rpc.api_server.deps import get_quant_db
from tests.rpc.test_api_quant_helpers import make_mock_db


class TestQuantDB:
    def test_query_rows_returns_list_of_dicts(self):
        """query_rows should return a list of dicts with column names as keys."""
        db = make_mock_db(
            description=[("pair",), ("row_count",)],
            rows=[("BTC/USDT", 26284), ("ETH/USDT", 8763)],
        )
        result = db.query_rows("SELECT pair, COUNT(*) as row_count FROM t", ())
        assert result == [
            {"pair": "BTC/USDT", "row_count": 26284},
            {"pair": "ETH/USDT", "row_count": 8763},
        ]

    def test_query_rows_returns_empty_on_no_results(self):
        db = make_mock_db(description=[("pair",)], rows=[])
        result = db.query_rows("SELECT pair FROM t WHERE 1=0", ())
        assert result == []


class TestQuantSchemas:
    def test_data_source_pair_serialization(self):
        p = DataSourcePair(
            pair="BTC/USDT",
            row_count=26284,
            date_min="2023-04-01T00:00:00Z",
            date_max="2026-04-10T00:00:00Z",
        )
        d = p.model_dump()
        assert d["pair"] == "BTC/USDT"
        assert d["row_count"] == 26284

    def test_factor_summary_serialization(self):
        f = FactorSummary(
            name="momentum_24h",
            bucket="A",
            direction="positive",
            description="24h trailing return",
            zscore_column="z_mom24",
            metrics=FactorMetrics(
                ic_mean=0.008,
                ic_ir=0.45,
                quantile_sharpe=1.2,
                backtest_sharpe=1.1,
                backtest_max_dd=0.12,
            ),
            verdict="PASS",
        )
        d = f.model_dump()
        assert d["name"] == "momentum_24h"
        assert d["metrics"]["ic_mean"] == 0.008
        assert d["verdict"] == "PASS"

    def test_time_series_response(self):
        ts = TimeSeriesResponse(
            columns=["date", "value"],
            data=[["2025-01-01T00:00:00Z", 1.23]],
        )
        assert len(ts.data) == 1

    def test_correlation_matrix_response(self):
        cm = CorrelationMatrixResponse(
            factors=["momentum_24h", "lowvol_24h"],
            matrix=[[1.0, 0.15], [0.15, 1.0]],
        )
        assert cm.matrix[0][1] == 0.15


class TestQuantDeps:
    def test_get_quant_db_returns_none_without_config(self):
        result = get_quant_db(config={})
        assert result is None

    def test_get_quant_db_returns_none_without_dsn(self):
        result = get_quant_db(config={"quant_db": {}})
        assert result is None


class TestDataSourcesEndpoint:
    def test_get_data_sources_with_data(self):
        mock_db = MagicMock()
        mock_db.query_rows.return_value = [
            {
                "pair": "BTC/USDT",
                "row_count": 26284,
                "date_min": "2023-04-01 00:00:00+00",
                "date_max": "2026-04-10 00:00:00+00",
            },
            {
                "pair": "ETH/USDT",
                "row_count": 8763,
                "date_min": "2025-04-11 00:00:00+00",
                "date_max": "2026-04-10 00:00:00+00",
            },
        ]
        result = _get_data_sources(mock_db)
        assert isinstance(result, DataSourcesResponse)
        crypto = next(s for s in result.sources if s.name == "Crypto")
        assert crypto.status == "active"
        assert len(crypto.pairs) == 2
        assert crypto.pairs[0].pair == "BTC/USDT"

    def test_get_data_sources_without_db(self):
        result = _get_data_sources(None)
        crypto = next(s for s in result.sources if s.name == "Crypto")
        assert crypto.pairs == []


class TestFactorsEndpoint:
    def test_get_factors_merges_yml_and_scoreboard(self, tmp_path):
        yml = tmp_path / "factors.yml"
        yml.write_text(
            yaml.dump(
                {
                    "factors": [
                        {
                            "name": "momentum_24h",
                            "bucket": "A",
                            "direction": "positive",
                            "description": "test",
                            "zscore_column": "z_mom24",
                            "feature_model": "feat_momentum_24h",
                            "raw_column": "momentum_24h",
                        },
                    ]
                }
            )
        )
        mock_db = MagicMock()
        mock_db.query_rows.return_value = [
            {
                "factor_name": "momentum_24h",
                "ic_mean": 0.008,
                "ic_ir": 0.45,
                "quantile_sharpe": 1.2,
                "backtest_sharpe": 1.1,
                "backtest_max_dd": 0.12,
                "verdict": "PASS",
            },
        ]
        result = _get_factors(mock_db, factors_yml_path=str(yml))
        assert isinstance(result, FactorsResponse)
        assert len(result.factors) == 1
        assert result.factors[0].metrics.ic_mean == 0.008
        assert result.factors[0].verdict == "PASS"

    def test_get_factors_without_db(self, tmp_path):
        yml = tmp_path / "factors.yml"
        yml.write_text(
            yaml.dump(
                {
                    "factors": [
                        {
                            "name": "rsi_14",
                            "bucket": "A",
                            "direction": "positive",
                            "description": "RSI",
                            "zscore_column": "z_rsi14",
                            "feature_model": "feat_rsi_14",
                            "raw_column": "rsi_14",
                        },
                    ]
                }
            )
        )
        result = _get_factors(None, factors_yml_path=str(yml))
        assert len(result.factors) == 1
        assert result.factors[0].metrics.ic_mean is None


class TestFactorDetailEndpoint:
    def test_get_factor_detail(self, tmp_path):
        yml = tmp_path / "factors.yml"
        yml.write_text(
            yaml.dump(
                {
                    "factors": [
                        {
                            "name": "momentum_24h",
                            "bucket": "A",
                            "direction": "positive",
                            "description": "test",
                            "zscore_column": "z_mom24",
                            "feature_model": "feat_momentum_24h",
                            "raw_column": "momentum_24h",
                        },
                    ]
                }
            )
        )
        mock_db = MagicMock()
        mock_db.query_rows.side_effect = [
            [
                {
                    "window_label": "overall",
                    "ic_mean": 0.008,
                    "ic_std": 0.02,
                    "ic_ir": 0.4,
                    "ic_t_stat": 2.1,
                    "n_months": 12,
                }
            ],
            [
                {
                    "sharpe_annualized": 1.2,
                    "mean_ret_per_hour": 0.00002,
                    "std_ret_per_hour": 0.001,
                    "total_return": 0.12,
                    "n_hours": 8760,
                }
            ],
            [{"factor_b": "lowvol_24h", "corr_pearson": 0.15, "n_obs": 50000}],
        ]
        result = _get_factor_detail("momentum_24h", mock_db, factors_yml_path=str(yml))
        assert isinstance(result, FactorDetailResponse)
        assert result.name == "momentum_24h"
        assert len(result.ic_by_window) == 1
        assert result.quantile_backtest.sharpe_annualized == 1.2
        assert len(result.correlations) == 1

    def test_get_factor_detail_unknown(self, tmp_path):
        yml = tmp_path / "factors.yml"
        yml.write_text(yaml.dump({"factors": []}))
        with pytest.raises(Exception, match="not found"):
            _get_factor_detail("unknown", MagicMock(), factors_yml_path=str(yml))


class TestTimeSeriesEndpoints:
    def test_get_ohlcv(self):
        mock_db = MagicMock()
        mock_db.query_rows.return_value = [
            {
                "date": "2025-01-01 00:00:00+00",
                "open": 42000.0,
                "high": 42500.0,
                "low": 41800.0,
                "close": 42300.0,
                "volume": 100.5,
            },
        ]
        result = _get_ohlcv(mock_db, "BTC/USDT", "20250101", "20250102")
        assert isinstance(result, TimeSeriesResponse)
        assert result.columns == ["date", "open", "high", "low", "close", "volume"]
        assert len(result.data) == 1

    def test_get_ohlcv_no_db(self):
        with pytest.raises(Exception, match="not configured"):
            _get_ohlcv(None, "BTC/USDT", "20250101", "20250102")

    def test_get_factor_zscore(self):
        mock_db = MagicMock()
        mock_db.query_rows.return_value = [
            {"date": "2025-01-01 00:00:00+00", "zscore": 1.23},
        ]
        result = _get_factor_zscore(mock_db, "BTC/USDT", "momentum_24h", "20250101", "20250102")
        assert result.columns == ["date", "zscore"]
        assert len(result.data) == 1


class TestRemainingEndpoints:
    def test_get_ic_rolling(self):
        mock_db = MagicMock()
        mock_db.query_rows.return_value = [
            {
                "month": "2025-01",
                "monthly_ic": 0.05,
                "rolling_3m_ic": 0.04,
                "rolling_3m_ic_std": 0.02,
            },
        ]
        result = _get_ic_rolling(mock_db, "momentum_24h")
        assert result.columns == ["month", "monthly_ic", "rolling_3m_ic", "rolling_3m_ic_std"]
        assert len(result.data) == 1

    def test_get_factor_correlation(self):
        mock_db = MagicMock()
        mock_db.query_rows.return_value = [
            {"factor_a": "lowvol_24h", "factor_b": "momentum_24h", "corr_pearson": 0.15},
            {"factor_a": "momentum_24h", "factor_b": "lowvol_24h", "corr_pearson": 0.15},
        ]
        result = _get_factor_correlation(mock_db)
        assert isinstance(result, CorrelationMatrixResponse)
        assert len(result.factors) == 2

    def test_get_nav(self):
        mock_db = MagicMock()
        mock_db.query_rows.return_value = [
            {"date": "2025-01-01", "nav": 10000.0},
            {"date": "2025-01-02", "nav": 10050.0},
        ]
        result = _get_nav(mock_db, "momentum_24h")
        assert result.columns == ["date", "nav"]
        assert len(result.data) == 2


class TestTradesEndpoint:
    def test_get_trades(self):
        mock_db = MagicMock()
        mock_db.query_rows.return_value = [
            {
                "open_date": "2025-01-15 08:00:00+00",
                "close_date": "2025-01-15 14:00:00+00",
                "open_rate": 42150.0,
                "close_rate": 42380.0,
                "profit_pct": 0.54,
                "exit_reason": "roi",
                "direction": "long",
            },
        ]
        result = _get_trades(mock_db, "BTC/USDT", "momentum_24h")
        assert isinstance(result, TradesResponse)
        assert len(result.trades) == 1
        assert result.trades[0].open_rate == 42150.0

    def test_get_trades_no_db(self):
        with pytest.raises(Exception, match="not configured"):
            _get_trades(None, "BTC/USDT", "momentum_24h")
