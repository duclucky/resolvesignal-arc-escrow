"""Strict normalization: every field is present before any paid work begins."""

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .contracts import Request


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


@dataclass(frozen=True)
class NormalizedRequest:
    request: Request
    canonical_json: str
    input_sha256: str


def normalize_request(payload: dict) -> NormalizedRequest:
    request = Request.model_validate(payload)
    value = request.model_dump(mode="json")
    if request.proposed_action_id is None:
        value.pop("proposed_action_id")
    serialized = canonical(value)
    return NormalizedRequest(
        request=request,
        canonical_json=serialized,
        input_sha256=hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
    )
