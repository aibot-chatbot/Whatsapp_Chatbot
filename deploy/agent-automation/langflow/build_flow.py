"""Build an importable bridge flow from the repository's existing IO templates."""
from copy import deepcopy
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def build_flow():
    source = json.loads((ROOT / "langflow/knowledge-document-follow-up.langflow.json").read_text(encoding="utf-8"))
    nodes = {}
    for node in source["data"]["nodes"]:
        if node["data"]["type"] in {"ChatInput", "ChatOutput"}:
            item = deepcopy(node)
            name = item["data"]["type"]
            item["id"] = item["data"]["id"] = name + "-analysis"
            item["data"]["node"]["template"]["should_store_message"]["value"] = False
            item["position"] = {"x": 0 if name == "ChatInput" else 600, "y": 0}
            nodes[name] = item
    bridge = {
        "id": "AnalysisModelStep-analysis", "type": "genericNode", "position": {"x": 300, "y": 0},
        "data": {"id": "AnalysisModelStep-analysis", "type": "AnalysisModelStep", "showNode": True,
                 "node": {"display_name": "Analysis Model Step", "description": "Run and step IDs only; Flask checks scope and lease.",
                          "base_classes": ["Message"], "field_order": ["input_value"], "icon": "ShieldCheck",
                          "template": {"_type": "Component",
                              "input_value": {"name": "input_value", "display_name": "Run and step IDs", "type": "str",
                                              "_input_type": "MessageTextInput", "input_types": ["Message"],
                                              "required": True, "show": True, "value": ""},
                              "code": {"name": "code", "type": "code", "required": True, "show": True,
                                       "advanced": True, "value": (HERE / "components/agent_analysis/model_step.py").read_text(encoding="utf-8")}},
                          "outputs": [{"name": "message", "display_name": "Step result", "method": "step_result",
                                       "types": ["Message"], "selected": "Message", "cache": False}],
                          "tool_mode": False}},
    }
    edges = []
    for source_node, target_node in [(nodes["ChatInput"], bridge), (bridge, nodes["ChatOutput"])]:
        source_handle = {"dataType": source_node["data"]["type"], "id": source_node["id"], "name": "message", "output_types": ["Message"]}
        target_handle = {"fieldName": "input_value", "id": target_node["id"], "inputTypes": ["Message"], "type": "str"}
        encode = lambda value: json.dumps(value, separators=(",", ":")).replace('"', "œ")
        edges.append({"id": source_node["id"] + "-to-" + target_node["id"], "source": source_node["id"],
                      "target": target_node["id"], "sourceHandle": encode(source_handle), "targetHandle": encode(target_handle),
                      "data": {"sourceHandle": source_handle, "targetHandle": target_handle}})
    return {"name": "Analysis authenticated model bridge", "description": "Two persisted steps maximum. No provider tools in this flow.",
            "endpoint_name": "analysis-model-bridge", "is_component": False, "webhook": False,
            "data": {"nodes": [nodes["ChatInput"], bridge, nodes["ChatOutput"]], "edges": edges}}


if __name__ == "__main__":
    target = HERE / "analysis-model-bridge.langflow.json"
    target.write_text(json.dumps(build_flow(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target.name)
