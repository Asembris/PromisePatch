/**
 * The frame parser.
 *
 * Separated from the connection loop so the wire format is asserted directly, including the
 * two cases that decide correctness: a keepalive comment is not an event and carries no id,
 * and a frame split across two network chunks is one frame, not two half ones.
 */
import { describe, expect, it } from 'vitest'
import { parseFrames } from '../src/api/stream'

describe('parseFrames', () => {
  it('reads id, event and data from a domain event frame', () => {
    const { frames, rest } = parseFrames('id: 42\nevent: fixture.reset\ndata: {"seq":42}\n\n')
    expect(rest).toBe('')
    expect(frames).toEqual([{ id: '42', event: 'fixture.reset', data: '{"seq":42}' }])
  })

  it('reads a resync frame under its own event name', () => {
    const { frames } = parseFrames('id: 7\nevent: resync\ndata: {"latest_seq":7}\n\n')
    expect(frames[0]?.event).toBe('resync')
  })

  it('drops a keepalive comment, which carries no id and is not an event', () => {
    const { frames } = parseFrames(': keepalive\n\n')
    expect(frames).toEqual([])
  })

  it('holds an incomplete frame back until the rest of it arrives', () => {
    const first = parseFrames('id: 9\nevent: fixture.reset\ndata: {"se')
    expect(first.frames).toEqual([])

    const second = parseFrames(first.rest + 'q":9}\n\n')
    expect(second.frames).toEqual([{ id: '9', event: 'fixture.reset', data: '{"seq":9}' }])
  })

  it('reads several frames from one chunk in order', () => {
    const { frames } = parseFrames('id: 1\nevent: a\ndata: {}\n\nid: 2\nevent: b\ndata: {}\n\n')
    expect(frames.map((frame) => frame.id)).toEqual(['1', '2'])
  })
})
