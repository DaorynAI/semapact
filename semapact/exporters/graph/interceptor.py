from typing import List

from open_data_contract_standard.model import OpenDataContractStandard
from semapact.exporters.graph_exporter import GraphNode


class SovereigntyInterceptor:
    def intercept(
        self, contract: OpenDataContractStandard, nodes: List[GraphNode]
    ) -> None:
        """
        Mutates GraphNode objects in-place to redact `example_value` if the node represents a PII column.
        In the new GraphExporter design, `is_pii` is evaluated upfront and injected directly into the `Column` node's properties.
        """
        for node in nodes:
            if node.type == "Column":
                if node.properties and node.properties.get("is_pii") is True:
                    # Only mutate if there's an example value to redact? No, we might want to proactively set it.
                    # Or at least if the property dictionary exists.
                    node.properties["example_value"] = "[REDACTED_PII]"
