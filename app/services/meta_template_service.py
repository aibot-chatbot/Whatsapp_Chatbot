import requests
from app.database import whatsapp_template_repository
from app.utils.whatsapp_graph import graph_api_version

def get_meta_templates(waba_id: str, access_token: str):
    """
    Fetches all WhatsApp message templates for a given WABA ID.
    """
    version = graph_api_version()
    url = f"https://graph.facebook.com/{version}/{waba_id}/message_templates"
    
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    
    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()
    return response.json().get("data", [])

def _requires_component_parameters(components):
    for component in components:
        kind = component["type"].upper()
        if kind == "HEADER":
            if component.get("format", "").upper() != "TEXT" or "{{" in component.get("text", ""):
                return True
        elif kind == "BUTTONS":
            for button in component.get("buttons", []):
                if (button["type"].upper() not in {"URL", "PHONE_NUMBER", "QUICK_REPLY"}
                        or "{{" in button.get("url", "")):
                    return True
        elif kind not in {"BODY", "FOOTER"}:
            return True
    return False


def create_meta_template(channel, name: str, language: str, category: str, components: list):
    """Submit to the connected WABA and track Meta's accepted template."""
    waba_id = channel.get("whatsapp_business_account_id") or channel["waba_id"]
    access_token = channel["access_token"]
    version = graph_api_version()
    url = f"https://graph.facebook.com/{version}/{waba_id}/message_templates"
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    # Meta requires the template name to be lowercase and underscore separated
    name = name.lower().replace(" ", "_")
    
    # Meta requires an example for media headers. Inject dummies if media_url is empty.
    for comp in components:
        if comp.get("type") == "HEADER" and comp.get("format") in ["IMAGE", "VIDEO", "DOCUMENT"]:
            # If the frontend didn't supply an example URL in the component, add a dummy one
            if not comp.get("example") or not comp["example"].get("header_url"):
                media_type = comp.get("format")
                if media_type == "IMAGE":
                    example_url = "https://raw.githubusercontent.com/FortAwesome/Font-Awesome/master/svgs/solid/image.svg"
                elif media_type == "VIDEO":
                    example_url = "https://www.w3schools.com/html/mov_bbb.mp4"
                else: # DOCUMENT
                    example_url = "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"
                    
                comp["example"] = {"header_url": [example_url]}
    
    payload = {
        "name": name,
        "language": language,
        "category": category,
        "components": components
    }
    
    body_has_variables = any(c["type"].upper() == "BODY" and "{{" in c.get("text", "") for c in components)
    requires_parameters = _requires_component_parameters(components)
    response = requests.post(url, headers=headers, json=payload, timeout=20)
    response.raise_for_status()
    result = response.json()
    whatsapp_template_repository.record_created({
        "company_id": channel["company_id"], "channel_id": channel["id"], "waba_id": waba_id,
        "meta_template_id": str(result["id"]), "name": name, "language": language,
        "category": result.get("category") or category, "status": result["status"],
        "body_has_variables": body_has_variables, "requires_component_parameters": requires_parameters,
    })
    return result

def delete_meta_template(channel, name: str):
    """
    Deletes a WhatsApp message template by name.
    """
    waba_id = channel.get("whatsapp_business_account_id") or channel["waba_id"]
    access_token = channel["access_token"]
    version = graph_api_version()
    url = f"https://graph.facebook.com/{version}/{waba_id}/message_templates"
    
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    
    params = {
        "name": name
    }
    
    response = requests.delete(url, headers=headers, params=params, timeout=20)
    response.raise_for_status()
    whatsapp_template_repository.remove_by_name(channel["company_id"], waba_id, name)
    return True
