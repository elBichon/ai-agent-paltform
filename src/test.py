import requests

API_GATEWAY_URL = "http://localhost:8000/v1/call_agent"

payload = {
    "agent_id": "<agent_id>", 
    "model_id": "<model_id>",  
    "user_query": "<your request>",
    "user_email": "user@example.com"
}

# En-têtes HTTP requis par ton API
headers = {
    "x-api-key": "<api_key>",
    "Content-Type": "application/json"
}

try:
    response = requests.post(API_GATEWAY_URL, json=payload, headers=headers, timeout=30)
    response.raise_for_status()
    print("Response JSON:", response.json())
except requests.exceptions.HTTPError as e:
    print(f"HTTP Error: {e.response.status_code}")
    print("Server Detail:", e.response.text)
