"""An explicit source selection, not an automatic maintenance policy."""
from dataclasses import dataclass


class SourceRefreshConflict(RuntimeError):
    pass


def _identity(value):
    return (type(value) is str and 1 <= len(value) <= 128
            and value == value.strip() and not any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value))


@dataclass(frozen=True)
class SourceRefreshSelection:
    source_ids: tuple[str, ...]
    expected_manifest_id: str
    expected_manifest_hash: str

    def __post_init__(self):
        if (type(self.source_ids) is not tuple or not 1 <= len(self.source_ids) <= 100
                or not all(_identity(value) for value in self.source_ids)
                or len(set(self.source_ids)) != len(self.source_ids)
                or not _identity(self.expected_manifest_id)):
            raise ValueError("Source refresh requires unique registered source IDs and a fixed manifest.")
        digest = self.expected_manifest_hash
        if (type(digest) is not str or len(digest) != 71 or not digest.startswith("sha256:")
                or any(char not in "0123456789abcdef" for char in digest[7:])):
            raise ValueError("Source refresh requires the exact source manifest hash.")

    def require_manifest(self, project_id, manifest):
        if (manifest is None or manifest.project_id != project_id
                or manifest.manifest_id != self.expected_manifest_id
                or manifest.content_hash != self.expected_manifest_hash):
            raise SourceRefreshConflict("Source manifest changed; read it again before refreshing selected sources.")
