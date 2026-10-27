"""Read bounded, exact Git trees without checkout, hooks or target execution."""
import hashlib
from pathlib import Path
import subprocess

from apps.api.app.domain.system_image.source_inventory import SourceInventory, SourceInventoryEntry


BEFORE = "cd9195691f2205d671fe61ba14e47744b5187ad6"
AFTER = "fe5827f6b76f77ef34918d8b452ee823142332dc"


def git_bytes(root: Path, *args):
    result = subprocess.run(["git", "--no-replace-objects", "-c", "core.hooksPath=/dev/null",
        "-C", str(root), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=True)
    return result.stdout


def read_git_tree(root: Path, revision: str):
    assert git_bytes(root, "rev-parse", "--verify", revision + "^{commit}").decode().strip() == revision
    manifest = git_bytes(root, "ls-tree", "-r", "-z", revision)
    assert len(manifest) <= 8 * 1024 * 1024
    files = []
    for line in manifest.split(b"\0"):
        if not line:
            continue
        metadata, path = line.split(b"\t", 1)
        mode, kind, object_id = metadata.split()
        assert mode in {b"100644", b"100755"} and kind == b"blob", "unsupported Git object must not be omitted"
        body = git_bytes(root, "cat-file", "blob", object_id.decode("ascii"))
        assert len(body) <= 10 * 1024 * 1024
        files.append((path.decode("utf-8"), body))
    files.sort()
    assert 1 <= len(files) <= 5000 and sum(len(body) for _, body in files) <= 100 * 1024 * 1024
    digest = hashlib.sha256()
    entries = [SourceInventoryEntry(".", "directory", "enumerated", "git_tree_verified")]
    for path, body in files:
        digest.update(path.encode("utf-8") + b"\0" + body)
        entries.append(SourceInventoryEntry(path, "file", "included", "git_blob_verified",
            len(body), "sha256:" + hashlib.sha256(body).hexdigest()))
    return files, "sha256:" + digest.hexdigest(), SourceInventory(tuple(sorted(entries, key=lambda item: item.path)), (), True)
