import requests
import json

def call_ai_agent(api_key, agent_id, query):
    """
    Example script to call the AI Platform API.
    """
    url = "http://localhost:8000/v1/call_agent"
    
    headers = {
        "X-API-Key": api_key,
        "Content-Type": "application/json"
    }
    
    payload = {
        "agent_id": agent_id,
        "user_query": query
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        
        # Check if the request was successful
        if response.status_code == 200:
            result = response.json()
            print("Successfully retrieved agent context:")
            print(json.dumps(result, indent=2))
            return result
        elif response.status_code == 401:
            print("Authentication failed: Invalid or missing API Key")
        elif response.status_code == 429:
            print("Rate limit exceeded. Please try again later.")
        else:
            print(f"Error {response.status_code}: {response.text}")
            
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    # Replace these with your actual values from the dashboard
    MY_API_KEY = "sk-..." 
    MY_AGENT_ID = "..." 
    USER_QUERY = "Explain the latest financial report using your tools."

    call_ai_agent(MY_API_KEY, MY_AGENT_ID, USER_QUERY)
