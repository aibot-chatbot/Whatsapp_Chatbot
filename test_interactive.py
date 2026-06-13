from dotenv import load_dotenv
load_dotenv()

import json
from app.utils.whatsapp_utils import get_interactive_button_message_input
import re

def test_payload():
    # Simulate an AI response with buttons
    ai_response = "Here are your choices! [BUTTON: Sales] [BUTTON: Support] [BUTTON: Pricing] [BUTTON: Extra]"
    
    # Extract buttons
    button_matches = re.findall(r"\[BUTTON:\s*(.*?)\]", ai_response, re.IGNORECASE)
    clean_response = re.sub(r"\[BUTTON:\s*(.*?)\]", "", ai_response, flags=re.IGNORECASE).strip()
    
    print("Raw AI:", ai_response)
    print("Clean Text:", clean_response)
    print("Buttons Extracted:", button_matches)
    
    # Generate Payload
    payload = get_interactive_button_message_input("1234567890", clean_response, button_matches)
    
    print("\n--- JSON Payload ---")
    print(json.dumps(json.loads(payload), indent=2))

if __name__ == "__main__":
    test_payload()
