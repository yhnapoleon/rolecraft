"""What a colleague receives of a shared work product.

One projection serves both ends of a share receipt: the context port writes it into the
fragment when a turn first receives the share, and the store recomputes it when any later
turn of that colleague replays the receipt. The two once kept separate copies; when the
port's copy changed (2026-10-26) every later turn after sharing a plan failed its receipt
check and the colleague fell silent for the rest of the session.
"""

from typing import Any

from career_lab.contracts.v2 import WorkProductVersion, canonical


def shared_work(product: Any) -> dict[str, Any]:
    """A plan whose text lives in its sections is shown as those sections in written order,
    not as an empty ``content`` beside a nested payload (a colleague read that as "nothing
    written yet"). Other works keep their original shape."""
    payload = (
        product.structured_payload.model_dump(mode="json") if product.structured_payload else None
    )
    if payload and payload.get("type") == "plan" and not product.content.strip():
        return {
            "title": product.title,
            "purpose": product.purpose,
            "kind": "plan",
            "sections": [
                {"section": key, "text": text}
                for key, text in payload["sections"].items()
                if str(text).strip()
            ],
        }
    return {
        "title": product.title,
        "content": product.content,
        "purpose": product.purpose,
        "structured_payload": payload,
    }


def shared_work_text(product: Any) -> str:
    """The fragment text a received share carries."""
    return canonical(shared_work(product))


def receipt_texts(content: dict[str, Any]) -> set[str]:
    """Fragment texts a stored product version may have been received as: the current
    projection, and the four-field shape every share was received as before 2026-10-26."""
    texts = {
        canonical(
            {k: content.get(k) for k in ("title", "content", "purpose", "structured_payload")}
        )
    }
    try:
        texts.add(shared_work_text(WorkProductVersion.model_validate(content)))
    except ValueError:
        pass
    return texts
