"""
Automated validation matching judge_simulator.py scenarios:
1. Warmup & Metadata
2. Auto-reply detection
3. Intent transition
4. Hostile message handling
5. Tick message generation across categories
"""
import pytest
import json
import urllib.request
import urllib.error

BASE_URL = "http://localhost:8000"


def _post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(path: str) -> dict:
    with urllib.request.urlopen(f"{BASE_URL}{path}", timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def test_judge_warmup():
    health = _get("/v1/healthz")
    assert health.get("status") == "ok"
    assert health.get("contexts_loaded", {}).get("merchant", 0) >= 10

    meta = _get("/v1/metadata")
    assert meta.get("team_name")
    assert "POST /v1/tick" in meta.get("endpoints", [])


def test_judge_auto_reply_detection():
    # Sending auto-reply messages
    auto_msg = "Thank you for contacting us! Our team will respond shortly."
    ended = False
    for i in range(1, 5):
        payload = {
            "conversation_id": f"conv_auto_{i}",
            "merchant_id": "m_001_drmeera_dentist_delhi",
            "customer_id": None,
            "from_role": "merchant",
            "message": auto_msg,
            "turn_number": i + 1,
        }
        res = _post("/v1/reply", payload)
        action = res.get("action")
        if action == "end":
            ended = True
            break
        elif action == "wait":
            assert res.get("wait_seconds", 0) > 0

    assert ended, "Bot should have ended the conversation on repeated auto-replies"


def test_judge_intent_transition():
    commitment = "Ok lets do it. Whats next?"
    payload = {
        "conversation_id": "conv_intent_1",
        "merchant_id": "m_002_bharat_dentist_mumbai",
        "customer_id": None,
        "from_role": "merchant",
        "message": commitment,
        "turn_number": 2,
    }
    res = _post("/v1/reply", payload)
    assert res.get("action") == "send"
    body = (res.get("body") or "").lower()

    actioning = ["done", "sending", "draft", "here", "confirm", "proceed", "next"]
    qualifying = ["would you", "do you", "can you tell", "what if", "how about"]

    assert any(w in body for w in actioning), f"Expected actioning words in '{body}'"
    assert not any(w in body for w in qualifying), f"Should not qualify further after commitment in '{body}'"


def test_judge_hostile_handling():
    hostile = "Stop messaging me. This is useless spam."
    payload = {
        "conversation_id": "conv_hostile_1",
        "merchant_id": "m_010_sunrisepharm_pharmacy_lucknow",
        "customer_id": None,
        "from_role": "merchant",
        "message": hostile,
        "turn_number": 2,
    }
    res = _post("/v1/reply", payload)
    action = res.get("action")
    body = (res.get("body") or "").lower()

    # Either ends cleanly or apologizes gracefully
    assert action == "end" or (action == "send" and any(w in body for w in ["sorry", "apolog", "won't"]))
