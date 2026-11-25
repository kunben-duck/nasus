import re
import unicodedata
from urllib.parse import urlsplit


def code_file_path(raw: str) -> str:
    path = unicodedata.normalize("NFC", raw)
    parts = path.casefold().split("/")
    excluded = {".git", ".svn", ".hg", "node_modules", "dist", "build", "target", "__pycache__", ".venv",
                ".cache", ".next", ".nasus", ".nasus-complete", ".bundle.zip", ".ssh", ".aws",
                ".npmrc", ".pypirc", ".netrc", ".terraform", ".ds_store", "credentials.json"}
    if (len(path) > 1024 or re.search(r"[\\:\x00-\x1f\x7f]", path)
            or any(p in {"", ".", ".."} or p in excluded or p.startswith(".env") or p.startswith("id_rsa")
                   or p.startswith("id_ed25519") or p.endswith((".pem", ".key", ".p12", ".pfx"))
                   for p in parts)):
        raise ValueError("Directory contains an unsafe or excluded path")
    return path


def check_upload_scope(project_id, kind, uri, tracked_ref=None):
    parsed = urlsplit(uri)
    if parsed.scheme not in {"local-object", "s3"}:
        return
    if (not parsed.netloc or parsed.netloc in {".", ".."} or "\\" in uri or uri != uri.strip()
            or any(p in {"", ".", ".."} for p in parsed.path[1:].split("/"))):
        raise ValueError("Invalid storage reference")
    if parsed.path.startswith("/source-uploads/") and not parsed.path.startswith(f"/source-uploads/{project_id}/{kind}/"):
        raise ValueError("Uploads must belong to this project and source type")
    if kind == "code" or "/code/" in parsed.path and parsed.path.startswith("/source-uploads/"):
        prefix = f"/source-uploads/{project_id}/code/"
        if (kind != "code" or tracked_ref or parsed.query or parsed.fragment
                or not parsed.path.startswith(prefix) or not re.fullmatch(r"[0-9a-f]{64}\.zip", parsed.path[len(prefix):])):
            raise ValueError("Select a code snapshot uploaded to this project")
