"""Explicit controlled changes to approved exweb bytes, never upstream commits."""
from __future__ import annotations

import hashlib

from apps.api.app.domain.system_image.source_inventory import SourceInventory, SourceInventoryEntry


BASE_COMMIT = "fe5827f6b76f77ef34918d8b452ee823142332dc"
JAVA_ROOT = "src/main/java/com/huawei/finance/front/one/"
CHAT_PATH = JAVA_ROOT + "interfaces/chat/ChatController.java"
DELETED_PATH = JAVA_ROOT + "interfaces/document/DocumentUploadController.java"
ADDED_PATH = JAVA_ROOT + "interfaces/chat/NasusChangeFixture.java"
CHANGE_POLICY = "nasus.exweb-controlled-code-change.v1"
ADDED_BODY = b"""// Nasus controlled static fixture; not an upstream exweb feature.
package com.huawei.finance.front.one.interfaces.chat;

public class NasusChangeFixture {
    public String health() {
        return value();
    }

    private String value() {
        return "fixture-only";
    }
}
"""


def _replace_once(body, before, after):
    if body.count(before) != 1:
        raise ValueError("The approved exweb mutation anchor must occur exactly once.")
    return body.replace(before, after, 1)


def controlled_code_change(files):
    """Return new bytes without checkout, file writes, hooks or target execution."""
    if (not files or len(files) > 5000 or len({path for path, _ in files}) != len(files)
            or any(type(path) is not str or type(body) is not bytes for path, body in files)):
        raise ValueError("Controlled change requires a complete unique byte inventory.")
    original = dict(files)
    if CHAT_PATH not in original or DELETED_PATH not in original or ADDED_PATH in original:
        raise ValueError("Controlled change differs from the approved exweb file set.")
    body = original[CHAT_PATH]
    for before, after in (
        (b"chatStream(@RequestBody", b"streamChat(@RequestBody"),
        (b'@PostMapping(value = "/stream",', b'@PostMapping(value = "/stream-v2",'),
        (b'toCommand(request, "sse", tenantId, userId)', b'toCommand(request, "fixture_sse", tenantId, userId)'),
    ):
        body = _replace_once(body, before, after)
    changed = dict(original)
    changed[CHAT_PATH] = b"// Nasus controlled code-change fixture, not an upstream commit.\n\n" + body
    del changed[DELETED_PATH]
    changed[ADDED_PATH] = ADDED_BODY
    return tuple(sorted(changed.items()))


def change_inventory(files):
    """Use the capture digest's path/NUL/body order; do not invent a Git SHA."""
    digest = hashlib.sha256()
    entries = [SourceInventoryEntry(".", "directory", "enumerated", "controlled_exweb_fixture")]
    for path, body in files:
        digest.update(path.encode("utf-8") + b"\0" + body)
        entries.append(SourceInventoryEntry(path, "file", "included", "controlled_exweb_fixture",
            len(body), "sha256:" + hashlib.sha256(body).hexdigest()))
    content_hash = "sha256:" + digest.hexdigest()
    return content_hash, SourceInventory(tuple(sorted(entries, key=lambda item: item.path)), (), True)
