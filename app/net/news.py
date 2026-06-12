"""Trending AI news, sourced from Hacker News via the Algolia API.

Strategy: pull the current HN front page (genuinely trending right now) and
keep only AI-related stories. If the front page is light on AI at the moment,
supplement with a popularity-ranked AI keyword search. One request normally,
two at most. No auth, public endpoint."""
from app.net.http import get_json

# UA so Cloudflare/Algolia don't 403 MicroPython's empty default (see crypto.py).
HEADERS = {"User-Agent": "Mozilla/5.0 (presto-cockpit)", "Accept": "application/json"}

FRONT = "https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=40"
SEARCH = ("https://hn.algolia.com/api/v1/search?query=AI&tags=story"
          "&numericFilters=points%3E40&hitsPerPage=40")

KEYWORDS = (
    " ai ", " ai.", " ai,", " ai:", "a.i.", " ml ", " llm", "gpt", "openai",
    "anthropic", "claude", "gemini", "llama", "mistral", "deepseek", "qwen",
    "grok", "copilot", "neural", "machine learning", "deep learning", "agent",
    "chatbot", "transformer", "diffusion", "stable diffusion", "midjourney",
    "hugging face", "huggingface", "nvidia", "inference", "fine-tun", "rag",
    "embedding", "multimodal", "foundation model", "language model",
)


def _is_ai(title):
    t = " " + (title or "").lower() + " "
    return any(k in t for k in KEYWORDS)


def _row(h):
    return {
        "title": h.get("title") or "",
        "url": h.get("url") or "",
        "points": h.get("points") or 0,
        "comments": h.get("num_comments") or 0,
        "author": h.get("author") or "",
        "id": h.get("objectID"),
    }


def fetch(limit=15):
    data, err = get_json(FRONT, timeout=8, headers=HEADERS)
    hits = []
    if data and not err:
        hits = [_row(h) for h in data.get("hits", []) if _is_ai(h.get("title") or "")]

    if len(hits) < 5:
        d2, e2 = get_json(SEARCH, timeout=8, headers=HEADERS)
        if d2 and not e2:
            seen = set(h["id"] for h in hits)
            for h in d2.get("hits", []):
                if h.get("objectID") in seen:
                    continue
                if _is_ai(h.get("title") or ""):
                    hits.append(_row(h))
        elif err:
            return None, err  # both calls failed
    elif err:
        return None, err

    hits.sort(key=lambda x: -x["points"])
    return hits[:limit], None
