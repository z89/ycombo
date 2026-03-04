#!/usr/bin/env python3
"""
YCOMBO — AI & Dev Intelligence Feed
Fetches HN posts via Algolia API, writes JSON to /tmp/ycombo_cache.json
for the eww widget to consume.
"""

import sys
import time
import os
import json
from datetime import datetime

try:
    import requests
except ImportError:
    sys.exit(1)

CACHE_JSON = "/tmp/ycombo_cache.json"

RELEVANT = [
    "ai", "llm", "agent", "claude", "gpt", "openai", "anthropic",
    "cursor", "copilot", "rag", "embedding", "transformer", "agentic",
    "langchain", "langgraph", "workflow", "mcp", "context protocol",
    "neural", "inference", "fine-tun", "prompt engineering", "benchmark",
    "multimodal", "autonomous", "code generation", "software engineer",
    "gemini", "mistral", "llama", "deepseek", "o1", "o3",
    "computer use", "function calling", "tool use", "ai coding",
]

LATEST_QUERIES = [
    "AI agent",
    "LLM coding",
    "agentic workflow",
    "Claude GPT",
    "software engineering AI",
    "RAG embedding",
    "MCP model context",
    "cursor copilot",
]

TOP5_QUERIES = [
    "AI agent architecture",
    "LLM engineering",
    "agentic system",
    "AI workflow best practices",
    "software engineering LLM",
]

def is_relevant(title: str) -> bool:
    t = title.lower()
    return any(k in t for k in RELEVANT)

def algolia(query: str, by_date: bool = False, hours: int = 0,
            min_pts: int = 0, limit: int = 50) -> list:
    endpoint = "search_by_date" if by_date else "search"
    params: dict = {"query": query, "tags": "story", "hitsPerPage": limit}
    filters = []
    if hours:
        filters.append(f"created_at_i>{int(time.time()) - hours * 3600}")
    if min_pts:
        filters.append(f"points>{min_pts}")
    if filters:
        params["numericFilters"] = ",".join(filters)
    r = requests.get(f"https://hn.algolia.com/api/v1/{endpoint}", params=params, timeout=12)
    r.raise_for_status()
    return r.json().get("hits", [])

def time_ago(ts: int) -> str:
    diff = int(time.time()) - ts
    if diff < 3600:   return f"{diff // 60}m"
    if diff < 86400:  return f"{diff // 3600}h"
    return f"{diff // 86400}d"

def fmt_pts(n: int) -> str:
    return f"{n/1000:.1f}k" if n >= 1000 else str(n)

def trunc(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n - 1] + "…"

def fetch_latest(n: int = 20) -> list:
    seen: dict = {}
    for query in LATEST_QUERIES:
        for h in algolia(query, by_date=True, hours=336, limit=30):
            oid = h.get("objectID")
            if oid not in seen and h.get("title") and is_relevant(h["title"]):
                seen[oid] = h
        if len(seen) >= n * 2:
            break
    results = sorted(seen.values(), key=lambda x: x.get("created_at_i", 0), reverse=True)
    if len(results) < n:
        for query in LATEST_QUERIES[:4]:
            for h in algolia(query, by_date=True, hours=336, limit=30):
                oid = h.get("objectID")
                if oid not in seen and h.get("title") and is_relevant(h["title"]):
                    seen[oid] = h
        results = sorted(seen.values(), key=lambda x: x.get("created_at_i", 0), reverse=True)
    return results[:n]

def fetch_top5() -> list:
    seen: dict = {}
    for query in TOP5_QUERIES:
        for h in algolia(query, by_date=False, hours=720, min_pts=80, limit=20):
            oid = h.get("objectID")
            pts = h.get("points", 0)
            if oid not in seen and h.get("title") and is_relevant(h["title"]) and pts >= 80:
                seen[oid] = h
    return sorted(seen.values(), key=lambda x: x.get("points", 0), reverse=True)[:5]

def to_post(h: dict, idx: int) -> dict:
    return {
        "idx":      idx,
        "id":       h.get("objectID", ""),
        "title":    trunc(h.get("title", "Untitled"), 90),
        "pts":      fmt_pts(h.get("points", 0)),
        "comments": h.get("num_comments", 0),
        "ago":      time_ago(h.get("created_at_i", 0)),
    }

def write_cache(data: dict) -> None:
    with open(CACHE_JSON, "w") as f:
        json.dump(data, f)

def main():
    try:
        latest = fetch_latest(40)
        top5   = fetch_top5()
        data   = {
            "updated": datetime.now().strftime("%I:%M %p").lstrip("0"),
            "offline": False,
            "latest":  [to_post(h, i) for i, h in enumerate(latest, 1)],
            "top5":    [to_post(h, i) for i, h in enumerate(top5, 1)],
        }
        write_cache(data)
        print(json.dumps(data))

    except requests.exceptions.ConnectionError:
        if os.path.exists(CACHE_JSON):
            with open(CACHE_JSON) as f:
                data = json.load(f)
            data["offline"] = True
            data["updated"] = "offline"
        else:
            data = {"updated": "offline", "offline": True, "latest": [], "top5": []}
        write_cache(data)
        print(json.dumps(data))

    except Exception as e:
        data = {"updated": f"err", "offline": False, "latest": [], "top5": []}
        write_cache(data)
        print(json.dumps(data))

if __name__ == "__main__":
    main()
