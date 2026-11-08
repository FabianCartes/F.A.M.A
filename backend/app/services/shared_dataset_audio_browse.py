"""Read-only response pagination; inventory enumeration remains eager."""
import base64
import hashlib
import json

from fastapi import HTTPException


def browse_files(dataset, files, *, class_name=None, feedback=None, limit=50, cursor=None):
    """Facet the full inventory, then intersect filters and page canonical paths."""
    if type(limit) is not int or not 1 <= limit <= 200:
        raise HTTPException(422, "Invalid browse limit.")
    rows = sorted((dict(item, is_feedback=item.get("is_feedback", False)) for item in files),
                  key=lambda item: item["path"])
    snapshot = hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False,
                                         separators=(",", ":")).encode()).hexdigest()
    binding = {"dataset": dataset, "class_name": class_name, "feedback": feedback}
    offset = 0
    if cursor is not None:
        try:
            state = json.loads(base64.b64decode(cursor.encode(), altchars=b"-_", validate=True))
            if (not isinstance(state, dict) or set(state) != set(binding) | {"snapshot", "offset"}
                    or any(state[key] != value for key, value in binding.items())
                    or type(state["offset"]) is not int or state["offset"] < 0
                    or not isinstance(state["snapshot"], str)):
                raise ValueError
        except (ValueError, TypeError, UnicodeError):
            raise HTTPException(422, "Invalid browse cursor.") from None
        if state["snapshot"] != snapshot:
            raise HTTPException(409, "Dataset inventory changed.")
        offset = state["offset"]
    selected = [row for row in rows
                if (class_name is None or row["class_name"] == class_name)
                and (feedback is None or row["is_feedback"] == feedback)]
    if offset > len(selected):
        raise HTTPException(422, "Invalid browse cursor.")
    end = offset + limit
    next_cursor = None
    if end < len(selected):
        state = dict(binding, snapshot=snapshot, offset=end)
        next_cursor = base64.urlsafe_b64encode(json.dumps(state, sort_keys=True).encode()).decode()
    return {"dataset": dataset, "files": selected[offset:end],
            "classes": sorted({row["class_name"] for row in rows}),
            "has_feedback": any(row["is_feedback"] for row in rows),
            "total": len(selected), "snapshot": snapshot, "next_cursor": next_cursor}
