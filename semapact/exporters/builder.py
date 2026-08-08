from typing import List, Any
from open_data_contract_standard.model import OpenDataContractStandard, Relationship


class InMemoryGraphBuilder:
    def __init__(self, data_contract: OpenDataContractStandard):
        if not isinstance(data_contract, OpenDataContractStandard):
            raise ValueError(
                "Input must be an instantiated OpenDataContractStandard model"
            )
        self.data_contract = data_contract
        try:
            import networkx as nx

            self.nx = nx
        except ImportError:
            raise ImportError(
                "networkx is required to build the graph. Please install with `pip install networkx` or `uv sync --extra graph`"
            )

    def build(self) -> Any:
        graph = self.nx.MultiDiGraph()

        import logging

        logger = logging.getLogger(__name__)

        for schema_obj in self.data_contract.schema_ or []:
            table_name = schema_obj.name

            # Extract relationships
            rels: List[Relationship] = []
            rels.extend(schema_obj.relationships or [])
            for prop in schema_obj.properties or []:
                rels.extend(prop.relationships or [])

            # Check if this table is a junction edge
            is_junction = False
            for cp in schema_obj.customProperties or []:
                if cp.property == "graph_export.is_junction_edge" and (
                    cp.value is True or str(cp.value).lower() == "true"
                ):
                    is_junction = True
                    break

            # Check N-ary junction fallback
            if is_junction:
                num_rels = len(rels)
                if num_rels >= 3:
                    logger.warning(
                        f"Schema {table_name} marked as junction but has {num_rels} relationships. "
                        "Property graphs do not support hyperedges. Falling back to treating it as a standard Table node."
                    )
                    is_junction = False
                elif num_rels <= 1:
                    logger.warning(
                        f"Schema {table_name} marked as junction but has {num_rels} relationships (needs exactly 2). "
                        "Falling back to treating it as a standard Table node."
                    )
                    is_junction = False

            if not is_junction:
                # Add a regular node
                graph.add_node(table_name)

                for rel in rels:
                    # In ODCS, 'to' could be a string or list of strings
                    target_tables = self._extract_target_tables(rel)
                    for target_table in target_tables:
                        is_source = False
                        edge_label = target_table.upper()

                        for cp in rel.customProperties or []:
                            if cp.property == "graph_export.is_source" and (
                                cp.value is True or str(cp.value).lower() == "true"
                            ):
                                is_source = True
                            elif cp.property == "graph_semantic.edge_label":
                                if isinstance(cp.value, str) and cp.value.strip():
                                    edge_label = cp.value

                        # Detect self-reference
                        if target_table == table_name:
                            # Self-referential graph edges can still be added
                            graph.add_edge(
                                table_name,
                                target_table,
                                label=edge_label,
                                is_junction_edge=False,
                            )
                            continue

                        if is_source:
                            # Reversed direction: FK Target -> Current Table
                            graph.add_edge(
                                target_table,
                                table_name,
                                label=edge_label,
                                is_junction_edge=False,
                            )
                        else:
                            # Default direction: Current Table -> FK Target
                            graph.add_edge(
                                table_name,
                                target_table,
                                label=edge_label,
                                is_junction_edge=False,
                            )
            else:
                # Junction table logic (exactly 2 relations)
                source_fk = None
                target_fk = None

                for rel in rels:
                    is_source = False
                    for cp in rel.customProperties or []:
                        if cp.property == "graph_export.is_source" and (
                            cp.value is True or str(cp.value).lower() == "true"
                        ):
                            is_source = True
                            break

                    if is_source:
                        source_fk = rel
                    else:
                        target_fk = rel

                if not source_fk or not target_fk:
                    continue

                source_tables = self._extract_target_tables(source_fk)
                target_tables = self._extract_target_tables(target_fk)

                if not source_tables or not target_tables:
                    continue

                # We'll map each source to each target
                for source_table in source_tables:
                    for target_table in target_tables:
                        edge_label = target_table.upper()
                        for cp in source_fk.customProperties or []:
                            if cp.property == "graph_semantic.edge_label":
                                if isinstance(cp.value, str) and cp.value.strip():
                                    edge_label = cp.value
                                    break

                        # Properties to attach to the edge
                        edge_props = {}
                        for prop in schema_obj.properties or []:
                            if not prop.relationships:
                                # Extract the prop type
                                prop_type = getattr(
                                    prop,
                                    "logicalType",
                                    getattr(
                                        prop,
                                        "physicalType",
                                        getattr(prop, "type", None),
                                    ),
                                )
                                if (
                                    prop_type is None
                                    and hasattr(prop, "__pydantic_extra__")
                                    and prop.__pydantic_extra__
                                ):
                                    prop_type = prop.__pydantic_extra__.get("type")
                                edge_props[prop.name] = prop_type

                        graph.add_edge(
                            source_table,
                            target_table,
                            label=edge_label,
                            is_junction_edge=True,
                            **edge_props,
                        )

        return graph

    def _extract_target_tables(self, rel: Relationship) -> List[str]:
        # Handle ODCS 3.1 schema-level or property-level relationship parsing
        to_field = rel.to
        if not to_field:
            to_field = getattr(rel, "from_", None)

        tables = set()
        if isinstance(to_field, str):
            parts = to_field.split(".")
            tables.add(parts[0] if len(parts) > 1 else to_field)
        elif isinstance(to_field, list):
            for t in to_field:
                if isinstance(t, str):
                    parts = t.split(".")
                    tables.add(parts[0] if len(parts) > 1 else t)
        return list(tables)
