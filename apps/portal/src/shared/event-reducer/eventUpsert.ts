export function upsertById<T extends { id: string }>(items: T[], nextItem: T): T[] {
  const index = items.findIndex((item) => item.id === nextItem.id)
  if (index < 0) return [...items, nextItem]
  return items.map((item, itemIndex) => (itemIndex === index ? nextItem : item))
}
