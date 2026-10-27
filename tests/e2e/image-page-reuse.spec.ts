import { expect, test } from '@playwright/test'
import { imagePagePlaceholder } from '../../apps/portal/src/domains/system-image/imagePageReuse'

const key = ['system-image', 'project', 'image-page', 'read-session', 'image', { section: 'objects', offset: 0 }]
const data = { marker: 'already verified page' }

test('image paging placeholder can only retain the exact project, read session and immutable image', () => {
  expect(imagePagePlaceholder(data, key, [...key.slice(0, 5), { section: 'objects', offset: 25 }])).toBe(data)
  expect(imagePagePlaceholder(data, key, [...key.slice(0, 5), { section: 'source_members', offset: 0 }])).toBe(data)
  for (let index = 0; index < 5; index++) {
    const other = [...key]
    other[index] = 'another-scope'
    expect(imagePagePlaceholder(data, key, other)).toBeUndefined()
    expect(imagePagePlaceholder(data, other, key)).toBeUndefined()
  }
})

test('missing, empty or malformed image page keys do not keep old inputs', () => {
  expect(imagePagePlaceholder(data, undefined, key)).toBeUndefined()
  expect(imagePagePlaceholder(undefined, key, key)).toBeUndefined()
  expect(imagePagePlaceholder(data, key.slice(0, 5), key)).toBeUndefined()
  expect(imagePagePlaceholder(data, key, [...key, 'extra'])).toBeUndefined()
  for (const index of [1, 3, 4]) {
    for (const invalid of ['', null, 1, {}]) {
      const malformed = [...key]
      malformed[index] = invalid as string
      expect(imagePagePlaceholder(data, malformed, malformed)).toBeUndefined()
    }
  }
})
