import semapact.importers.delta_importer as delta_mod


def test_delta_helpers_cover_edge_paths():
    assert delta_mod._derive_dataset_name("path/without/scheme/table1") == "table1"  # noqa: SLF001
    assert (
        delta_mod._derive_dataset_name("abfss://c@a.dfs.core.windows.net/path/table2")
        == "table2"
    )  # noqa: SLF001
    assert delta_mod._to_contract_id("A B C") == "a-b-c"  # noqa: SLF001

    assert delta_mod._extract_table_description(None) is None  # noqa: SLF001
    assert (
        delta_mod._extract_table_description({"configuration": {"comment": "desc"}})
        == "desc"
    )  # noqa: SLF001

    class Meta:
        description = None
        configuration = {"delta.table.description": "d1"}

    assert delta_mod._extract_table_description(Meta()) == "d1"  # noqa: SLF001

    assert delta_mod._extract_partition_positions(None) == {}  # noqa: SLF001
    assert delta_mod._extract_partition_positions(
        {"partitionColumns": ["id", "dt"]}
    ) == {"id": 1, "dt": 2}  # noqa: E501, SLF001

    class Meta2:
        partition_columns = ["p1"]

    assert delta_mod._extract_partition_positions(Meta2()) == {"p1": 1}  # noqa: SLF001

    assert (
        delta_mod._delta_type_to_string(
            {"type": "decimal", "precision": 10, "scale": 2}
        )
        == "decimal(10,2)"
    )  # noqa: E501, SLF001
    assert delta_mod._delta_type_to_string({"type": "struct"}) == '{"type":"struct"}'  # noqa: SLF001

    assert delta_mod._parse_sql_data_type("NOT A TYPE") is None  # noqa: SLF001
    assert delta_mod._map_delta_type_to_odcs("array<int>") == "array"  # noqa: SLF001
    assert delta_mod._map_delta_type_to_odcs("map<string,string>") == "object"  # noqa: SLF001
    assert delta_mod._map_delta_type_to_odcs("weird") == "string"  # noqa: SLF001


def test_schema_property_from_any_type_none_and_plain_string():
    assert delta_mod._schema_property_from_any_type(None, required=False) is None  # noqa: SLF001
    prop = delta_mod._schema_property_from_any_type("string", required=True)  # noqa: SLF001
    assert prop.logicalType == "string"
    assert prop.required is True


def test_schema_property_from_delta_field_handles_missing_name_and_map_options():
    assert (
        delta_mod._schema_property_from_delta_field({}, partition_positions={}) is None
    )  # noqa: SLF001
    prop = delta_mod._schema_property_from_delta_field(  # noqa: SLF001
        {
            "name": "attrs",
            "type": {
                "type": "map",
                "keyType": "string",
                "valueType": "long",
                "valueContainsNull": True,
            },
            "nullable": True,
            "metadata": {"description": "attrs"},
        },
        partition_positions={},
    )
    assert prop.description == "attrs"
    assert prop.logicalTypeOptions["keyType"].lower().startswith("string")


def test_parse_sql_data_type_exception_branch():
    assert delta_mod._parse_sql_data_type("###") is None  # noqa: SLF001
