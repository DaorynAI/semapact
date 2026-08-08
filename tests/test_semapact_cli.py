from unittest.mock import patch
from semapact.interfaces.cli import main


def test_export_ge_handles_missing_pyspark_gracefully(monkeypatch):
    class FakeExporter:
        def export_to_path(self, *args, **kwargs):
            raise RuntimeError(
                "datacontract-cli Great Expectations export with engine='spark' requires pyspark to be installed"
            )

    monkeypatch.setattr(
        "semapact.quality.ge_exporter.GreatExpectationsExporter",
        lambda: FakeExporter(),
    )

    test_args = [
        "semapact",
        "export-ge",
        "--contract",
        "dummy.yaml",
        "--output",
        "out.json",
    ]
    with patch("sys.argv", test_args):
        # The new CLI top-level error handler catches RuntimeErrors and returns 1
        exit_code = main()
        assert exit_code == 1


def test_cli_export_sql_databricks_location(tmp_path):
    import yaml
    from semapact.interfaces.cli import main
    from unittest.mock import patch

    contract_data = {
        "apiVersion": "v3.1.0",
        "kind": "DataContract",
        "id": "my-contract",
        "servers": [
            {"server": "prod", "type": "databricks"}
        ],
        "schema": [
            {
                "name": "my_table",
                "customProperties": [
                    {"property": "semapact.table.location", "value": "s3://my-bucket/my_table/"}
                ],
                "properties": [
                    {
                        "name": "id",
                        "type": "string"
                    }
                ]
            }
        ]
    }

    contract_file = tmp_path / "contract.yaml"
    contract_file.write_text(yaml.dump(contract_data), encoding="utf-8")

    output_file = tmp_path / "output.sql"

    test_args = [
        "semapact",
        "export",
        str(contract_file),
        "--format",
        "sql",
        "--sql-server-type",
        "databricks",
        "--output",
        str(output_file),
    ]

    with patch("sys.argv", test_args):
        exit_code = main()
        assert exit_code == 0

    ddl = output_file.read_text(encoding="utf-8")
    assert "USING delta" in ddl
    assert "LOCATION 's3://my-bucket/my_table/'" in ddl


def test_cli_export_sql_auto_databricks_location(tmp_path):
    import yaml
    from semapact.interfaces.cli import main
    from unittest.mock import patch

    contract_data = {
        "apiVersion": "v3.1.0",
        "kind": "DataContract",
        "id": "my-contract",
        "servers": [
            {"server": "my_db", "type": "databricks"}
        ],
        "schema": [
            {
                "name": "my_table",
                "customProperties": [
                    {"property": "semapact.table.location", "value": "s3://my-bucket/my_table/"}
                ],
                "properties": [
                    {
                        "name": "id",
                        "type": "string"
                    }
                ]
            }
        ]
    }

    contract_file = tmp_path / "contract.yaml"
    contract_file.write_text(yaml.dump(contract_data), encoding="utf-8")

    output_file = tmp_path / "output.sql"

    # 1. auto-detect using default/only server in the contract
    test_args = [
        "semapact",
        "export",
        str(contract_file),
        "--format",
        "sql",
        "--output",
        str(output_file),
    ]

    with patch("sys.argv", test_args):
        exit_code = main()
        assert exit_code == 0

    ddl = output_file.read_text(encoding="utf-8")
    assert "USING delta" in ddl
    assert "LOCATION 's3://my-bucket/my_table/'" in ddl

