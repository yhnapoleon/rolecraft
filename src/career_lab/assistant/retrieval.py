import math
import re
from collections import Counter


def tokens(text: str) -> list[str]:
    text = text.lower()
    chunks = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", text)
    return [token for chunk in chunks for token in ([chunk] if chunk.isascii() or len(chunk) == 1 else [chunk[i:i+2] for i in range(len(chunk)-1)])]


def retrieve(query: str, documents: list[dict], limit=3) -> list[dict]:
    """BM25 over Chinese bigrams/Latin words; permissions must be filtered first."""
    if not documents:
        return []
    terms = set(tokens(query))
    bags = [Counter(tokens(d["text"])) for d in documents]
    lengths = [sum(b.values()) for b in bags]
    avg = sum(lengths) / len(lengths) or 1
    ranked = []
    for doc, bag, length in zip(documents, bags, lengths):
        score = 0.0
        for term in terms:
            df = sum(term in b for b in bags)
            freq = bag[term]
            idf = math.log(1 + (len(bags) - df + .5) / (df + .5))
            score += idf * freq * 2.2 / (freq + 1.2 * (.25 + .75 * length / avg))
        if score > 0:
            ranked.append(doc | {"score": score})
    return sorted(ranked, key=lambda d: (-d["score"], d["id"]))[:limit]
