from app.database.flow_repository import get_flow_for_chatbot, upsert_flow


def save_flow(company_id: int, chatbot_id: int, name: str, flow_data: dict, action: str = "draft"):
    if not company_id:
        raise ValueError("company_id is required")
    if not chatbot_id:
        raise ValueError("chatbot_id is required")
    if not isinstance(flow_data, dict):
        raise ValueError("flow_data must be an object")

    normalized_action = "publish" if action == "publish" else "draft"
    return upsert_flow(company_id, chatbot_id, name or "Untitled Flow", flow_data, normalized_action)


def get_active_flow(company_id: int, chatbot_id: int):
    if not company_id:
        raise ValueError("company_id is required")
    if not chatbot_id:
        raise ValueError("chatbot_id is required")
    return get_flow_for_chatbot(company_id, chatbot_id)
