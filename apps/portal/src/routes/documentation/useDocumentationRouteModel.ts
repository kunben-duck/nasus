import { useDocumentationContent } from '../../domains/platform/useTopLevelContent'

export function useDocumentationRouteModel() {
  const documentationContent = useDocumentationContent()

  return {
    entries: documentationContent.entries,
    statusDependencies: documentationContent.statusDependencies,
  }
}
