"""
Rule-based, fully deterministic intent classifier for /v1/reply.

Intents (in order of priority when multiple match):
  auto_reply    — canned WA Business auto-reply
  hostile       — explicit frustration / opt-out
  no_decline    — soft no / not interested
  yes_affirm    — positive engagement / yes
  price_objection — cost complaint
  off_topic     — out-of-scope ask
  intent_commit — "let's do it" / "ok proceed"
  curious       — follow-up question
  neutral       — unclassified
"""
from __future__ import annotations
import re
from typing import Tuple


# ──────────────────────────────────────────────
# Pattern tables (ordered: first match wins)
# ──────────────────────────────────────────────

_AUTO_REPLY_PATTERNS = [
    r"thank you for contacting",
    r"our team will respond shortly",
    r"we will get back to you",
    r"automated (reply|response|message)",
    r"out of office",
    r"currently unavailable",
]

_HOSTILE_PATTERNS = [
    r"\bstop\b.*(message|messaging|sending|contact)",
    r"(don'?t|do not).*(message|contact|bother|send)",
    r"\bbother(ing)?\b",
    r"\buseless\b",
    r"\bwaste\b",
    r"\bspam\b",
    r"not (interested|needed|required|useful)",
    r"remove (me|my number)",
    r"block",
    r"report",
    r"\bopt.?out\b",
    r"don'?t (want|need) (this|these|any)",
]

_NO_PATTERNS = [
    r"^no[\.\!\?]?$",
    r"\bnot (right now|now)\b",
    r"\bmaybe later\b",
    r"\bno thanks\b",
    r"\bnot interested\b",
    r"\bnahi\b",      # Hindi
    r"\bnaheen\b",
    r"\bnot at the moment\b",
    r"\bnot today\b",
    r"pass",
]

_YES_PATTERNS = [
    r"^yes[\.\!\?]?$",
    r"^ok[\.\!\?]?$",
    r"^sure[\.\!\?]?$",
    r"^confirm[\.\!\?]?$",
    r"^haan[\.\!\?]?$",     # Hindi
    r"^ha[\.\!\?]?$",
    r"\bplease (send|proceed|do it|go ahead)\b",
    r"\byes please\b",
    r"\bsend (it|the|that)\b",
    r"\bgo ahead\b",
    r"\bsounds good\b",
    r"\blet'?s do (it|this)\b",
    r"\bperfect\b",
    r"\bgreat\b.*\bplease\b",
    r"\^[12]\b",            # reply "1" or "2" for slot selection
    r"^[12]$",
    r"\bconfirm\b",
]

_PRICE_PATTERNS = [
    r"\btoo (expensive|costly|much)\b",
    r"\bprice\b",
    r"\bcost\b",
    r"\bbudget\b",
    r"\bcheap(er)?\b",
    r"\bdiscount\b",
    r"\breduc(e|tion)\b",
    r"\baffordable\b",
    r"\bcan'?t afford\b",
    r"\bexpensive\b",
    r"₹\s*\d+",            # any rupee mention without yes
]

_COMMIT_PATTERNS = [
    r"\blet'?s do (it|this)\b",
    r"\bwhat'?s next\b",
    r"\bproceed\b",
    r"\bgo ahead\b",
    r"\bok,? let'?s\b",
    r"\bready\b",
    r"\bok,?\s+great\b",
]

_OFF_TOPIC_PATTERNS = [
    r"\bgst (filing|return|tax)\b",
    r"\bincome tax\b",
    r"\bca\b",
    r"\bloan\b",
    r"\binsurance\b",
    r"\bjob\b",
    r"\bhiring\b",
    r"\bsocial media (post|management)\b",
    r"\bwebsite\b",
    r"\bseo\b",
    r"\bads (agency|manage)\b",
]


def _match_any(text: str, patterns: list[str]) -> bool:
    t = text.lower().strip()
    return any(re.search(p, t) for p in patterns)


def classify_intent(message: str) -> str:
    """
    Returns one of:
      auto_reply | hostile | no_decline | yes_affirm | price_objection |
      off_topic | intent_commit | curious | neutral
    """
    if _match_any(message, _AUTO_REPLY_PATTERNS):
        return "auto_reply"
    if _match_any(message, _HOSTILE_PATTERNS):
        return "hostile"
    if _match_any(message, _COMMIT_PATTERNS):
        return "intent_commit"
    if _match_any(message, _YES_PATTERNS):
        return "yes_affirm"
    if _match_any(message, _NO_PATTERNS):
        return "no_decline"
    if _match_any(message, _PRICE_PATTERNS):
        return "price_objection"
    if _match_any(message, _OFF_TOPIC_PATTERNS):
        return "off_topic"
    if "?" in message:
        return "curious"
    return "neutral"


# ──────────────────────────────────────────────
# Intent → follow-up strategy
# ──────────────────────────────────────────────

def intent_strategy(intent: str, turn: int, auto_reply_count: int) -> str:
    """
    Return the strategy key for the composition router.
    """
    if intent == "auto_reply":
        if auto_reply_count >= 2:
            return "end_no_engagement"
        return "wait_long"
    if intent == "hostile":
        return "end_hostile"
    if intent == "no_decline":
        return "end_graceful"
    if intent == "intent_commit":
        return "execute_next_action"
    if intent == "yes_affirm":
        return "deliver_artifact"
    if intent == "price_objection":
        return "offer_alternative"
    if intent == "off_topic":
        return "redirect_polite"
    if intent == "curious":
        return "answer_then_cta"
    return "re_engage"
