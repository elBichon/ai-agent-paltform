
import json
import requests
from datetime import datetime, timezone

API_URL = "https://openrouter.ai/api/v1/models"
OUTPUT_FILE = "llm_pricing.json"


def fetch_models():
    response = requests.get(API_URL, timeout=30)
    response.raise_for_status()
    return response.json()["data"]


def generate_catalog(models):
    providers = {}

    for item in models:
        model_id = item.get("id")
        pricing = item.get("pricing", {})

        if not model_id:
            continue

        # OpenRouter prices are generally USD per token.
        try:
            input_price = float(pricing["prompt"])
            output_price = float(pricing["completion"])
        except (KeyError, TypeError, ValueError):
            continue

        provider = model_id.split("/", 1)[0]

        providers.setdefault(provider, {
            "model": provider,
            "base_url": "https://openrouter.ai/api/v1",
            "sub_models": []
        })

        providers[provider]["sub_models"].append({
            "id": model_id,
            "name": item.get("name"),
            "input_price_per_token": input_price,
            "output_price_per_token": output_price,
            "input_price_per_million_tokens": input_price * 1_000_000,
            "output_price_per_million_tokens": output_price * 1_000_000,
            "context_length": item.get("context_length")
        })

    return {
        "source": API_URL,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "models": list(providers.values())
    }


def main():
    models = fetch_models()
    catalog = generate_catalog(models)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        json.dump(catalog, file, indent=2, ensure_ascii=False)

    count = sum(
        len(provider["sub_models"])
        for provider in catalog["models"]
    )

    print(f"Saved {count} models to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
