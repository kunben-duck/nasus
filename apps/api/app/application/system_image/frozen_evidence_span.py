from ...domain.system_image.evidence import text_digest
from ...domain.system_image.image_revision import ImageRevisionIntegrityError, ImageRevisionPageTooLarge


def read_frozen_evidence_span(images, project_id, image_revision_id, object_id, evidence_id):
    """Read one complete verified span, never silently embed a truncated excerpt."""
    offset, evidence, parts, byte_count = None, None, [], 0
    while True:
        page = images.read_evidence(project_id, image_revision_id, object_id, evidence_id, start_line=offset, max_lines=200)
        if evidence is None:
            evidence = page.evidence
            offset = evidence.locator.start_line
        if (page.evidence != evidence or page.evidence.evidence_id != evidence_id or page.integrity != "verified"
                or page.start_line != offset or not offset <= page.end_line <= evidence.locator.end_line
                or evidence.locator.precision != "exact" or page.end_line - offset >= 200
                or page.excerpt_hash != text_digest(page.content)):
            raise ImageRevisionIntegrityError("frozen source page integrity mismatch")
        byte_count += len(page.content.encode("utf-8"))
        if byte_count > 65536 or len(parts) >= 512:
            raise ImageRevisionPageTooLarge("frozen span exceeds budget; no partial evidence accepted")
        parts.append(page.content)
        following = page.next_start_line
        if following is None:
            if page.end_line != evidence.locator.end_line:
                raise ImageRevisionIntegrityError("frozen source span is truncated")
            break
        if type(following) is not int or following != page.end_line + 1 or following > evidence.locator.end_line:
            raise ImageRevisionIntegrityError("frozen source cursor is invalid")
        offset = following
    raw = "".join(parts)
    if text_digest(raw) != evidence.snippet_hash:
        raise ImageRevisionIntegrityError("frozen source span hash mismatch")
    return evidence, raw
