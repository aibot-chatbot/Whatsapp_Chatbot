import requests

url = "http://localhost:8000/api/guide/chat"
data = {
    "message": "hi",
    "bot_id": "52",
    "company_id": "34"
}
headers = {
    "Content-Type": "application/json"
}
try:
    response = requests.post(url, json=data, headers=headers)
    print("STATUS:", response.status_code)
    print("REPLY:", response.json())
except Exception as e:
    print(f"ERROR: {e}")
