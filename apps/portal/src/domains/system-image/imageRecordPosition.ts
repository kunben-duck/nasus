export function imageRecordOffset(position: string, total: number): number | null {
  if (!Number.isSafeInteger(total) || total < 1 || !/^\d+$/.test(position.trim())) return null
  const record = Number(position.trim())
  return Number.isSafeInteger(record) && record >= 1 && record <= total ? record - 1 : null
}
