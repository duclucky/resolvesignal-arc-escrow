"""Command-line interface for deterministic integrations."""

import argparse
import json
from pathlib import Path

from .client import CircleCliPayment, ResolveSignalClient, build_request, validate_request


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if path:
        Path(path).write_text(text, encoding="utf-8")
    else:
        print(text, end="")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="resolvesignal")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("build", "validate"):
        command = sub.add_parser(name)
        command.add_argument("--profile", required=True)
        command.add_argument("--runtime", required=True)
        command.add_argument("--output")
    check = sub.add_parser("check")
    check.add_argument("--base-url", default="https://resolvesignal.com")
    call = sub.add_parser("call")
    call.add_argument("--base-url", default="https://resolvesignal.com")
    call.add_argument("--profile", required=True)
    call.add_argument("--runtime", required=True)
    call.add_argument("--payer", required=True)
    call.add_argument("--max-fee", required=True)
    call.add_argument("--recovery", required=True)
    call.add_argument("--confirm-paid-call", action="store_true")
    reconcile = sub.add_parser("reconcile")
    reconcile.add_argument("--base-url", default="https://resolvesignal.com")
    reconcile.add_argument("--recovery", required=True)
    args = parser.parse_args(argv)

    if args.command in {"build", "validate"}:
        request = build_request(read(args.profile), read(args.runtime))
        if args.command == "validate":
            validate_request(request)
            value = {"valid": True, "schema_version": "2.1"}
        else:
            value = request
        write(args.output, value)
        return 0

    payment = CircleCliPayment()
    with ResolveSignalClient(args.base_url, payment) as client:
        if args.command == "check":
            status = client.check()
            write(None, {"ready": True, "health": status["health"]["status"]})
        elif args.command == "call":
            request = build_request(read(args.profile), read(args.runtime))
            result = client.call(
                request,
                payer=args.payer,
                max_fee_usdc=args.max_fee,
                recovery_path=Path(args.recovery),
                confirm_paid_call=args.confirm_paid_call,
            )
            write(None, result)
        else:
            write(None, client.reconcile(Path(args.recovery)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
