"""
Pydantic schemas — exactly matching api-call-examples.md shapes.
"""
from __future__ import annotations
from typing import Any, List, Optional
from pydantic import BaseModel, field_validator
import datetime


# ──────────────────────────────────────────────
# Shared
# ──────────────────────────────────────────────

class ContextRequest(BaseModel):
    scope: str          # "merchant" | "customer" | "category" | "trigger"
    context_id: str
    version: int
    delivered_at: str   # ISO8601
    payload: dict[str, Any]


class ContextResponse(BaseModel):
    accepted: bool
    ack_id: Optional[str] = None
    stored_at: Optional[str] = None
    reason: Optional[str] = None
    current_version: Optional[int] = None


# ──────────────────────────────────────────────
# /v1/tick
# ──────────────────────────────────────────────

class TickRequest(BaseModel):
    now: str                        # ISO8601 simulated-now
    available_triggers: List[str]   # list of trigger context_ids


class TickAction(BaseModel):
    conversation_id: str
    merchant_id: str
    customer_id: Optional[str] = None
    send_as: str                    # "vera" | "merchant_on_behalf"
    trigger_id: str
    template_name: str
    template_params: List[str]
    body: str
    cta: str                        # "open_ended" | "binary_yes_no" | "binary_confirm_cancel" | "multi_choice_slot" | "none"
    suppression_key: str
    rationale: str


class TickResponse(BaseModel):
    actions: List[TickAction] = []


# ──────────────────────────────────────────────
# /v1/reply
# ──────────────────────────────────────────────

class ReplyRequest(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: str          # "merchant" | "customer"
    message: str
    received_at: Optional[str] = None
    turn_number: int = 2


class ReplyResponse(BaseModel):
    action: str             # "send" | "wait" | "end"
    body: Optional[str] = None
    cta: Optional[str] = None
    wait_seconds: Optional[int] = None
    rationale: str
    suppression_key: Optional[str] = None
    template_name: Optional[str] = None
    template_params: Optional[List[str]] = None


# ──────────────────────────────────────────────
# /v1/healthz
# ──────────────────────────────────────────────

class HealthzResponse(BaseModel):
    status: str = "ok"
    uptime_seconds: int
    contexts_loaded: dict[str, int]


# ──────────────────────────────────────────────
# /v1/metadata
# ──────────────────────────────────────────────

class MetadataResponse(BaseModel):
    team_name: str
    model: str
    approach: str
    version: str
    submitted_at: str
    supported_categories: List[str]
    endpoints: List[str]
