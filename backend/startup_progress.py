"""Structured startup milestones readable before the HTTP server is ready."""
import json


def report(stage, label, completed):
    print("PLUMDECK_STARTUP:" + json.dumps({
        "stage": stage, "label": label, "completed": completed, "total": 5,
    }, ensure_ascii=False), flush=True)
