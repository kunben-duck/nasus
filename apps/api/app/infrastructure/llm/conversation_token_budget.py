"""Counting and model-specific budgets; estimates are explicitly labelled."""
import json
import os

from ...domain.agent.conversation_memory import ContextBudget


class ConversationTokenCounter:
    def __init__(self, model_name="", provider=""):
        self.encoding = None
        self.kind = "utf8_bytes_upper_estimate"
        if provider in {"openai", "openai_compatible"}:
            try:
                import tiktoken
                self.encoding = tiktoken.encoding_for_model(model_name)
                self.kind = "tiktoken:" + self.encoding.name
            except (KeyError, ImportError):
                pass

    def count(self, text):
        if self.encoding is not None:
            return len(self.encoding.encode(text, disallowed_special=()))
        return len(text.encode("utf-8"))


def memory_enabled():
    return os.getenv("NASUS_CONVERSATION_MEMORY_V2", "false").lower() in {"1", "true", "yes"}


def model_budget(settings):
    overrides = json.loads(os.getenv("NASUS_MEMORY_MODEL_BUDGETS", "{}"))
    entry = overrides.get(settings.model_name, {})
    limit = int(entry.get("input_limit", os.getenv("NASUS_MEMORY_INPUT_TOKENS", "16384")))
    if entry.get("context_window"):
        limit = min(limit, int(entry["context_window"]) - max(summary_output_limit(settings), int(entry.get("output_reserve", 4096)))
                    - int(entry.get("safety_reserve", 1024)))
    if limit < 1024:
        raise ValueError("conversation input budget must be at least 1024")
    return ContextBudget(input_limit=limit)


def summary_output_limit(settings):
    entry = json.loads(os.getenv("NASUS_MEMORY_MODEL_BUDGETS", "{}")).get(settings.model_name, {})
    limit = int(entry.get("summary_output_tokens", 4096))
    if not 512 <= limit <= 16384:
        raise ValueError("summary output budget must be between 512 and 16384")
    return limit

