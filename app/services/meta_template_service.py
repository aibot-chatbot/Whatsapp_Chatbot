import logging
import requests
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
    
    try:
        response = requests.get(url, headers=headers, timeout=20)
        if response.status_code == 200:
            return response.json().get("data", [])
        else:
            logging.error(f"Failed to fetch Meta templates: {response.text}")
            raise Exception(f"Failed to fetch templates: {response.json().get('error', {}).get('message', 'Unknown error')}")
    except Exception as e:
        logging.error(f"Error fetching Meta templates: {e}")
        raise

def create_meta_template(waba_id: str, access_token: str, name: str, language: str, category: str, components: list):
    """
    Creates a new WhatsApp message template in Meta using the provided components.
    """
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
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=20)
        if response.status_code in (200, 201):
            return response.json()
        else:
            logging.error(f"Failed to create Meta template: {response.text}")
            raise Exception(f"Failed to create template: {response.json().get('error', {}).get('message', 'Unknown error')}")
    except Exception as e:
        logging.error(f"Error creating Meta template: {e}")
        raise

def delete_meta_template(waba_id: str, access_token: str, name: str):
    """
    Deletes a WhatsApp message template by name.
    """
    version = graph_api_version()
    url = f"https://graph.facebook.com/{version}/{waba_id}/message_templates"
    
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    
    params = {
        "name": name
    }
    
    try:
        response = requests.delete(url, headers=headers, params=params, timeout=20)
        if response.status_code == 200:
            return True
        else:
            logging.error(f"Failed to delete Meta template: {response.text}")
            raise Exception(f"Failed to delete template: {response.json().get('error', {}).get('message', 'Unknown error')}")
    except Exception as e:
        logging.error(f"Error deleting Meta template: {e}")
        raise
