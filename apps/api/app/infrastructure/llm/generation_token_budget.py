import hashlib
import importlib.metadata
import json
import os
from pathlib import Path

from ...application.quality_loop.generation_budget import GenerationModelPolicy, GenerationBudgetInvalid
from ...domain.quality_loop.acceptance_specification import acceptance_digest


class LocalGenerationTokenCounter:
    def __init__(self, policy, encode):
        self.policy, self._encode = policy, encode

    def count(self, system, content):
        return len(self._encode(system)) + len(self._encode(content)) + self.policy.framing_tokens


class ConfiguredGenerationModelPolicies:
    """Read administrator-owned configuration, never paths/rates supplied by a model or HTTP caller."""

    def __init__(self, path=None):
        self.path = path

    def resolve(self, binding):
        path = self.path or os.getenv("NASUS_GENERATION_MODEL_POLICIES")
        if not path:
            raise GenerationBudgetInvalid("generation model token/pricing policy is not configured")
        try:
            config_path = Path(path).resolve(strict=True)
            if config_path.stat().st_size > 128 * 1024:
                raise ValueError("policy file too large")
            config = json.loads(config_path.read_text())
            if not isinstance(config, dict) or set(config) != {"schema", "profiles"} or config["schema"] != "nasus.generation-model-policies.v1":
                raise ValueError("invalid policy document")
            profiles = config["profiles"]
            if not isinstance(profiles, list) or not 1 <= len(profiles) <= 64:
                raise ValueError("invalid profile list")
            matches = [entry for entry in profiles if entry.get("policy", {}).get("config_id") == binding.config_id]
            if len(matches) != 1:
                raise ValueError("model needs exactly one operator profile")
            entry = matches[0]
            if set(entry) - {"policy", "tokenizer_path"}:
                raise ValueError("unknown profile fields")
            policy = GenerationModelPolicy.model_validate(entry["policy"])
            if any(getattr(policy, key) != getattr(binding, key) for key in ("config_id", "provider", "model_name", "base_url")):
                raise ValueError("profile belongs to another model/destination")
            if policy.tokenizer_kind == "tiktoken":
                import tiktoken
                if importlib.metadata.version("tiktoken") != "0.8.0" or "tokenizer_path" in entry:
                    raise ValueError("tokenizer implementation changed")
                # Encoding assets are static tokenizer data, not repository data.
                # No remote model is called and no source text is uploaded.
                encoding = tiktoken.get_encoding(policy.tokenizer_id)
                if policy.tokenizer_digest != tiktoken_policy_digest(policy.tokenizer_id):
                    raise ValueError("tokenizer policy pin mismatch")
                return LocalGenerationTokenCounter(policy, lambda text: encoding.encode(text, disallowed_special=()))
            from tokenizers import Tokenizer
            if importlib.metadata.version("tokenizers") != "0.21.4":
                raise ValueError("tokenizer implementation changed")
            tokenizer_path = (config_path.parent / entry["tokenizer_path"]).resolve(strict=True)
            if tokenizer_path.stat().st_size > 32 * 1024 * 1024:
                raise ValueError("tokenizer asset too large")
            body = tokenizer_path.read_bytes()
            if "sha256:" + hashlib.sha256(body).hexdigest() != policy.tokenizer_digest:
                raise ValueError("tokenizer artifact changed")
            tokenizer = Tokenizer.from_str(body.decode())
            tokenizer.no_truncation()
            tokenizer.no_padding()
            return LocalGenerationTokenCounter(policy, lambda text: tokenizer.encode(text, add_special_tokens=False).ids)
        except GenerationBudgetInvalid:
            raise
        except Exception:
            raise GenerationBudgetInvalid("generation model policy/tokenizer cannot be verified; contact the administrator") from None


def tiktoken_policy_digest(encoding):
    import tiktoken
    tokenizer = tiktoken.get_encoding(encoding)
    ranks = hashlib.sha256()
    for value, rank in sorted(tokenizer._mergeable_ranks.items(), key=lambda item: item[1]):
        ranks.update(len(value).to_bytes(4, "big") + value + rank.to_bytes(4, "big"))
    return acceptance_digest({"library": "tiktoken", "version": "0.8.0", "encoding": encoding,
        "mergeable_ranks_digest": ranks.hexdigest(), "special_tokens": "ordinary_text"})
