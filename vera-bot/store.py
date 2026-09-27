"""
In-memory context store with version idempotency.
Thread-safe via a simple lock (single-process uvicorn workers).

Keys: (scope, context_id) → {"version": int, "payload": dict, "stored_at": str}
"""
from __future__ import annotations
import threading
import datetime
from typing import Any, Dict, Optional, Tuple


_lock = threading.Lock()

# Main context store: (scope, context_id) → {version, payload, stored_at}
_store: Dict[Tuple[str, str], Dict[str, Any]] = {}

# Sent-messages suppression log: suppression_key → conversation_id
_sent_log: Dict[str, str] = {}

# Conversation-level state: conversation_id → {"merchant_id", "turn", "trigger_id", "suppression_key", "ended", "auto_reply_count"}
_conv_state: Dict[str, Dict[str, Any]] = {}

# Merchant-level suppression overrides (hostile opt-out): merchant_id → suppress_until ISO
_merchant_suppress: Dict[str, str] = {}


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def clear_all() -> None:
    with _lock:
        _store.clear()
        _sent_log.clear()
        _conv_state.clear()
        _merchant_suppress.clear()
        _merchant_auto_reply.clear()


def clear_suppressions() -> None:
    with _lock:
        _sent_log.clear()
        _merchant_suppress.clear()
        _merchant_auto_reply.clear()


# ──────────────────────────────────────────────
# Context CRUD
# ──────────────────────────────────────────────

def store_context(scope: str, context_id: str, version: int, payload: dict) -> Tuple[bool, Optional[int]]:
    """
    Returns (accepted: bool, current_version: int | None).
    accepted=False means incoming version < stored version (stale).
    Re-posting the same version is an idempotent no-op (accepted=True).
    """
    key = (scope, context_id)
    with _lock:
        existing = _store.get(key)
        if existing and existing["version"] > version:
            return False, existing["version"]
        _store[key] = {
            "version": version,
            "payload": payload,
            "stored_at": _now_iso(),
        }
        if scope == "merchant":
            _merchant_suppress.pop(context_id, None)
            _merchant_auto_reply.pop(context_id, None)
        return True, None


def get_context(scope: str, context_id: str) -> Optional[Dict[str, Any]]:
    key = (scope, context_id)
    with _lock:
        return _store.get(key)


def get_all_by_scope(scope: str) -> Dict[str, Dict[str, Any]]:
    """Return {context_id: stored_record} for a given scope."""
    with _lock:
        return {
            cid: rec
            for (sc, cid), rec in _store.items()
            if sc == scope
        }


def context_counts() -> Dict[str, int]:
    with _lock:
        counts: Dict[str, int] = {}
        for (scope, _) in _store:
            counts[scope] = counts.get(scope, 0) + 1
        return counts


# ──────────────────────────────────────────────
# Suppression log
# ──────────────────────────────────────────────

def is_suppressed(suppression_key: str) -> bool:
    with _lock:
        return suppression_key in _sent_log


def mark_sent(suppression_key: str, conversation_id: str) -> None:
    with _lock:
        _sent_log[suppression_key] = conversation_id


def clear_suppression(suppression_key: str) -> None:
    """Called when a newer context version supersedes a trigger."""
    with _lock:
        _sent_log.pop(suppression_key, None)


# ──────────────────────────────────────────────
# Conversation state
# ──────────────────────────────────────────────

def get_conv(conv_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        return _conv_state.get(conv_id)


def upsert_conv(conv_id: str, **kwargs) -> None:
    with _lock:
        state = _conv_state.setdefault(conv_id, {"turn": 1, "auto_reply_count": 0})
        state.update(kwargs)


def end_conv(conv_id: str) -> None:
    with _lock:
        state = _conv_state.setdefault(conv_id, {})
        state["ended"] = True


def is_conv_ended(conv_id: str) -> bool:
    with _lock:
        return _conv_state.get(conv_id, {}).get("ended", False)


_merchant_auto_reply: Dict[str, int] = {}


def increment_auto_reply(conv_id: str, merchant_id: Optional[str] = None) -> int:
    """Return the new auto_reply_count after incrementing."""
    with _lock:
        state = _conv_state.setdefault(conv_id, {"auto_reply_count": 0})
        state["auto_reply_count"] = state.get("auto_reply_count", 0) + 1
        c_cnt = state["auto_reply_count"]
        if merchant_id:
            m_cnt = _merchant_auto_reply.get(merchant_id, 0) + 1
            _merchant_auto_reply[merchant_id] = m_cnt
            return max(c_cnt, m_cnt)
        return c_cnt


# ──────────────────────────────────────────────
# Merchant-level suppression (hostile opt-out)
# ──────────────────────────────────────────────

def suppress_merchant(merchant_id: str, days: int = 30) -> None:
    import datetime
    until = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days)).isoformat()
    with _lock:
        _merchant_suppress[merchant_id] = until


def is_merchant_suppressed(merchant_id: str) -> bool:
    import datetime
    with _lock:
        until = _merchant_suppress.get(merchant_id)
        if until is None:
            return False
        return datetime.datetime.now(datetime.timezone.utc) < datetime.datetime.fromisoformat(until)


def unsuppress_merchant(merchant_id: str) -> None:
    with _lock:
        _merchant_suppress.pop(merchant_id, None)
