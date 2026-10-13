"""Process-wide mode flag.

LIVE is True while the whole-laptop indexer is running, i.e. in the real app. Tests and
the eval harnesses leave it False and keep the original pipeline, so the numbers
recorded in docs/REPORT.md stay reproducible. LIVE only adds behavior that real,
large, messy corpora need (see app/agent/graph.py and app/config.py).
"""

LIVE = False
