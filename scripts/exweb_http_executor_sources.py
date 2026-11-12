"""Files pinned by the configured owned HTTP probe and its archive replay."""

EXECUTOR_SOURCE_PATHS = (
    "apps/api/app/infrastructure/runner/owned_target_http.py",
    *(f"apps/runner/src/{name}" for name in (
        "owned-http-cli.mjs", "owned-http-cohort.mjs", "http-job.mjs", "http-bindings.mjs",
        "http-executor.mjs", "http-transport.mjs", "strict-json.mjs", "execution-receipt.mjs",
        "docker-http-transport.mjs",
    )),
)
