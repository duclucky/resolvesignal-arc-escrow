"""Single-shot ResolveSignal integration with an injectable x402 payment adapter."""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
import shutil
import subprocess
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx
from jsonschema import Draft202012Validator, FormatChecker

PROFILE_FIELDS = frozenset(
    {"objective", "policy", "capabilities", "locale"}
)
RUNTIME_FIELDS = frozenset(
    {"current_state", "observations", "facts", "previous_attempts", "observed_at"}
)
REQUEST_FIELDS = PROFILE_FIELDS | RUNTIME_FIELDS
OPTIONAL_RUNTIME_FIELDS = frozenset({"proposed_action_id"})
NETWORK = "eip155:5042"
USDC = "0x3600000000000000000000000000000000000000"
ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
HASH = re.compile(r"^[0-9a-f]{64}$")


class IntegrationError(RuntimeError):
    """Stable local error code; no automatic paid retry is performed."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(code + (f": {detail}" if detail else ""))


class PaymentAdapter(Protocol):
    def sign_typed_data(self, typed_data: dict[str, Any], payer: str) -> str: ...

    def inspect(self, url: str, request_key: str, input_hash: str) -> dict[str, Any]: ...

    def pay(
        self,
        url: str,
        request_key: str,
        input_hash: str,
        payer: str,
        max_fee_usdc: str,
    ) -> dict[str, Any]: ...


def _load_schema(name: str) -> dict[str, Any]:
    path = Path(__file__).with_name("schemas") / name
    return json.loads(path.read_text(encoding="utf-8"))


def _exact_fields(value: dict[str, Any], expected: frozenset[str], code: str,
                  optional: frozenset[str] = frozenset()) -> None:
    if not isinstance(value, dict) or not expected <= set(value) or set(value) - expected - optional:
        missing = sorted(expected - set(value)) if isinstance(value, dict) else sorted(expected)
        extra = sorted(set(value) - expected - optional) if isinstance(value, dict) else []
        raise IntegrationError(code, f"missing={missing}; extra={extra}")


def build_request(profile: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    """Merge immutable integration policy with current runtime evidence."""

    _exact_fields(profile, PROFILE_FIELDS, "profile_fields_invalid")
    _exact_fields(runtime, RUNTIME_FIELDS, "runtime_fields_invalid", OPTIONAL_RUNTIME_FIELDS)
    request = {**profile, **runtime}
    validate_request(request)
    return request


def validate_request(request: dict[str, Any], schema: dict[str, Any] | None = None) -> None:
    """Validate locally. The live payer challenge remains the authoritative gate."""

    _exact_fields(request, REQUEST_FIELDS, "request_fields_invalid", OPTIONAL_RUNTIME_FIELDS)
    validator = Draft202012Validator(
        schema or _load_schema("request-schema.json"), format_checker=FormatChecker()
    )
    errors = sorted(validator.iter_errors(request), key=lambda item: list(item.path))
    if errors:
        error = errors[0]
        path = ".".join(str(part) for part in error.absolute_path) or "$"
        raise IntegrationError("request_schema_invalid", f"{path}: {error.message}")
    if _contains_blank(request):
        raise IntegrationError("request_blank_value")
    proposal = request.get("proposed_action_id")
    actions = request.get("capabilities")
    action_ids = {action["id"] for action in actions} if isinstance(actions, list) else set()
    if proposal is not None and proposal not in action_ids:
        raise IntegrationError("proposed_action_reference_invalid")
    _observed_timestamp(request.get("observed_at"))


def _observed_timestamp(value: Any) -> float:
    if not isinstance(value, str):
        raise IntegrationError("observed_at_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise IntegrationError("observed_at_invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise IntegrationError("observed_at_timezone_required")
    return parsed.timestamp()


def _contains_blank(value: Any) -> bool:
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return any(_contains_blank(item) for item in value)
    if isinstance(value, dict):
        return any(not str(key).strip() or _contains_blank(item) for key, item in value.items())
    return False


def _origin(value: str) -> str:
    parsed = urlsplit(value)
    local = parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    if (
        not (parsed.scheme == "https" or local)
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise IntegrationError("unsafe_origin")
    return value.rstrip("/")


def _json(response: httpx.Response, expected: set[int]) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError as error:
        raise IntegrationError("response_not_json", str(response.status_code)) from error
    if response.status_code not in expected or not isinstance(body, dict):
        raise IntegrationError("unexpected_http_status", str(response.status_code))
    return body


def _write_private_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".new")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    os.replace(temporary, path)


class ResolveSignalClient:
    """Synchronous reference client. One call invokes the payment adapter at most once."""

    def __init__(
        self,
        base_url: str,
        payment: PaymentAdapter,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 180,
    ):
        self.base_url = _origin(base_url)
        self.payment = payment
        self.http = httpx.Client(
            base_url=self.base_url,
            timeout=timeout_seconds,
            transport=transport,
            headers={"User-Agent": "ResolveSignalIntegration/0.1"},
        )

    def close(self) -> None:
        self.http.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def check(self) -> dict[str, Any]:
        health = _json(self.http.get("/health"), {200})
        form = _json(self.http.get("/v2/form"), {200})
        if health.get("status") != "ok":
            raise IntegrationError("service_unhealthy")
        if (
            form.get("mode") != "live"
            or str(form.get("protocol_version")) != "2"
            or form.get("payment_metadata", {}).get("backend") != "escrow_v3"
            or form.get("payment_metadata", {}).get("payer_control_proof_required") is not True
        ):
            raise IntegrationError("live_contract_mismatch")
        return {"health": health, "form": form}

    def call(
        self,
        request: dict[str, Any],
        *,
        payer: str,
        max_fee_usdc: str,
        recovery_path: Path,
        confirm_paid_call: bool = False,
    ) -> dict[str, Any]:
        if not confirm_paid_call:
            raise IntegrationError("paid_call_not_confirmed")
        if not ADDRESS.fullmatch(payer):
            raise IntegrationError("payer_invalid")
        try:
            fee_cap = Decimal(max_fee_usdc)
        except InvalidOperation as error:
            raise IntegrationError("fee_cap_invalid") from error
        if fee_cap <= 0:
            raise IntegrationError("fee_cap_invalid")

        readiness = self.check()
        live_schema = readiness["form"].get("request_schema")
        validate_request(request, live_schema if isinstance(live_schema, dict) else None)
        max_age = readiness["form"].get("max_state_age_seconds")
        if isinstance(max_age, (int, float)) and time.time() - _observed_timestamp(request["observed_at"]) > max_age:
            raise IntegrationError("runtime_evidence_stale")
        request_key = secrets.token_urlsafe(32)
        idempotency_key = secrets.token_urlsafe(24)
        headers = {
            "X-Request-Key": request_key,
            "Idempotency-Key": idempotency_key,
            "X-Payer-Address": payer,
        }
        challenge = _json(
            self.http.post("/v2/payer-challenge", json=request, headers=headers), {200}
        )
        typed = challenge.get("typed_data")
        if not isinstance(typed, dict):
            raise IntegrationError("challenge_invalid")
        message = typed.get("message", {})
        if (
            typed.get("domain", {}).get("chainId") != 5042
            or typed.get("primaryType") != "QuoteAdmission"
            or str(message.get("payer", "")).lower() != payer.lower()
            or message.get("purpose") != "quote_admission_only_no_payment"
        ):
            raise IntegrationError("challenge_scope_invalid")
        signature = self.payment.sign_typed_data(typed, payer)
        if not re.fullmatch(r"0x(?:[0-9a-fA-F]{2}){1,8192}", signature):
            raise IntegrationError("challenge_signature_invalid")
        proof = base64.b64encode(
            json.dumps(
                {
                    "typed_data": typed,
                    "challenge_token": challenge.get("challenge_token"),
                    "signature": signature,
                },
                separators=(",", ":"),
            ).encode()
        ).decode()
        quote = _json(
            self.http.post(
                "/v2/requests", json=request, headers=headers | {"X-Payer-Proof": proof}
            ),
            {402},
        )
        requirement = self._validate_quote(quote, payer, fee_cap)
        call_id, input_hash = quote.get("call_id"), quote.get("input_hash")
        pay_url = f"{self.base_url}/v2/requests/{call_id}/pay"
        resource = requirement.get("resource")
        if resource is not None and resource != pay_url:
            raise IntegrationError("quote_resource_invalid")
        recovery = {
            "version": 1,
            "base_url": self.base_url,
            "call_id": call_id,
            "input_hash": input_hash,
            "request_key": request_key,
            "idempotency_key": idempotency_key,
            "payer": payer,
            "vault": requirement["payTo"],
            "amount_atomic": requirement["amount"],
            "network": NETWORK,
            "quote_until": quote.get("quote_until"),
            "payment_attempted": False,
        }
        _write_private_json(recovery_path, recovery)
        inspected = self.payment.inspect(pay_url, request_key, input_hash)
        if inspected.get("status") != "payable":
            raise IntegrationError("payment_not_payable")

        recovery["payment_attempted"] = True
        _write_private_json(recovery_path, recovery)
        try:
            paid = self.payment.pay(
                pay_url, request_key, input_hash, payer, format(fee_cap, "f")
            )
        except Exception as error:
            recovery["last_error"] = getattr(error, "code", type(error).__name__)
            _write_private_json(recovery_path, recovery)
            raise
        response = paid.get("data", {}).get("response")
        if (
            not isinstance(response, dict)
            or response.get("call_id") != call_id
            or response.get("input_hash") != input_hash
            or response.get("result_available") is not True
            or not isinstance(response.get("result"), dict)
        ):
            raise IntegrationError("paid_response_invalid")
        recovery["paid_response_received"] = True
        financial = self.reconcile(recovery)
        recovery["financial_status"] = financial
        _write_private_json(recovery_path, recovery)
        return response

    def reconcile(self, state: dict[str, Any] | Path) -> dict[str, Any]:
        if isinstance(state, (str, Path)):
            state = json.loads(Path(state).read_text(encoding="utf-8"))
        call_id, request_key = state.get("call_id"), state.get("request_key")
        if not isinstance(call_id, str) or not isinstance(request_key, str):
            raise IntegrationError("recovery_state_invalid")
        return _json(
            self.http.get(
                f"/v2/requests/{call_id}", headers={"X-Request-Key": request_key}
            ),
            {200, 402, 410, 424},
        )

    def _validate_quote(
        self, quote: dict[str, Any], payer: str, fee_cap: Decimal
    ) -> dict[str, Any]:
        del payer  # payer is already bound by the challenge and server quote.
        if quote.get("payment_allowed") is not True:
            raise IntegrationError("payment_not_allowed")
        accepts = quote.get("payment_required", {}).get("accepts", [])
        if not isinstance(accepts, list) or len(accepts) != 1:
            raise IntegrationError("quote_invalid")
        item = accepts[0]
        call_id, input_hash = quote.get("call_id"), quote.get("input_hash")
        quote_until = quote.get("quote_until")
        if (
            item.get("scheme") != "exact"
            or item.get("network") != NETWORK
            or str(item.get("asset", "")).lower() != USDC
            or not ADDRESS.fullmatch(str(item.get("payTo", "")))
            or not isinstance(call_id, str)
            or not re.fullmatch(r"call_[0-9A-Za-z_-]+", call_id)
            or not isinstance(input_hash, str)
            or not HASH.fullmatch(input_hash)
            or not isinstance(quote_until, (int, float))
            or quote_until <= time.time()
        ):
            raise IntegrationError("quote_invalid")
        try:
            amount_atomic = int(item["amount"])
        except (KeyError, TypeError, ValueError) as error:
            raise IntegrationError("quote_invalid") from error
        if amount_atomic <= 0:
            raise IntegrationError("quote_invalid")
        if Decimal(amount_atomic) / Decimal(1_000_000) > fee_cap:
            raise IntegrationError("fee_cap_exceeded")
        return item


class CircleCliPayment:
    """Circle Agent Wallet adapter using argv-only subprocesses and no shell."""

    def __init__(self, executable: str = "circle", timeout_seconds: int = 150):
        self.executable = executable
        self.timeout_seconds = timeout_seconds

    def _command(self) -> list[str]:
        path = shutil.which(self.executable)
        if not path:
            raise IntegrationError("circle_cli_not_found")
        if os.name == "nt":
            entry = Path(path).parent / "node_modules/@circle-fin/cli/dist/index.js"
            node = shutil.which("node")
            if not node or not entry.is_file():
                raise IntegrationError("circle_cli_runtime_unavailable")
            return [node, str(entry)]
        return [path]

    def _run(self, args: list[str]) -> dict[str, Any]:
        completed = subprocess.run(
            [*self._command(), *args, "--output", "json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=self.timeout_seconds,
            check=False,
        )
        try:
            value = json.loads(completed.stdout)
        except ValueError as error:
            raise IntegrationError("circle_response_invalid") from error
        if completed.returncode or not isinstance(value, dict) or "error" in value:
            code = value.get("error", {}).get("code", "operation_failed") if isinstance(value, dict) else "operation_failed"
            raise IntegrationError("circle_" + str(code).lower())
        return value

    def sign_typed_data(self, typed_data: dict[str, Any], payer: str) -> str:
        value = self._run(
            [
                "wallet",
                "sign",
                "typed-data",
                json.dumps(typed_data, separators=(",", ":")),
                "--address",
                payer,
                "--chain",
                "ARC",
            ]
        )
        data = value.get("data", value)
        signature = data.get("signature") if isinstance(data, dict) else None
        if not isinstance(signature, str):
            raise IntegrationError("circle_signature_invalid")
        return signature

    @staticmethod
    def _common(url: str, request_key: str, input_hash: str) -> list[str]:
        return [
            url,
            "-X",
            "POST",
            "--data",
            json.dumps({"input_hash": input_hash}, separators=(",", ":")),
            "-H",
            "X-Request-Key: " + request_key,
        ]

    def inspect(self, url: str, request_key: str, input_hash: str) -> dict[str, Any]:
        value = self._run(["services", "inspect", *self._common(url, request_key, input_hash)])
        data = value.get("data", value)
        if not isinstance(data, dict):
            raise IntegrationError("circle_response_invalid")
        return data

    def pay(
        self,
        url: str,
        request_key: str,
        input_hash: str,
        payer: str,
        max_fee_usdc: str,
    ) -> dict[str, Any]:
        return self._run(
            [
                "services",
                "pay",
                *self._common(url, request_key, input_hash),
                "--address",
                payer,
                "--chain",
                "ARC",
                "--max-amount",
                max_fee_usdc,
                "--timeout",
                "120",
            ]
        )
