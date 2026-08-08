import argparse
import json
from pathlib import Path

def run_export(args: argparse.Namespace) -> str:
    from datacontract.data_contract import DataContract

    export_args_dict = {}
    if getattr(args, "export_args", None):
        try:
            export_args_dict = json.loads(args.export_args)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Failed to parse --export-args as JSON: {exc}")

    # Common validation: schema name must exist if provided
    from semapact.utils.schema_utils import contract_to_model
    contract_model = contract_to_model(args.location)
    if getattr(args, "schema_name", None) and args.schema_name != "all":
        valid_schemas = [s.name for s in contract_model.schema_ or [] if s.name]
        if args.schema_name not in valid_schemas:
            raise ValueError(
                f"Schema '{args.schema_name}' not found in contract. "
                f"Available schemas: {', '.join(valid_schemas) if valid_schemas else 'none'}"
            )

    if args.format == "graph":
        from semapact.exporters.graph_exporter import GraphExporter

        exporter = GraphExporter(export_format="graph")
        result = exporter.export(
            data_contract=contract_model,
            schema_name=args.schema_name,
            server=getattr(args, "server", None),
            sql_server_type=getattr(args, "sql_server_type", "auto"),
            export_args=export_args_dict,
        )
    else:
        # Determine if we should route to our custom sql exporter (SparkSqlContractExporter)
        is_spark_sql = False
        resolved_sql_server_type = "auto"
        if args.format == "sql":
            sql_server_type = getattr(args, "sql_server_type", "auto")
            server = getattr(args, "server", None)
            resolved_sql_server_type = sql_server_type
            if resolved_sql_server_type == "auto":
                if contract_model.servers:
                    if server is None:
                        server_types = set([s.type for s in contract_model.servers if s.type])
                    else:
                        server_obj = next((s for s in contract_model.servers if s.server == server), None)
                        server_types = {server_obj.type} if (server_obj and server_obj.type) else set()

                    if "snowflake" in server_types:
                        resolved_sql_server_type = "snowflake"
                    elif "postgres" in server_types:
                        resolved_sql_server_type = "postgres"
                    elif "mysql" in server_types:
                        resolved_sql_server_type = "mysql"
                    elif "databricks" in server_types:
                        resolved_sql_server_type = "databricks"
                    elif "spark" in server_types:
                        resolved_sql_server_type = "spark"
                    else:
                        resolved_sql_server_type = "snowflake"

            if resolved_sql_server_type in ("databricks", "spark"):
                is_spark_sql = True

        if is_spark_sql:
            from semapact.exporters.sql_exporter import export_contract_to_spark_sql
            try:
                result = export_contract_to_spark_sql(
                    contract=contract_model,
                    sql_server_type=resolved_sql_server_type,
                    schema_name=getattr(args, "schema_name", "all"),
                    server=getattr(args, "server", None),
                    export_args=export_args_dict,
                )
            except Exception as exc:
                raise ValueError(f"Failed to export contract to Spark/Databricks SQL: {exc}") from exc
        else:
            contract = DataContract(data_contract_file=args.location)
            try:
                result = contract.export(
                    export_format=args.format,
                    server=getattr(args, "server", None),
                    schema_name=getattr(args, "schema_name", "all"),
                    sql_server_type=getattr(args, "sql_server_type", "auto"),
                    export_args=export_args_dict,
                )
            except ValueError as exc:
                if "format is not supported" in str(exc):
                    raise ValueError(
                        f"The '{args.format}' format requires a datacontract-cli plugin. "
                        f"Please ensure you have installed the necessary package (e.g., pip install \"datacontract-cli[{args.format}]\")."
                    ) from exc
                raise

    if getattr(args, "output", None):
        if result is not None:
            output_data = result[0] if isinstance(result, tuple) else result
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(str(output_data), encoding="utf-8")
            return f"Exported to {args.output}"
        return f"Exported to {args.output}"

    return result if result is not None else ""


def run_export_ge(args: argparse.Namespace) -> str:
    import sys

    try:
        from semapact.quality.ge_exporter import GreatExpectationsExporter
    except ImportError as exc:
        if "great_expectations" in str(exc) or "great-expectations" in str(exc):
            sys.exit(
                "Error: The 'great_expectations' library is required to export GE suites.\n"
                "Please install it using: pip install \"semapact[quality]\" or pip install great_expectations"
            )
        raise

    try:
        output_path = GreatExpectationsExporter().export_to_path(
            args.contract,
            args.output,
            schema_name=args.schema_name,
            suite_name=args.suite_name,
            engine=args.engine,
        )
        return str(output_path)
    except (RuntimeError, ImportError) as exc:
        if "requires pyspark to be installed" in str(exc) or "pyspark" in str(exc):
            sys.exit(str(exc))
        raise
