"""Offline pipeline orchestration."""

PIPELINE_VERSION = "offline-pipeline-v1"
STAGES = ("import", "normalize", "deterministic_match", "fuzzy_match", "review_queue", "materialize")
