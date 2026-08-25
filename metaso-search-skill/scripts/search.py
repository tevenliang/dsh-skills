import sys
import json
import requests
import os


def metaso_search(api_key: str, request_body: dict):
    url = "https://metaso.cn/api/v1/search"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    response = requests.post(url, json=request_body, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python search.py <JSON>")
        sys.exit(1)

    try:
        parse_data = json.loads(sys.argv[1])
    except json.JSONDecodeError as e:
        print(f"JSON parse error: {e}")
        sys.exit(1)

    if "q" not in parse_data:
        print("Error: 'q' (query) is required.")
        sys.exit(1)

    api_key = os.getenv("METASO_API_KEY")
    if not api_key:
        print("Error: METASO_API_KEY not set.")
        sys.exit(1)

    # Build minimal body — only include fields with truthy values
    request_body = {"q": parse_data["q"], "size": parse_data.get("size", 10)}
    if parse_data.get("scope"):
        request_body["scope"] = parse_data["scope"]
    if parse_data.get("page", 1) != 1:
        request_body["page"] = parse_data["page"]
    if parse_data.get("conciseSnippet"):
        request_body["conciseSnippet"] = True
    if parse_data.get("includeSummary"):
        request_body["includeSummary"] = True
    if parse_data.get("includeRawContent"):
        request_body["includeRawContent"] = True

    try:
        results = metaso_search(api_key, request_body)
        print(json.dumps(results, indent=2, ensure_ascii=False))
    except requests.exceptions.HTTPError as e:
        print(f"HTTP Error: {e}")
        if e.response is not None:
            print(f"Response: {e.response.text}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
