import requests

def test_api():
    base_url = "http://127.0.0.1:8000"
    
    # 1. Login
    print("Logging in...")
    login_res = requests.post(f"{base_url}/api/auth/login", json={
        "email": "deeying888@gmail.com",
        "password": "Dyanime@100"
    })
    
    if login_res.status_code != 200:
        print("Login failed:", login_res.text)
        return
        
    token = login_res.json().get("token")
    print("Login successful, got token.")
    
    # 2. Get chatbots
    headers = {"Authorization": f"Bearer {token}"}
    bots_res = requests.get(f"{base_url}/api/bots", headers=headers)
    bots_data = bots_res.json()
    if not bots_data.get("data"):
        print("No bots found.")
        return
        
    bot_id = bots_data["data"][0]["id"]
    print(f"Using Bot ID: {bot_id}")
    
    # 3. Test escalations API
    print("Fetching escalations...")
    esc_res = requests.get(f"{base_url}/api/agent/escalations?chatbot_id={bot_id}", headers=headers)
    print("Status code:", esc_res.status_code)
    try:
        print("Response JSON:", esc_res.json())
    except Exception as e:
        print("Failed to parse JSON:", esc_res.text)

if __name__ == "__main__":
    test_api()
