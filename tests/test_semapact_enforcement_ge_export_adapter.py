import pytest
import sys
import semapact.quality.ge_exporter as ge_adapter
from semapact.utils.schema_utils import contract_to_model


@pytest.mark.skipif(
    sys.version_info >= (3, 13),
    reason="great_expectations does not support Python 3.13+",
)
def test_generate_expectation_suite_uses_datacontract_exporter(monkeypatch):
    """
    Test that the Great Expectations exporter successfully constructs the correct GE suite dictionary
    without invoking the underlying Pandas/Spark/SQLAlchemy validation engines, by mocking pyspark.
    """
    from unittest.mock import MagicMock, patch

    mock_pyspark = MagicMock()

    class MockDataFrame:
        pass

    mock_pyspark.DataFrame = MockDataFrame
    mock_pyspark.pyspark = mock_pyspark

    with patch.dict(
        "sys.modules",
        {
            "pyspark": mock_pyspark,
            "pyspark.sql": MagicMock(),
            "pyspark.sql.types": MagicMock(),
        },
    ):
        # Load from fixture instead of inline yaml
        fixture_path = (
            "tests/fixtures/contracts/quality/constraint_friendly_quality.yaml"
        )
        model = contract_to_model(fixture_path)

        suite = ge_adapter.generate_expectation_suite(
            contract=model, schema_name="quality_rules"
        )

        # Assert that the exporter constructs the suite
        suite_name = getattr(
            suite, "expectation_suite_name", getattr(suite, "name", None)
        )
        assert suite_name == "quality_rules.1.0.0"

        # Check that expectations were generated (e.g. for the columns)
        assert len(suite.expectations) > 0

        # Verify expect_table_columns_to_match_ordered_list or similar was generated
        types = [
            getattr(exp, "expectation_type", getattr(exp, "type", None))
            for exp in suite.expectations
        ]
        assert "expect_table_columns_to_match_ordered_list" in types
