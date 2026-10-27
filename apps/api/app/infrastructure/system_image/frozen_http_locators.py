"""Derive locators from verified frozen bytes, never the working checkout."""
from dataclasses import asdict

from ...application.system_image.code_analysis_inventory import build_code_analysis_inventory
from ...application.system_image.source_ports import SourceTextUnit
from ...domain.shared.native_build_source import byte_digest
from ...domain.quality_loop.acceptance_specification import acceptance_digest
from ...domain.system_image.evidence import source_lines, text_digest
from .java_structure_inventory import LOCATOR_RULE, RULE
from .tree_sitter_code_intelligence import TreeSitterCodeIntelligenceAdapter


class FrozenHttpLocatorInventory:
    def __init__(self, sources):
        self.sources = sources

    def verify(self, plan, inventory, *, require_access):
        expected = sorted(plan["selection"]["target_build"]["code_sources"], key=lambda pin: pin["binding_id"])
        if len(inventory["sources"]) != len(expected):
            raise ValueError("locator history source roster differs")
        context = plan["prepared"]["context_pin"]
        for selected, archived in zip(expected, inventory["sources"]):
            require_access()
            source = self.sources.read(project_id=plan["project_id"], image_revision_id=context["image_revision_id"],
                image_artifact_hash=context["image_artifact_hash"], **selected)
            if asdict(source.pin) != archived["pin"]:
                raise ValueError("locator history original source pin differs")
            files = {file.path: file for file in source.files}
            if len(archived["files"]) != len(files) or len({file["relative_path"] for file in archived["files"]}) != len(files):
                raise ValueError("locator history complete file roster differs")
            for file in archived["files"]:
                original = files.get(file["relative_path"])
                if original is None or type(file["byte_count"]) is not int or file["byte_count"] != len(original.body) or file["source_file_hash"] != byte_digest(original.body):
                    raise ValueError("locator history original file bytes differ")
            for route in archived["routes"]:
                original = files.get(route["relative_path"])
                if original is None or route["source_file_hash"] != byte_digest(original.body):
                    raise ValueError("locator history route file differs")
                lines = source_lines(original.body.decode("utf-8", errors="strict"))
                for span in (route, *route["supporting_spans"]):
                    if (type(span["start_line"]) is not int or type(span["end_line"]) is not int
                            or not 1 <= span["start_line"] <= span["end_line"] <= len(lines)
                            or span["snippet_hash"] != text_digest("".join(lines[span["start_line"] - 1:span["end_line"]]))):
                        raise ValueError("locator history original source span differs")
        require_access()

    def inspect(self, plan, *, require_access):
        context = plan["prepared"]["context_pin"]
        results = []
        scoped = plan["schema"] == "nasus.run-plan.v3"
        rule = "java.import-resolved-http-locators.v2" if scoped else LOCATOR_RULE
        parser = TreeSitterCodeIntelligenceAdapter(strict_http_locators=True)
        for selected in sorted(plan["selection"]["target_build"]["code_sources"], key=lambda pin: pin["binding_id"]):
            require_access()
            source = self.sources.read(project_id=plan["project_id"], image_revision_id=context["image_revision_id"],
                image_artifact_hash=context["image_artifact_hash"], **selected)
            units = []
            for file in source.files:
                try:
                    text, lossless = file.body.decode("utf-8", errors="strict"), True
                except UnicodeError:
                    text, lossless = file.body.decode("utf-8", errors="replace"), False
                units.append(SourceTextUnit(file.path, text, len(file.body), byte_digest(file.body), text_is_lossless=lossless))
            analyzed = parser.analyze_controlled(units, check_current=require_access)
            inventory = build_code_analysis_inventory({"project_id": source.pin.project_id,
                "source_id": source.pin.source_id, "external_revision": source.pin.external_revision,
                "files": [file.metadata() for file in source.files]}, analyzed, units)
            routes = [fact for fact in inventory["facts"] if fact["kind"] == "route"]
            if scoped:
                # A second AST observation proves only the possible method/path
                # scope of unsupported conditions, never that they are satisfied.
                paths = TreeSitterCodeIntelligenceAdapter().analyze_controlled(units, check_current=require_access)
                for route in routes:
                    route["rule"] = rule
                    if route["status"] != "unresolved":
                        continue
                    matches = [fact for fact in paths.structural_facts if fact.kind == "route" and fact.rule == RULE
                        and fact.relative_path == route["relative_path"] and fact.start_line == route["start_line"]
                        and fact.end_line == route["end_line"]]
                    pairs = sorted({(fact.method, fact.route_path) for fact in matches if fact.status == "observed"})
                    route["unresolved_match_scope"] = ([{"method": method, "route_path": path} for method, path in pairs]
                        if matches and all(fact.status == "observed" for fact in matches) and 1 <= len(pairs) <= 64 else None)
                for file in inventory["files"]:
                    file["rules"] = tuple(rule if item == LOCATOR_RULE else item for item in file["rules"])
            results.append({"pin": asdict(source.pin), "files": inventory["files"],
                "routes": routes})
        require_access()
        value = {"schema": "nasus.frozen-http-route-inventory.v2" if scoped else "nasus.frozen-http-route-inventory.v1", "rule": rule,
            "provider": parser.provider, "provider_version": parser.provider_version, "sources": results}
        return {**value, "inventory_hash": acceptance_digest(value)}
