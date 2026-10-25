"""Minimal SSE reader for BEAMTEAM event streams."""
import json

def read(path):
    out = []
    for line in open(path):
        if line.startswith("data: "):
            try:
                out.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return out
