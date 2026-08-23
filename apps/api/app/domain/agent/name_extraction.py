from __future__ import annotations

import re


def extract_project_name(content: str, *, fallback_index: int) -> str:
    quoted = re.search(r"['\"]([^'\"]+)['\"]", content)
    if quoted:
        return quoted.group(1)
    named = re.search(r"project(?: called| named)? ([A-Za-z0-9 _-]+)", content, re.IGNORECASE)
    if named:
        return named.group(1).strip()
    chinese_named = re.search(r"(?:名字叫|叫做|名为)([^，。,\\n]+)", content)
    if chinese_named:
        return chinese_named.group(1).strip()
    if "项目" in content:
        return "New Quality Project"
    return f"Project {fallback_index}"


def extract_version_name(content: str, *, fallback_index: int) -> str:
    quoted = re.search(r"['\"]([^'\"]+)['\"]", content)
    if quoted:
        return quoted.group(1)
    named = re.search(r"version(?: called| named| branch)? ([A-Za-z0-9._ -]+)", content, re.IGNORECASE)
    if named:
        return named.group(1).strip()
    chinese_named = re.search(r"(?:版本(?:叫|名为)?|分支(?:叫|名为)?)([^，。,\\n]+)", content)
    if chinese_named:
        return chinese_named.group(1).strip()
    if "版本" in content:
        return f"Version {fallback_index}"
    return "New Version"
