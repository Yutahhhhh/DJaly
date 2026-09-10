#!/usr/bin/env python3
"""Operate the running plumdeck app's durable analysis jobs through its public MCP."""
import argparse
import asyncio
import json
from datetime import datetime

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def call(url, name, arguments):
    async with streamable_http_client(url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(name, arguments)
            if result.is_error:
                raise RuntimeError(result.content[0].text)
            return json.loads(result.content[0].text)


async def watch(url, job_id, interval):
    """Observe an existing job; never start/resume work on connection failures."""
    failures = 0
    while True:
        try:
            job = await call(url, "get_track_analysis_status", {"job_id": job_id})
            failures = 0
        except Exception as exc:
            failures += 1
            print(json.dumps({"time": datetime.now().isoformat(), "connection_error": str(exc), "attempt": failures}), flush=True)
            if failures >= 5:
                raise
        else:
            print(json.dumps({"time": datetime.now().isoformat(), **job}, ensure_ascii=False), flush=True)
            if job["status"] not in ("running", "pausing"):
                return 0 if job["status"] == "completed" else 1
        await asyncio.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["plan", "start", "status", "pause", "resume", "watch"])
    parser.add_argument("--url", default="http://127.0.0.1:48123/mcp")
    parser.add_argument("--job-id")
    parser.add_argument("--track-ids", nargs="+", type=int)
    parser.add_argument("--genres", nargs="+")
    parser.add_argument("--features", nargs="+", choices=["embedding", "rhythm", "key", "timbre", "waveform"])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--workers", type=int)
    parser.add_argument("--force", action="store_true", help="Also recompute current versions")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--interval", type=int, default=60, help="Watch polling interval in seconds (minimum 10)")
    args = parser.parse_args()
    if args.action == "watch":
        if not args.job_id:
            parser.error("--job-id is required for watch")
        if args.interval < 10:
            parser.error("--interval must be at least 10")
        raise SystemExit(asyncio.run(watch(args.url, args.job_id, args.interval)))
    arguments = {}
    if args.action in ("plan", "start"):
        for key in ("track_ids", "genres", "features", "limit"):
            if getattr(args, key) is not None:
                arguments[key] = getattr(args, key)
        arguments["only_outdated"] = not args.force
    if args.action in ("start", "resume") and args.workers is not None:
        arguments["workers"] = args.workers
    if args.action in ("pause", "resume") and not args.job_id:
        parser.error("--job-id is required for pause/resume")
    if args.action in ("status", "pause", "resume") and args.job_id:
        arguments["job_id"] = args.job_id
    if args.action == "resume":
        arguments["retry_failed"] = args.retry_failed
    tool = "get_track_analysis_status" if args.action == "status" else f"{args.action}_track_analysis"
    print(json.dumps(asyncio.run(call(args.url, tool, arguments)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
