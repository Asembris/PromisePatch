// TRACES, verbatim from the approved prototype. `e` lists the diagram edges
// the trace lights, in the order they light (140 ms apart).
// Claim-hardening corrections (CONTENT_SOURCES.md) depart from the prototype
// only where the repository record required it.

export const TRACES = {
  report: { label: 'Worker report', text: 'A worker reports by voice or text in a signed-in session. A plan approval is written there or on the operator console, never over MCP. The workflow asks the deterministic engine what the failure reaches, then pushes governed amendments to the order system.', e: ['e1', 'e4', 'e6', 'e7'] },
  agent: { label: 'MCP client', text: 'An Alexa+-style agent, or any MCP client, calls five intent tools over Streamable HTTP, revision 2025-11-25. Its bearer token proves a process, not a person: MCP intake is a trusted reporting channel, and its reports are recorded under the server’s configured worker. It can spend a plan approval, never write one. The MCP server has no database access.', e: ['e2', 'e3', 'e4'] },
  consent: { label: 'Customer consent', text: 'One outbound Telegram message. The customer answers YES or NO on a signed web link. That answer is revalidated by the engine against a fresh snapshot before the amendment is committed.', e: ['e9', 'e10', 'e11', 'e12', 'e6', 'e7'] },
  model: { label: 'Where the model sits', text: 'The words go to the semantic boundary and a candidate reading comes back. It is checked against the bakery’s own vocabulary and never becomes authority. The canonical raspberry report costs zero model calls.', e: ['e5a', 'e5b'] },
};

export const DEFAULT_TRACE = 'consent';

/** Stroke transition 350 ms, 140 ms stagger per edge in trace order (MOTION_SPEC). */
export const TRACE_STAGGER_S = 0.14;
