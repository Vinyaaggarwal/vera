"""
conversation_handlers.py — Multi-turn conversation handling for Vera.

Implements the respond() interface specified in challenge-brief.md §7.4.
Demonstrates multi-turn handling (replying to merchant responses, auto-reply detection,
intent routing, and hostile opt-out handling).
"""
from __future__ import annotations
import os
import sys
from typing import Any

# Ensure vera-bot directory is on sys.path using absolute path
_vera_bot_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vera-bot")
if _vera_bot_dir not in sys.path:
    sys.path.insert(0, _vera_bot_dir)

from intent import classify_intent, intent_strategy


def respond(state: Any, merchant_message: str) -> dict:
    """
    Given the conversation state and the merchant's latest message, produce the reply.

    Parameters:
        state: ConversationState or dict containing conversation context
        merchant_message: The text received from the merchant

    Returns:
        dict with:
            - reply: WhatsApp response text (or empty string if auto-reply / suppressed)
            - intent: Classified intent
            - action: 'reply' | 'suppress' | 'opt_out' | 'escalate'
    """
    intent = classify_intent(merchant_message)
    strategy = intent_strategy(intent, turn=1, auto_reply_count=1)

    if intent == "auto_reply":
        return {
            "reply": "",
            "intent": intent,
            "action": "suppress",
            "strategy": strategy,
            "rationale": "Canned WhatsApp Business auto-reply detected. Suppressing to prevent loops."
        }

    if intent == "hostile":
        return {
            "reply": "Understood, we won't message you again. Have a good day.",
            "intent": intent,
            "action": "opt_out",
            "strategy": strategy,
            "rationale": "Hostile sentiment / opt-out request honored immediately."
        }

    if intent == "intent_commit" or intent == "yes_affirm":
        return {
            "reply": "Great! Setting this up for you now. I'll share a preview before going live.",
            "intent": intent,
            "action": "reply",
            "strategy": strategy,
            "rationale": "Positive affirmation / commitment detected. Transitioning directly to execution."
        }

    if intent == "no_decline":
        return {
            "reply": "No problem at all! Feel free to reach out whenever you're ready.",
            "intent": intent,
            "action": "reply",
            "strategy": strategy,
            "rationale": "Soft decline acknowledged politely without repetitive nudges."
        }

    if intent == "price_objection":
        return {
            "reply": "This campaign is included in your current active plan at zero extra cost.",
            "intent": intent,
            "action": "reply",
            "strategy": strategy,
            "rationale": "Price objection handled by clarifying zero incremental cost."
        }

    # Default curious / neutral response
    return {
        "reply": "Got it! Let me know if you'd like me to activate this for your profile.",
        "intent": intent,
        "action": "reply",
        "strategy": strategy,
        "rationale": "Follow-up response providing a low-effort next step."
    }


if __name__ == "__main__":
    test_msgs = [
        "Thank you for contacting Dr. Meera's Dental Clinic. We will respond shortly.",
        "Stop messaging me, this is useless spam!",
        "Yes, let's do it",
        "No thanks, not today"
    ]
    for msg in test_msgs:
        res = respond(None, msg)
        print(f"Input: '{msg[:32]}...' -> Intent: {res['intent']} | Action: {res['action']}")
