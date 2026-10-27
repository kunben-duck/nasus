from ...domain.system_image.source_refresh import SourceRefreshSelection


def source_refresh_selection(payload):
    fields = {"source_ids", "expected_manifest_id", "expected_manifest_hash"}
    present = fields.intersection(payload)
    if not present:
        return None
    if present != fields or type(payload["source_ids"]) is not list:
        raise ValueError("Selected source refresh requires source IDs, manifest ID and manifest hash.")
    return SourceRefreshSelection(tuple(payload["source_ids"]),
        payload["expected_manifest_id"], payload["expected_manifest_hash"])
