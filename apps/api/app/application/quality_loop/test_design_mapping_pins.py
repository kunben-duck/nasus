from ...domain.quality_loop.acceptance_specification import acceptance_digest


def mapping_review_query_keys(project_id):
    return [[kind, project_id] for kind in (
        "test-design-mapping", "automation-input", "mapping-staging", "mapping-final-preview",
        "automation-script-input", "automation-script-revisions", "automation-script-reviews",
    )]


def mapping_generation_pin(result):
    return {"generation_id": result["metadata"]["generation_id"],
        "artifact_hash": result["metadata"]["artifact_hash"],
        "context_pin": result["result"]["context_pin"], "scope_pin": result["result"]["scope_pin"],
        "input_digest": result["result"]["request"]["input_digest"],
        "proposal_hash": acceptance_digest(result["result"]["proposal"])}
