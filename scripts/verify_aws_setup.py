#!/usr/bin/env python3
"""
verify_aws_setup.py — sanity-check AWS credentials and Kinesis stream access
before starting the ingestion service.

Usage:
    python scripts/verify_aws_setup.py
    python scripts/verify_aws_setup.py --stream tickwatch-trades-dev --region us-east-1

Exit codes: 0 = all checks passed, 1 = one or more checks failed.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError, NoCredentialsError


def _load_env(path: Path) -> None:
    """Load key=value pairs from a .env file without overwriting existing env vars."""
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


GREEN = "\033[92m"
RED   = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"

_passed = 0
_failed = 0


def ok(msg: str) -> None:
    global _passed
    _passed += 1
    print(f"  {GREEN}✓{RESET}  {msg}")


def fail(msg: str) -> None:
    global _failed
    _failed += 1
    print(f"  {RED}✗{RESET}  {msg}")


def warn(msg: str) -> None:
    print(f"  {YELLOW}!{RESET}  {msg}")


# ---------------------------------------------------------------------------

def check_env_vars() -> None:
    print("\n[1] Environment variables")
    required = ["FINNHUB_API_KEY", "KINESIS_STREAM_NAME", "AWS_REGION"]
    for var in required:
        val = os.getenv(var)
        if val:
            display = val[:6] + "…" if len(val) > 8 else val
            ok(f"{var} = {display}")
        else:
            fail(f"{var} is not set")

    optional = ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_PROFILE"]
    for var in optional:
        val = os.getenv(var)
        if val:
            display = val[:6] + "…" if len(val) > 8 else val
            ok(f"{var} = {display}  (optional)")
        else:
            warn(f"{var} not set — will fall back to instance profile / credential chain")


def check_credentials(session: boto3.Session) -> None:
    print("\n[2] AWS credentials")
    try:
        sts = session.client("sts")
        identity = sts.get_caller_identity()
        ok(f"Account : {identity['Account']}")
        ok(f"ARN     : {identity['Arn']}")
    except NoCredentialsError:
        fail("No AWS credentials found. Set AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY, "
             "configure ~/.aws/credentials, or attach an IAM role.")
    except ClientError as exc:
        fail(f"STS error: {exc}")


def check_kinesis_stream(session: boto3.Session, stream_name: str) -> bool:
    print(f"\n[3] Kinesis stream — '{stream_name}'")
    kinesis = session.client("kinesis")
    try:
        resp = kinesis.describe_stream_summary(StreamName=stream_name)
        summary = resp["StreamDescriptionSummary"]
        status = summary["StreamStatus"]
        shards = summary["OpenShardCount"]
        retention = summary["RetentionPeriodHours"]

        if status == "ACTIVE":
            ok(f"Stream status : ACTIVE")
        else:
            fail(f"Stream status : {status} (expected ACTIVE)")

        ok(f"Open shards   : {shards}")
        ok(f"Retention     : {retention}h")
        return status == "ACTIVE"

    except kinesis.exceptions.ResourceNotFoundException:
        fail(f"Stream '{stream_name}' not found. Run `terraform apply` first.")
        return False
    except ClientError as exc:
        fail(f"Kinesis describe error: {exc}")
        return False


def check_put_permissions(session: boto3.Session, stream_name: str) -> None:
    print(f"\n[4] PutRecords permission test")
    kinesis = session.client("kinesis")
    test_record = {
        "Data": json.dumps({
            "symbol": "_VERIFY_",
            "price": 0.0,
            "volume": 0.0,
            "timestamp_ms": int(time.time() * 1000),
            "trade_conditions": [],
            "ingested_at": int(time.time() * 1000),
        }).encode(),
        "PartitionKey": "_VERIFY_",
    }
    try:
        resp = kinesis.put_records(StreamName=stream_name, Records=[test_record])
        failed = resp.get("FailedRecordCount", 0)
        if failed == 0:
            ok("PutRecords succeeded — ingestion service can write to this stream")
        else:
            result = resp["Records"][0]
            fail(f"PutRecords returned failure: {result.get('ErrorCode')} — {result.get('ErrorMessage')}")
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code == "AccessDeniedException":
            fail("PutRecords denied — IAM policy is missing kinesis:PutRecords permission")
        else:
            fail(f"PutRecords error: {exc}")


# ---------------------------------------------------------------------------

def main() -> None:
    # Load .env before argparse reads os.getenv defaults
    _load_env(Path(__file__).resolve().parents[1] / ".env")

    parser = argparse.ArgumentParser(description="Verify TickWatch AWS setup")
    parser.add_argument(
        "--stream",
        default=os.getenv("KINESIS_STREAM_NAME", "tickwatch-trades-dev"),
        help="Kinesis stream name",
    )
    parser.add_argument(
        "--region",
        default=os.getenv("AWS_REGION", "us-east-1"),
        help="AWS region",
    )
    args = parser.parse_args()

    print("=" * 55)
    print("  TickWatch — AWS setup verification")
    print("=" * 55)

    check_env_vars()
    session = boto3.Session(region_name=args.region)
    check_credentials(session)
    stream_active = check_kinesis_stream(session, args.stream)
    if stream_active:
        check_put_permissions(session, args.stream)

    print("\n" + "=" * 55)
    if _failed == 0:
        print(f"  {GREEN}All {_passed} checks passed — ready to run ingestion service.{RESET}")
        sys.exit(0)
    else:
        print(f"  {RED}{_failed} check(s) failed, {_passed} passed.{RESET}")
        print("  Fix the issues above before starting the service.")
        sys.exit(1)


if __name__ == "__main__":
    main()
