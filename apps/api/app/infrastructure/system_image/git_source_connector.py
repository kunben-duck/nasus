from __future__ import annotations

import fcntl
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Mapping, Sequence
from urllib.parse import SplitResult, urlsplit, urlunsplit

from ...application.system_image.source_ports import (
    MaterializedSource,
    SourceCredentialResolver,
)
from ...application.system_image.system_image_models import RawAssetRecord


class GitSourceConnectorError(OSError):
    """Raised when a Git source cannot be safely materialized."""


class EnvironmentSourceCredentialResolver:
    """Resolve explicit environment references without persisting secret material."""

    _ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

    def resolve(self, credential_ref: str) -> str:
        if credential_ref.startswith("env://"):
            env_name = credential_ref.removeprefix("env://")
        elif credential_ref.startswith("env:"):
            env_name = credential_ref.removeprefix("env:")
        else:
            raise GitSourceConnectorError(
                "unsupported Git credential reference; use env:VARIABLE or provide a vault-backed resolver"
            )
        if not self._ENV_NAME.fullmatch(env_name):
            raise GitSourceConnectorError("Git credential environment reference is invalid")
        value = os.getenv(env_name, "")
        if not value:
            raise GitSourceConnectorError(f"Git credential reference {credential_ref!r} is unavailable")
        return value


class GitSourceConnector:
    """Materialize remote code into a revision-pinned, Nasus-managed checkout.

    This adapter is intentionally hidden behind the system-image source port so
    a future code-intelligence provider can replace Git or enrich its output
    without leaking provider-specific state into application services.
    """

    connector_kind = "git"

    def __init__(
        self,
        *,
        cache_dir: Path | None = None,
        allowed_hosts: set[str] | None = None,
        allowed_schemes: set[str] | None = None,
        timeout_seconds: int | None = None,
        credential_resolver: SourceCredentialResolver | None = None,
        git_binary: str | None = None,
    ) -> None:
        self.cache_dir = (
            cache_dir
            or Path(os.getenv("NASUS_SOURCE_CACHE_DIR", ".nasus/source-cache"))
        ).expanduser().resolve()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.allowed_hosts = allowed_hosts if allowed_hosts is not None else self._env_csv_set(
            "NASUS_GIT_ALLOWED_HOSTS"
        )
        self.allowed_schemes = allowed_schemes or self._env_csv_set(
            "NASUS_GIT_ALLOWED_SCHEMES",
            default={"git", "https", "ssh"},
        )
        self.timeout_seconds = timeout_seconds or self._env_int("NASUS_GIT_CLONE_TIMEOUT_SECONDS", 120)
        self.credential_resolver = credential_resolver or EnvironmentSourceCredentialResolver()
        self.git_binary = git_binary or shutil.which("git") or ""

    def supports(self, source: RawAssetRecord) -> bool:
        if source.source_type != "code":
            return False
        parsed = urlsplit(source.source_uri)
        return (
            parsed.scheme.lower() in self.allowed_schemes
            and bool(parsed.path.strip("/"))
        )

    def materialize(self, source: RawAssetRecord, *, refresh: bool) -> MaterializedSource:
        safe_uri, parsed = self._validated_uri(source.source_uri)
        if not self.git_binary:
            raise GitSourceConnectorError("Git executable is required to materialize remote code sources")

        cache_key = hashlib.sha256(safe_uri.encode("utf-8")).hexdigest()
        checkout = self.cache_dir / "git" / cache_key
        checkout.parent.mkdir(parents=True, exist_ok=True)
        lock_path = checkout.parent / f"{cache_key}.lock"

        with self._checkout_lock(lock_path), self._git_environment(source, parsed) as git_env:
            if (checkout / ".git").is_dir():
                if refresh:
                    self._refresh_checkout(checkout, safe_uri, git_env)
            elif checkout.exists():
                raise GitSourceConnectorError(f"managed Git cache path is not a repository: {checkout}")
            else:
                self._clone_checkout(checkout, safe_uri, git_env)

            revision = self._run_git(
                ["-C", str(checkout), "rev-parse", "HEAD"],
                env=git_env,
            ).strip()
            if not re.fullmatch(r"[0-9a-fA-F]{40,64}", revision):
                raise GitSourceConnectorError("Git checkout did not resolve to a valid commit revision")

        return MaterializedSource(
            local_path=checkout,
            connector_kind=self.connector_kind,
            source_ref=safe_uri,
            revision=revision,
            evidence_refs=(
                "connector:git",
                f"git:revision:{revision}",
                f"git:remote:{safe_uri}",
            ),
        )

    def _validated_uri(self, source_uri: str) -> tuple[str, SplitResult]:
        parsed = urlsplit(source_uri)
        scheme = parsed.scheme.lower()
        if scheme not in self.allowed_schemes:
            raise PermissionError(f"Git source URI scheme is not allowed: {scheme or 'unknown'}")
        if parsed.password or (scheme in {"http", "https"} and parsed.username):
            raise PermissionError("Git credentials must use credential_ref and must not be embedded in source_uri")
        if parsed.query or parsed.fragment:
            raise PermissionError("Git source URI query and fragment values are not allowed")

        host = (parsed.hostname or "").lower()
        if scheme != "file" and not host:
            raise PermissionError("Git source URI must include a host")
        if host and self.allowed_hosts and not self._host_allowed(host, self.allowed_hosts):
            raise PermissionError(f"Git source host is not allowed: {host}")

        safe_uri = urlunsplit((scheme, parsed.netloc, parsed.path, "", ""))
        return safe_uri, parsed

    def _clone_checkout(self, checkout: Path, safe_uri: str, env: Mapping[str, str]) -> None:
        temporary_parent = checkout.parent
        temporary_path = Path(tempfile.mkdtemp(prefix=f".{checkout.name}.", dir=temporary_parent))
        shutil.rmtree(temporary_path)
        try:
            self._run_git(
                ["clone", "--depth", "1", "--no-tags", "--", safe_uri, str(temporary_path)],
                env=env,
            )
            os.replace(temporary_path, checkout)
        except Exception:
            shutil.rmtree(temporary_path, ignore_errors=True)
            raise

    def _refresh_checkout(self, checkout: Path, safe_uri: str, env: Mapping[str, str]) -> None:
        self._run_git(["-C", str(checkout), "remote", "set-url", "origin", safe_uri], env=env)
        self._run_git(
            ["-C", str(checkout), "fetch", "--depth", "1", "--no-tags", "origin"],
            env=env,
        )
        self._run_git(["-C", str(checkout), "checkout", "--detach", "--force", "FETCH_HEAD"], env=env)
        self._run_git(["-C", str(checkout), "clean", "-ffd"], env=env)

    def _run_git(self, args: Sequence[str], *, env: Mapping[str, str]) -> str:
        try:
            result = subprocess.run(
                [self.git_binary, *args],
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                env=dict(env),
            )
        except subprocess.TimeoutExpired as exc:
            raise GitSourceConnectorError(
                f"Git command exceeded {self.timeout_seconds} second timeout"
            ) from exc
        except OSError as exc:
            raise GitSourceConnectorError(f"Git command could not start: {exc}") from exc

        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "Git command failed").strip()
            raise GitSourceConnectorError(detail[:500])
        return result.stdout

    @contextmanager
    def _git_environment(
        self,
        source: RawAssetRecord,
        parsed: SplitResult,
    ) -> Iterator[dict[str, str]]:
        env = os.environ.copy()
        env.update(
            {
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "credential.helper",
                "GIT_CONFIG_VALUE_0": "",
            }
        )
        if not source.credential_ref:
            yield env
            return
        if parsed.scheme not in {"http", "https"}:
            raise GitSourceConnectorError("credential_ref is currently supported for HTTP(S) Git sources only")

        secret = self.credential_resolver.resolve(source.credential_ref)
        username = os.getenv("NASUS_GIT_HTTP_USERNAME", "oauth2")
        with tempfile.TemporaryDirectory(prefix="nasus-git-askpass-", dir=self.cache_dir) as temp_dir:
            askpass = Path(temp_dir) / "askpass.sh"
            askpass.write_text(
                "#!/bin/sh\n"
                "case \"$1\" in\n"
                "  *Username*) printf '%s\\n' \"$NASUS_GIT_HTTP_USERNAME\" ;;\n"
                "  *) printf '%s\\n' \"$NASUS_GIT_HTTP_SECRET\" ;;\n"
                "esac\n",
                encoding="utf-8",
            )
            askpass.chmod(0o700)
            env["GIT_ASKPASS"] = str(askpass)
            env["NASUS_GIT_HTTP_USERNAME"] = username
            env["NASUS_GIT_HTTP_SECRET"] = secret
            yield env

    @staticmethod
    @contextmanager
    def _checkout_lock(lock_path: Path) -> Iterator[None]:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _host_allowed(host: str, patterns: set[str]) -> bool:
        for pattern in patterns:
            normalized = pattern.strip().lower()
            if normalized == host:
                return True
            if normalized.startswith("*.") and host.endswith(normalized[1:]):
                return True
        return False

    @staticmethod
    def _env_csv_set(name: str, default: set[str] | None = None) -> set[str]:
        raw = os.getenv(name, "")
        if not raw:
            return set(default or set())
        return {item.strip().lower() for item in raw.split(",") if item.strip()}

    @staticmethod
    def _env_int(name: str, default: int) -> int:
        try:
            return max(1, int(os.getenv(name, str(default))))
        except ValueError:
            return default


__all__ = [
    "EnvironmentSourceCredentialResolver",
    "GitSourceConnector",
    "GitSourceConnectorError",
]
