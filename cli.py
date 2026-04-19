#!/usr/bin/env python3
"""Simple CLI to submit a file for test generation and poll until done."""

import argparse
import sys
import time

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate pytest tests for a Python file.")
    parser.add_argument("file", help="Path to the Python source file")
    parser.add_argument("--coverage", type=float, default=0.8, help="Target coverage (default: 0.8)")
    parser.add_argument("--url", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--out", help="Write generated tests to this file instead of stdout")
    args = parser.parse_args()

    source = open(args.file).read()
    filename = args.file.split("/")[-1]

    print(f"Submitting {filename}...")
    resp = httpx.post(
        f"{args.url}/generate",
        json={"code": source, "filename": filename, "target_coverage": args.coverage},
    )
    resp.raise_for_status()
    job_id = resp.json()["job_id"]
    print(f"Job ID: {job_id}")

    for attempt in range(120):
        time.sleep(2)
        result = httpx.get(f"{args.url}/jobs/{job_id}").json()
        status = result["status"]
        print(f"  [{attempt * 2}s] status: {status}", end="")
        if status in ("success", "failed"):
            print()
            break
        print(f"  (coverage so far: {result.get('coverage', '—')})")
    else:
        print("\nTimed out waiting for result.")
        sys.exit(1)

    if status == "failed":
        print(f"Generation failed: {result.get('error')}")
        sys.exit(1)

    tests = result["generated_tests"]
    coverage = result.get("coverage", 0)
    print(f"Done! Coverage: {coverage:.0%}")

    if args.out:
        open(args.out, "w").write(tests)
        print(f"Tests written to {args.out}")
    else:
        print("\n" + "=" * 60)
        print(tests)


if __name__ == "__main__":
    main()
