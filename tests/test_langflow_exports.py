"""Export connections must survive Langflow's frontend edge validation."""
import json
from pathlib import Path


def test_export_connections_match_visible_component_handles():
    root = Path(__file__).resolve().parents[1] / "langflow"
    for filename, edge_count in (
        ("crm-stage-automation.langflow.json", 8),
        ("knowledge-document-follow-up.langflow.json", 3),
    ):
        graph = json.loads((root / filename).read_text(encoding="utf-8"))["data"]
        nodes = {node["id"]: node["data"] for node in graph["nodes"]}
        assert len(graph["edges"]) == edge_count, filename
        for edge in graph["edges"]:
            connection = f"{edge['source']} -> {edge['target']}"
            target = edge["data"]["targetHandle"]
            field = nodes[edge["target"]]["node"]["template"][target["fieldName"]]
            # Langflow removes edges to advanced/hidden inputs when loading or saving.
            assert not field.get("advanced", False), connection
            assert field.get("show", True), connection
            assert target["id"] == edge["target"], connection
            assert target["type"] == field["type"], connection
            assert target["inputTypes"] == field["input_types"], connection
            for handle_name in ("sourceHandle", "targetHandle"):
                decoded = json.loads(edge[handle_name].replace("œ", '"'))
                assert decoded == edge["data"][handle_name], connection
            assert edge["id"] == (
                f"reactflow__edge-{edge['source']}{edge['sourceHandle']}"
                f"-{edge['target']}{edge['targetHandle']}"
            ), connection


if __name__ == "__main__":
    test_export_connections_match_visible_component_handles()
