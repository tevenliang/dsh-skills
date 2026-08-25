#!/usr/bin/env python3
"""
exa_search.py — Exa MCP wrapper via Python SDK.
Usage:
  python3 exa_search.py "query" [--num-results N] [--highlights]
"""
import sys
import json
import os

try:
    from exa_py import Exa
except ImportError:
    print(json.dumps({"error": "exa-py not installed. Run: pip install exa-py"}))
    sys.exit(1)

EXA_KEY = os.environ.get("EXA_API_KEY", "")
if not EXA_KEY:
    # Try to read from .env
    env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
    if os.path.exists(env_file):
        for line in open(env_file):
            line = line.strip()
            if line.startswith("EXA_API_KEY="):
                EXA_KEY = line.split("=", 1)[1].strip().strip('"').strip("'")
                break

if not EXA_KEY:
    print(json.dumps({"error": "EXA_API_KEY not found. Set in .env or env var."}))
    sys.exit(1)

def main():
    args = sys.argv[1:]
    query = ""
    num_results = 8
    use_highlights = True

    i = 0
    while i < len(args):
        if args[i] == "--num-results" and i + 1 < len(args):
            num_results = int(args[i + 1])
            i += 2
        elif args[i] == "--no-highlights":
            use_highlights = False
            i += 1
        elif not args[i].startswith("--"):
            query = args[i]
            i += 1
        else:
            i += 1

    if not query:
        print(json.dumps({"error": "Usage: exa_search.py 'query' [--num-results N] [--highlights]"}))
        sys.exit(1)

    exa = Exa(api_key=EXA_KEY)

    try:
        kwargs = {
            "num_results": num_results,
        }
        if use_highlights:
            kwargs["highlights"] = {"num_sentences": 3}

        result = exa.search_and_contents(query, **kwargs)

        results = []
        for r in (result.results or []):
            item = {
                "title": r.title or "",
                "url": r.url or "",
                "snippet": "",
                "content": "",
            }
            if r.highlights:
                item["snippet"] = " ".join(r.highlights)[:300]
                item["content"] = " ".join(r.highlights)[:800]
            results.append(item)

        print(json.dumps(results, ensure_ascii=False, indent=None))

    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

if __name__ == "__main__":
    main()
