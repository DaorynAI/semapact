from semapact.quality.validation import format_validation_result


def test_format_validation_result_collects_failures():
    validation_payload = {
        "success": False,
        "statistics": {"evaluated_expectations": 2, "successful_expectations": 1},
        "results": [
            {
                "success": True,
                "expectation_config": {
                    "expectation_type": "expect_column_values_to_not_be_null",
                    "kwargs": {"column": "id"},
                },
            },
            {
                "success": False,
                "expectation_config": {
                    "expectation_type": "expect_column_values_to_be_between",
                    "kwargs": {"column": "amount", "min_value": 0},
                },
                "result": {"unexpected_count": 2},
            },
        ],
    }

    formatted = format_validation_result(validation_payload)

    assert formatted["success"] is False
    assert formatted["statistics"]["evaluated_expectations"] == 2
    assert len(formatted["failed_expectations"]) == 1
    assert (
        formatted["failed_expectations"][0]["expectation_type"]
        == "expect_column_values_to_be_between"
    )


def test_format_validation_result_supports_to_json_dict_and_non_dict_config():
    class ValidationResult:
        @staticmethod
        def to_json_dict():
            return {
                "success": False,
                "statistics": {"evaluated_expectations": 1},
                "results": [{"success": False, "expectation_config": "invalid"}],
            }

    formatted = format_validation_result(ValidationResult())
    assert formatted["success"] is False
    assert formatted["failed_expectations"][0]["kwargs"] == {}


def test_format_validation_result_handles_unknown_payload_type():
    formatted = format_validation_result(object())
    assert formatted == {"success": False, "statistics": {}, "failed_expectations": []}


def test_format_validation_result_skips_non_dict_results():
    payload = {"success": False, "statistics": {}, "results": ["bad-entry"]}
    formatted = format_validation_result(payload)
    assert formatted["failed_expectations"] == []
