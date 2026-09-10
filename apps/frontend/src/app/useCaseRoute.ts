/**
 * Which case the browser is looking at, kept in the address bar.
 *
 * This is the whole of the reload guarantee on the client side. The case id lives in
 * `?case=<id>` rather than in a `useState`, so a refresh, a restored tab, a bookmark and a
 * pasted link all mount the app already pointing at the same case — and what it then shows is
 * whatever `GET /api/cases/{id}` answers. There is no client-side cache of a case to restore
 * and nothing to reconstruct, which is what makes the reloaded screen incapable of disagreeing
 * with the durable one.
 *
 * `popstate` is listened to because the browser's back button is a legitimate way to leave a
 * case, and a component that only read the URL at mount would keep rendering the case the
 * worker had just navigated away from.
 */
import { useCallback, useEffect, useState } from 'react'

export const CASE_PARAM = 'case'

function currentCaseId(): string | null {
  if (typeof window === 'undefined') return null
  return new URLSearchParams(window.location.search).get(CASE_PARAM)
}

export interface CaseRoute {
  /** The case in the address bar, or `null` when the address bar names none. */
  caseId: string | null
  /** Open a case, or pass `null` to leave the one that is open. */
  open: (caseId: string | null) => void
}

export function useCaseRoute(): CaseRoute {
  const [caseId, setCaseId] = useState<string | null>(currentCaseId)

  useEffect(() => {
    const onPop = (): void => {
      setCaseId(currentCaseId())
    }
    window.addEventListener('popstate', onPop)
    return () => {
      window.removeEventListener('popstate', onPop)
    }
  }, [])

  const open = useCallback((next: string | null): void => {
    const url = new URL(window.location.href)
    if (next === null) url.searchParams.delete(CASE_PARAM)
    else url.searchParams.set(CASE_PARAM, next)
    // `pushState` rather than `replaceState`: opening a case is a place a worker can go back
    // from, and the list they came from is where back should land them.
    window.history.pushState({}, '', url)
    setCaseId(next)
  }, [])

  return { caseId, open }
}
