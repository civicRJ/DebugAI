"""Shared test configuration.

Force offline / quiet model loading so tests use the already-downloaded weights
and don't make network calls or spawn tokenizer threads.
"""

import os

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
# Disable the auth rate limiter in tests: all requests come from 127.0.0.1,
# so the per-IP counter would accumulate across tests and cause false 429s.
os.environ.setdefault("DEBUGAI_AUTH_RATE_LIMIT", "0")
