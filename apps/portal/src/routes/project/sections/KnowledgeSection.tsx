import type { ProjectRouteContext } from '../ProjectRouteTypes'
import type { SystemImageKnowledgeCardView } from '../ProjectSectionViewModels'
import { knowledgeSectionModel } from '../ProjectSectionViewModels'
import { MetricMini } from './primitives/MetricCards'

export function KnowledgeSection({ context, objectId }: { context: ProjectRouteContext; objectId?: string }) {
  const model = knowledgeSectionModel(context, objectId)

  return (
    <>
      <div className="agent-heading">
        <h1>System Image Knowledge</h1>
        <div className="segmented">
          <button className="active">Graph</button>
          <button>Objects</button>
          <button>Search</button>
        </div>
      </div>
      <div className="system-image-strip">
        <div>
          <span className="eyebrow">Knowledge object</span>
          <strong>{model.selectedName}</strong>
          <p>{model.selectedDescription}</p>
        </div>
        <div className="source-stat-grid">
          <MetricMini label="Objects" value={`${model.objectCount}`} />
          <MetricMini label="Relations" value={`${model.relationshipCount}`} />
          <MetricMini label="Chunks" value={`${model.chunkCount}`} />
          <MetricMini label="Metrics" value={`${model.metricCount}`} />
        </div>
      </div>
      <div className="quality-lane-grid">
        {model.objects.map((object) => (
          <KnowledgeCard object={object} key={object.id} />
        ))}
      </div>
    </>
  )
}

function KnowledgeCard({ object }: { object: SystemImageKnowledgeCardView }) {
  return (
    <div className="quality-lane-card ready">
      <div>
        <span className="quality-lane-dot" />
        <strong>{object.name}</strong>
      </div>
      <p>{object.type} · {object.branch}</p>
      <span>{object.confidence} confidence · {object.relationCount} relations</span>
    </div>
  )
}
