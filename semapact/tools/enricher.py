import concurrent.futures
from open_data_contract_standard.model import (
    OpenDataContractStandard,
    CustomProperty,
    Relationship,
    DataQuality,
)
from semapact.tools.llm_client import BaseLLMProvider, OpenAILLMProvider
from semapact.constants import (
    LABEL_SYSTEM_PROMPT_TEMPLATE,
    LABEL_USER_PROMPT_TEMPLATE,
    JOIN_SYSTEM_PROMPT_TEMPLATE,
    JOIN_USER_PROMPT_TEMPLATE,
    TABLE_DESC_SYSTEM_PROMPT_TEMPLATE,
    TABLE_DESC_USER_PROMPT_TEMPLATE,
    COLUMN_DESC_SYSTEM_PROMPT_TEMPLATE,
    COLUMN_DESC_USER_PROMPT_TEMPLATE,
    QUALITY_SUGGESTION_SYSTEM_PROMPT_TEMPLATE,
    QUALITY_SUGGESTION_USER_PROMPT_TEMPLATE,
)


class ContractEnricher:
    def __init__(self, llm_provider: BaseLLMProvider | None = None):
        self.llm_provider = llm_provider or OpenAILLMProvider()

    def process(self, contract_path: str, max_workers: int = 1, mode: str = "label", system_prompt: str | None = None, user_prompt: str | None = None) -> None:
        """
        Process the contract.
        mode can be 'label' (for tagging existing relationships), 'infer_joins' (for discovering new ones),
        'describe_tables', 'describe_columns', or 'suggest_quality'.
        """
        odcs = OpenDataContractStandard.from_file(contract_path)

        domain_context = "Unknown"
        if odcs.domain:
            domain_context = odcs.domain
        elif odcs.name:
            domain_context = odcs.name
        elif odcs.description:
            domain_context = str(odcs.description)

        if mode == "label":
            self._process_labels(odcs, contract_path, domain_context, max_workers, system_prompt, user_prompt)
        elif mode == "infer_joins":
            self._process_infer_joins(odcs, contract_path, domain_context, max_workers, system_prompt, user_prompt)
        elif mode == "describe_tables":
            self._process_describe_tables(odcs, contract_path, domain_context, max_workers, system_prompt, user_prompt)
        elif mode == "describe_columns":
            self._process_describe_columns(odcs, contract_path, domain_context, max_workers, system_prompt, user_prompt)
        elif mode == "suggest_quality":
            self._process_suggest_quality(odcs, contract_path, domain_context, max_workers, system_prompt, user_prompt)
        else:
            raise ValueError(f"Unknown mode: {mode}")

    def _process_labels(self, odcs, contract_path, domain_context, max_workers, system_prompt_override=None, user_prompt_override=None):
        if system_prompt_override:
            system_prompt = system_prompt_override.replace("{domain_context}", domain_context)
        else:
            system_prompt = LABEL_SYSTEM_PROMPT_TEMPLATE.replace(
                "{domain_context}", domain_context
            )

        table_descriptions = {}
        if odcs.schema_:
            for schema in odcs.schema_:
                table_name = schema.name or schema.id or "Unknown"
                desc = schema.description or "No description provided."
                table_descriptions[table_name] = desc

        tasks = []

        if odcs.schema_:
            for schema in odcs.schema_:
                source_table_name = schema.name or schema.id or "Unknown"
                source_table_description = (
                    schema.description or "No description provided."
                )

                if schema.relationships:
                    for rel in schema.relationships:
                        tasks.append(
                            self._create_label_task(
                                rel=rel,
                                system_prompt=system_prompt,
                                source_table_name=source_table_name,
                                source_table_description=source_table_description,
                                source_column_name=", ".join(rel.from_)
                                if rel.from_
                                else "Unknown",
                                target_table_name=rel.to[0].split(".")[0]
                                if rel.to and len(rel.to) > 0
                                else "Unknown",
                                table_descriptions=table_descriptions,
                                user_prompt_override=user_prompt_override
                            )
                        )

                if schema.properties:
                    for prop in schema.properties:
                        if prop.relationships:
                            for rel in prop.relationships:
                                tasks.append(
                                    self._create_label_task(
                                        rel=rel,
                                        system_prompt=system_prompt,
                                        source_table_name=source_table_name,
                                        source_table_description=source_table_description,
                                        source_column_name=prop.name or "Unknown",
                                        target_table_name=rel.to.split(".")[0]
                                        if rel.to and isinstance(rel.to, str)
                                        else "Unknown",
                                        table_descriptions=table_descriptions,
                                        user_prompt_override=user_prompt_override
                                    )
                                )

        tasks = [t for t in tasks if t is not None]

        if tasks:
            if max_workers > 1:
                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=max_workers
                ) as executor:
                    futures = [
                        executor.submit(self._execute_label_inference, task)
                        for task in tasks
                    ]
                    concurrent.futures.wait(futures)
            else:
                for idx, task in enumerate(tasks, 1):
                    print(f"    -> Processing LLM task {idx}/{len(tasks)}...", flush=True)
                    self._execute_label_inference(task)

        with open(contract_path, "w") as f:
            f.write(odcs.to_yaml())

    def _create_label_task(
        self,
        rel,
        system_prompt,
        source_table_name,
        source_table_description,
        source_column_name,
        target_table_name,
        table_descriptions,
        user_prompt_override=None
    ):
        if rel.customProperties:
            for cp in rel.customProperties:
                if cp.property == "graph_semantic.edge_label":
                    return None

        target_table_description = table_descriptions.get(
            target_table_name, "No description provided."
        )

        user_prompt_template = user_prompt_override or LABEL_USER_PROMPT_TEMPLATE
        user_prompt = user_prompt_template.format(
            source_table_name=source_table_name,
            source_table_description=source_table_description,
            source_column_name=source_column_name,
            target_table_name=target_table_name,
            target_table_description=target_table_description,
            junction_table_name="None",
        )

        return {"rel": rel, "system_prompt": system_prompt, "user_prompt": user_prompt}

    def _execute_label_inference(self, task):
        response = self.llm_provider.generate_json(
            task["system_prompt"], task["user_prompt"]
        )
        edge_label = response.get("edge_label")
        if edge_label:
            rel = task["rel"]
            new_cp = CustomProperty(
                property="graph_semantic.edge_label", value=edge_label
            )
            if rel.customProperties is None:
                rel.customProperties = []
            rel.customProperties.append(new_cp)

    def _process_infer_joins(self, odcs, contract_path, domain_context, max_workers, system_prompt_override=None, user_prompt_override=None):
        if system_prompt_override:
            system_prompt = system_prompt_override.replace("{domain_context}", domain_context)
        else:
            system_prompt = JOIN_SYSTEM_PROMPT_TEMPLATE.replace(
                "{domain_context}", domain_context
            )

        tables = []
        if odcs.schema_:
            for schema in odcs.schema_:
                table_name = schema.name or schema.id or "Unknown"
                desc = schema.description or "No description provided."

                cols = []
                if schema.properties:
                    for prop in schema.properties:
                        has_rels = False
                        if prop.relationships:
                            has_rels = len(prop.relationships) > 0
                        if schema.relationships:
                            for r in schema.relationships:
                                if r.from_ and prop.name in r.from_:
                                    has_rels = True
                                    break

                        if not has_rels:
                            col_info = prop.name
                            if prop.description:
                                col_info += f" ({prop.description})"
                            cols.append({"name": prop.name, "info": col_info})

                tables.append(
                    {
                        "name": table_name,
                        "description": desc,
                        "columns": cols,
                        "schema_ref": schema,
                    }
                )

        tasks = []
        for i, source_table in enumerate(tables):
            for j, target_table in enumerate(tables):
                if i == j:
                    continue

                if not source_table["columns"] or not target_table["columns"]:
                    continue

                source_cols_str = ", ".join(
                    [c["info"] for c in source_table["columns"]]
                )
                target_cols_str = ", ".join(
                    [c["info"] for c in target_table["columns"]]
                )

                user_prompt_template = user_prompt_override or JOIN_USER_PROMPT_TEMPLATE
                user_prompt = user_prompt_template.format(
                    source_table_name=source_table["name"],
                    source_table_description=source_table["description"],
                    source_columns=source_cols_str,
                    target_table_name=target_table["name"],
                    target_table_description=target_table["description"],
                    target_columns=target_cols_str,
                )

                tasks.append(
                    {
                        "source_table_name": source_table["name"],
                        "target_table_name": target_table["name"],
                        "schema_ref": source_table["schema_ref"],
                        "system_prompt": system_prompt,
                        "user_prompt": user_prompt,
                    }
                )

        results = []
        if tasks:
            if max_workers > 1:
                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=max_workers
                ) as executor:
                    futures = {
                        executor.submit(self._execute_inference, task): task
                        for task in tasks
                    }
                    for future in concurrent.futures.as_completed(futures):
                        results.append(future.result())
            else:
                for idx, task in enumerate(tasks, 1):
                    print(f"    -> Processing LLM join inference {idx}/{len(tasks)}...", flush=True)
                    results.append(self._execute_inference(task))

        for task, response in results:
            if not response:
                continue

            potential_joins = response.get("potential_joins", [])
            for join in potential_joins:
                source_col_name = join.get("source_column")
                target_col_name = join.get("target_column")
                edge_label = join.get("edge_label")
                confidence = join.get("confidence")

                if not all([source_col_name, target_col_name, edge_label, confidence]):
                    continue

                schema = task["schema_ref"]
                target_table_name = task["target_table_name"]

                for prop in schema.properties:
                    if prop.name == source_col_name:
                        if not prop.relationships:
                            prop.relationships = []

                        exists = False
                        for r in prop.relationships:
                            if (
                                isinstance(r.to, str)
                                and r.to == f"{target_table_name}.{target_col_name}"
                            ):
                                exists = True
                                break

                        if not exists:
                            rel = Relationship(
                                **{"to": f"{target_table_name}.{target_col_name}"},
                                customProperties=[
                                    CustomProperty(
                                        property="graph_semantic.edge_label",
                                        value=edge_label,
                                    ),
                                    CustomProperty(
                                        property="graph_semantic.provenance",
                                        value="LLM_INFERRED",
                                    ),
                                    CustomProperty(
                                        property="graph_semantic.confidence",
                                        value=confidence,
                                    ),
                                ],
                            )
                            prop.relationships.append(rel)
                        break

        with open(contract_path, "w") as f:
            f.write(odcs.to_yaml())

    def _process_describe_tables(self, odcs, contract_path, domain_context, max_workers, system_prompt_override=None, user_prompt_override=None):
        if system_prompt_override:
            system_prompt = system_prompt_override.replace("{domain_context}", domain_context)
        else:
            system_prompt = TABLE_DESC_SYSTEM_PROMPT_TEMPLATE.replace(
                "{domain_context}", domain_context
            )
        tasks = []
        if odcs.schema_:
            for schema in odcs.schema_:
                if not schema.description:
                    table_name = schema.name or schema.id or "Unknown"
                    cols_info = []
                    if schema.properties:
                        for p in schema.properties:
                            cols_info.append(f"{p.name} ({p.logicalType})")
                    columns_info_str = ", ".join(cols_info)

                    contract_auth_defs = getattr(odcs, "authoritativeDefinitions", []) or []
                    schema_auth_defs = schema.authoritativeDefinitions or []
                    all_auth_defs = contract_auth_defs + schema_auth_defs
                    auth_defs_str = (
                        ", ".join([str(a) for a in all_auth_defs])
                        if all_auth_defs
                        else "None"
                    )

                    user_prompt_template = user_prompt_override or TABLE_DESC_USER_PROMPT_TEMPLATE
                    user_prompt = user_prompt_template.format(
                        table_name=table_name,
                        columns_info=columns_info_str,
                        authoritative_definitions=auth_defs_str,
                    )
                    tasks.append(
                        {
                            "schema_ref": schema,
                            "system_prompt": system_prompt,
                            "user_prompt": user_prompt,
                        }
                    )

        results = self._run_tasks_concurrently(tasks, max_workers)

        for task, response in results:
            if response and "description" in response:
                desc = response["description"].strip()
                if not desc.startswith("[LLM_INFERRED]"):
                    desc = f"[LLM_INFERRED] {desc}"
                task["schema_ref"].description = desc
                if not task["schema_ref"].tags:
                    task["schema_ref"].tags = []
                if "LLM_INFERRED" not in task["schema_ref"].tags:
                    task["schema_ref"].tags.append("LLM_INFERRED")

        with open(contract_path, "w") as f:
            f.write(odcs.to_yaml())

    def _process_describe_columns(self, odcs, contract_path, domain_context, max_workers, system_prompt_override=None, user_prompt_override=None):
        if system_prompt_override:
            system_prompt = system_prompt_override.replace("{domain_context}", domain_context)
        else:
            system_prompt = COLUMN_DESC_SYSTEM_PROMPT_TEMPLATE.replace(
                "{domain_context}", domain_context
            )
        tasks = []
        if odcs.schema_:
            for schema in odcs.schema_:
                table_name = schema.name or schema.id or "Unknown"
                table_desc = schema.description or "No description."

                cols_info = []
                if schema.properties:
                    for p in schema.properties:
                        cols_info.append(f"{p.name}")
                other_columns_info_str = ", ".join(cols_info)

                if schema.properties:
                    for prop in schema.properties:
                        if not prop.description:
                            contract_auth_defs = getattr(odcs, "authoritativeDefinitions", []) or []
                            schema_auth_defs = schema.authoritativeDefinitions or []
                            prop_auth_defs = (
                                getattr(prop, "authoritativeDefinitions", []) or []
                            )
                            all_auth_defs = (
                                contract_auth_defs + schema_auth_defs + prop_auth_defs
                            )
                            auth_defs_str = (
                                ", ".join([str(a) for a in all_auth_defs])
                                if all_auth_defs
                                else "None"
                            )

                            user_prompt_template = user_prompt_override or COLUMN_DESC_USER_PROMPT_TEMPLATE
                            user_prompt = user_prompt_template.format(
                                table_name=table_name,
                                table_description=table_desc,
                                column_name=prop.name,
                                column_type=prop.logicalType,
                                other_columns_info=other_columns_info_str,
                                authoritative_definitions=auth_defs_str,
                            )
                            tasks.append(
                                {
                                    "prop_ref": prop,
                                    "system_prompt": system_prompt,
                                    "user_prompt": user_prompt,
                                }
                            )

        results = self._run_tasks_concurrently(tasks, max_workers)

        for task, response in results:
            if response and "description" in response:
                desc = response["description"].strip()
                if not desc.startswith("[LLM_INFERRED]"):
                    desc = f"[LLM_INFERRED] {desc}"
                task["prop_ref"].description = desc
                if not task["prop_ref"].tags:
                    task["prop_ref"].tags = []
                if "LLM_INFERRED" not in task["prop_ref"].tags:
                    task["prop_ref"].tags.append("LLM_INFERRED")

        with open(contract_path, "w") as f:
            f.write(odcs.to_yaml())

    def _process_suggest_quality(self, odcs, contract_path, domain_context, max_workers, system_prompt_override=None, user_prompt_override=None):
        if system_prompt_override:
            system_prompt = system_prompt_override.replace("{domain_context}", domain_context)
        else:
            system_prompt = QUALITY_SUGGESTION_SYSTEM_PROMPT_TEMPLATE.replace(
                "{domain_context}", domain_context
            )
        tasks = []
        if odcs.schema_:
            for schema in odcs.schema_:
                table_name = schema.name or schema.id or "Unknown"

                if schema.properties:
                    for prop in schema.properties:
                        contract_auth_defs = getattr(odcs, "authoritativeDefinitions", []) or []
                        schema_auth_defs = schema.authoritativeDefinitions or []
                        prop_auth_defs = (
                            getattr(prop, "authoritativeDefinitions", []) or []
                        )
                        all_auth_defs = (
                            contract_auth_defs + schema_auth_defs + prop_auth_defs
                        )
                        auth_defs_str = (
                            ", ".join([str(a) for a in all_auth_defs])
                            if all_auth_defs
                            else "None"
                        )

                        user_prompt_template = user_prompt_override or QUALITY_SUGGESTION_USER_PROMPT_TEMPLATE
                        user_prompt = user_prompt_template.format(
                            table_name=table_name,
                            column_name=prop.name,
                            column_description=prop.description or "No description.",
                            column_type=prop.logicalType,
                            is_required=prop.required,
                            is_primary_key=prop.primaryKey,
                            authoritative_definitions=auth_defs_str,
                        )
                        tasks.append(
                            {
                                "prop_ref": prop,
                                "system_prompt": system_prompt,
                                "user_prompt": user_prompt,
                            }
                        )

        results = self._run_tasks_concurrently(tasks, max_workers)

        for task, response in results:
            if response and "quality_rules" in response:
                prop = task["prop_ref"]
                existing_metrics = [
                    q.metric for q in (prop.quality or []) if getattr(q, "metric", None)
                ]

                rules_to_add = []
                for rule_dict in response["quality_rules"]:
                    metric = rule_dict.get("metric")
                    if not metric:
                        continue
                    if metric in existing_metrics:
                        continue

                    data_quality = DataQuality(**rule_dict)
                    if not data_quality.tags:
                        data_quality.tags = []
                    data_quality.tags.append("LLM_INFERRED")

                    if not data_quality.customProperties:
                        data_quality.customProperties = []
                    data_quality.customProperties.append(
                        CustomProperty(
                            property="graph_semantic.provenance", value="LLM_INFERRED"
                        )
                    )

                    rules_to_add.append(data_quality)
                    existing_metrics.append(metric)

                if rules_to_add:
                    if prop.quality is None:
                        prop.quality = []
                    prop.quality.extend(rules_to_add)

        with open(contract_path, "w") as f:
            f.write(odcs.to_yaml())

    def _run_tasks_concurrently(self, tasks, max_workers):
        results = []
        if tasks:
            if max_workers > 1:
                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=max_workers
                ) as executor:
                    futures = {
                        executor.submit(self._execute_inference, task): task
                        for task in tasks
                    }
                    for future in concurrent.futures.as_completed(futures):
                        results.append(future.result())
            else:
                for task in tasks:
                    results.append(self._execute_inference(task))
        return results

    def _execute_inference(self, task):
        response = self.llm_provider.generate_json(
            task["system_prompt"], task["user_prompt"], temperature=0.2
        )
        return task, response
