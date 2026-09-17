import logging
from dataclasses import dataclass

from app.database.flow_repository import (
    get_active_published_flow,
    get_open_conversation_for_flow,
    insert_execution_log,
    update_conversation_flow_state,
)


AI_HANDOFF_NODE_NAMES = {
    "ai",
    "ai_response",
    "ask_ai",
    "handoff_ai",
    "rag",
    "rag_response",
}


@dataclass
class _ExecutionContext:
    company_id: int
    chatbot_id: int
    customer_id: str
    source_channel: str | None
    flow: dict
    conversation: dict | None

    @property
    def conversation_id(self):
        return (self.conversation or {}).get("id")


@dataclass(frozen=True)
class FlowExecutionResult:
    status: str
    reply: str | None = None

    @property
    def handled(self):
        return self.status == "handled" and bool(self.reply)

    @property
    def should_handoff_to_ai(self):
        return self.status in {"no_flow", "not_applicable", "handoff"}


def _result(status: str, reply: str | None = None):
    return FlowExecutionResult(status=status, reply=reply)


def process_flow_message(company_id: int, chatbot_id: int, user_message: str, customer_id: str, source_channel: str | None = None, conversation: dict | None = None):
    """Return structured Flow Builder execution status for one inbound message.

    Status values:
    - no_flow: no active/published flow exists for this company + chatbot.
    - not_applicable: a flow exists but no trigger/current node should handle this message.
    - handoff: the flow explicitly ended or handed off to AI/RAG.
    - handled: the flow produced a reply.
    - failed: execution failed and should not be treated as normal no-flow.
    """
    try:
        flow = get_active_published_flow(company_id, chatbot_id)
        if not flow:
            return _result("no_flow")

        flow_data = _select_runtime_flow_data(flow)
        nodes = _extract_nodes(flow_data)
        if not nodes:
            logging.warning("Active flow %s for chatbot %s has no executable nodes.", flow.get("id"), chatbot_id)
            return _result("handoff")

        conversation = conversation if conversation is not None else get_open_conversation_for_flow(chatbot_id, str(customer_id), source_channel)
        ctx = _ExecutionContext(company_id, chatbot_id, str(customer_id), source_channel, flow, conversation)

        current_node_id = (conversation or {}).get("current_node_id")
        active_flow_id = (conversation or {}).get("active_flow_id")
        if active_flow_id and str(active_flow_id) == str(flow.get("id")) and current_node_id:
            reply = _continue_flow(ctx, nodes, str(current_node_id), user_message)
            return _result("handled", reply) if reply else _result("handoff")

        trigger_node_id = _find_matching_trigger(nodes, user_message)
        if not trigger_node_id:
            return _result("not_applicable")

        next_node_id = _first_connected_node(nodes[trigger_node_id])
        if not next_node_id:
            _clear_flow_state(ctx)
            return _result("handoff")

        _set_flow_state(ctx, flow.get("id"), next_node_id)
        reply = _execute_from_node(ctx, nodes, next_node_id)
        return _result("handled", reply) if reply else _result("handoff")
    except Exception as exc:
        logging.exception("Flow executor failed for chatbot %s: %s", chatbot_id, exc)
        return _result("failed")


def _select_runtime_flow_data(flow: dict):
    if flow.get("published_data"):
        return flow["published_data"]
    return flow.get("flow_data") or {}


def _extract_nodes(flow_data: dict):
    if not isinstance(flow_data, dict):
        return {}
    drawflow_home = flow_data.get("drawflow", {}).get("Home", {}).get("data")
    if isinstance(drawflow_home, dict):
        return {str(node_id): node for node_id, node in drawflow_home.items() if isinstance(node, dict)}
    nodes = flow_data.get("nodes")
    if isinstance(nodes, dict):
        return {str(node_id): node for node_id, node in nodes.items() if isinstance(node, dict)}
    if isinstance(nodes, list):
        return {str(node.get("id")): node for node in nodes if isinstance(node, dict) and node.get("id") is not None}
    return {}


def _node_name(node: dict):
    return str(node.get("name") or node.get("type") or "").strip().lower()


def _node_data(node: dict):
    data = node.get("data")
    return data if isinstance(data, dict) else {}


def _find_matching_trigger(nodes: dict, user_message: str):
    normalized_message = (user_message or "").strip().lower()
    for node_id, node in nodes.items():
        if _node_name(node) != "trigger":
            continue
        data = _node_data(node)
        raw_keywords = data.get("keywords") or data.get("keyword") or data.get("trigger") or ""
        if isinstance(raw_keywords, str):
            keywords = [part.strip().lower() for part in raw_keywords.replace("\n", ",").split(",")]
        elif isinstance(raw_keywords, list):
            keywords = [str(part).strip().lower() for part in raw_keywords]
        else:
            keywords = []
        if any(keyword and keyword == normalized_message for keyword in keywords):
            return node_id
    return None


def _continue_flow(ctx: _ExecutionContext, nodes: dict, current_node_id: str, user_message: str):
    current_node = nodes.get(current_node_id)
    if not current_node:
        _clear_flow_state(ctx)
        return None

    if _node_name(current_node) == "interactive_buttons":
        next_node_id = _button_destination(current_node, user_message)
        if not next_node_id:
            return _render_interactive_buttons(ctx, current_node_id, current_node)
        _set_flow_state(ctx, ctx.flow.get("id"), next_node_id)
        return _execute_from_node(ctx, nodes, next_node_id)

    return _execute_from_node(ctx, nodes, current_node_id)


def _execute_from_node(ctx: _ExecutionContext, nodes: dict, node_id: str, visited=None):
    visited = visited or set()
    if node_id in visited:
        logging.warning("Flow %s loop detected at node %s.", ctx.flow.get("id"), node_id)
        _clear_flow_state(ctx)
        return None
    visited.add(node_id)

    node = nodes.get(str(node_id))
    if not node:
        _clear_flow_state(ctx)
        return None

    node_name = _node_name(node)
    _log_node(ctx, node_id, node_name)

    if node_name in AI_HANDOFF_NODE_NAMES:
        _clear_flow_state(ctx)
        return None

    if node_name in {"send_message", "message", "text"}:
        reply_text = _message_text(node)
        next_node_id = _first_connected_node(node)
        if next_node_id:
            _set_flow_state(ctx, ctx.flow.get("id"), next_node_id)
            next_reply = _execute_from_node(ctx, nodes, next_node_id, visited)
            if reply_text and next_reply:
                return f"{reply_text}\n\n{next_reply}"
            return reply_text or next_reply
        _clear_flow_state(ctx)
        return reply_text or None

    if node_name == "interactive_buttons":
        return _render_interactive_buttons(ctx, node_id, node)

    if node_name in {"end", "stop"}:
        _clear_flow_state(ctx)
        return None

    next_node_id = _first_connected_node(node)
    if next_node_id:
        _set_flow_state(ctx, ctx.flow.get("id"), next_node_id)
        return _execute_from_node(ctx, nodes, next_node_id, visited)

    _clear_flow_state(ctx)
    return None


def _message_text(node: dict):
    data = _node_data(node)
    return str(data.get("text") or data.get("message") or data.get("body") or "").strip()


def _render_interactive_buttons(ctx: _ExecutionContext, node_id: str, node: dict):
    data = _node_data(node)
    text = str(data.get("body_text") or data.get("text") or data.get("message") or "Options:").strip()
    labels = _button_labels(node)
    if labels:
        text = f"{text}\n" + "\n".join(f"{index}. {label}" for index, label in enumerate(labels, start=1))
    _set_flow_state(ctx, ctx.flow.get("id"), node_id)
    return text


def _button_labels(node: dict):
    data = _node_data(node)
    if isinstance(data.get("buttons"), list):
        return [str(item.get("label") if isinstance(item, dict) else item).strip() for item in data["buttons"] if str(item).strip()]
    return [str(data.get(f"btn_{index}") or "").strip() for index in range(1, 4) if str(data.get(f"btn_{index}") or "").strip()]


def _button_destination(node: dict, user_message: str):
    labels = _button_labels(node)
    normalized = (user_message or "").strip().lower()
    selected_index = None
    if normalized.isdigit():
        selected_index = int(normalized)
    else:
        for index, label in enumerate(labels, start=1):
            if normalized == label.lower():
                selected_index = index
                break
    if not selected_index:
        return None
    return _first_connected_node(node, f"output_{selected_index}")


def _first_connected_node(node: dict, output_key: str = "output_1"):
    outputs = node.get("outputs") if isinstance(node.get("outputs"), dict) else {}
    output = outputs.get(output_key) if isinstance(outputs.get(output_key), dict) else {}
    connections = output.get("connections") if isinstance(output.get("connections"), list) else []
    if connections:
        destination = connections[0].get("node")
        return str(destination) if destination is not None else None

    edges = node.get("edges")
    if isinstance(edges, list) and edges:
        destination = edges[0].get("target") if isinstance(edges[0], dict) else edges[0]
        return str(destination) if destination is not None else None
    return None


def _set_flow_state(ctx: _ExecutionContext, active_flow_id, current_node_id):
    if ctx.conversation_id:
        update_conversation_flow_state(ctx.conversation_id, active_flow_id, current_node_id)


def _clear_flow_state(ctx: _ExecutionContext):
    if ctx.conversation_id:
        update_conversation_flow_state(ctx.conversation_id, None, None)


def _log_node(ctx: _ExecutionContext, node_id: str, node_type: str):
    try:
        insert_execution_log(
            ctx.flow.get("company_id"),
            ctx.chatbot_id,
            ctx.conversation_id,
            ctx.flow.get("id"),
            node_id,
            node_type,
        )
    except Exception as exc:
        logging.debug("Flow execution log skipped for chatbot %s: %s", ctx.chatbot_id, exc)
