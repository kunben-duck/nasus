from ...application.system_image.code_index_generations import code_unit_snapshot_hash
from dataclasses import asdict, replace

from ...application.system_image.build_lineage import NativeCodeExecutionPin
from ...application.system_image.source_ports import code_projection_payload
from ...domain.system_image.source_snapshots import snapshot_digest
from .composite_code_intelligence import CompositeCodeIntelligenceAdapter


class RegisteredCodeIntelligenceAdapter:
    """Keep the existing structural merge while leasing its real native enhancer."""
    def __init__(self, composite, generations):
        self.composite, self.generations = composite, generations

    def analyze_source(self, source, units, *, invocation_id, check_current):
        enhancer = _GenerationEnhancer(self.generations, self.composite.enhancer, source, invocation_id)
        scoped = CompositeCodeIntelligenceAdapter(self.composite.primary, enhancer, mode=self.composite.mode)
        return scoped.analyze_controlled(units, check_current=check_current)


class _GenerationEnhancer:
    def __init__(self, generations, native, source, invocation_id):
        self.generations, self.native, self.source, self.invocation_id = generations, native, source, invocation_id

    def capabilities(self):
        return self.native.capabilities()

    def analyze_controlled(self, units, *, check_current):
        prepared = self.generations.open_index(self.source, invocation_id=self.invocation_id, check_current=check_current)
        if code_unit_snapshot_hash(units) != prepared.generation.snapshot_hash:
            prepared.close()
            raise ValueError("materialized code units differ from their registered source snapshot")
        with prepared:
            projection = prepared.read_projection()
            return replace(projection, execution_pin=NativeCodeExecutionPin(prepared.generation,
                snapshot_digest(code_projection_payload(projection)), snapshot_digest(asdict(prepared.protocol_receipt()))))
