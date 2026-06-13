"""Shared test configuration.

Force offline / quiet model loading so tests use the already-downloaded weights
and don't make network calls or spawn tokenizer threads.
"""

import os

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
