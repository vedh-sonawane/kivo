# ADR-0004: A synchronous backend core (async only where it earns its place)

- **Status:** Accepted
- **Date:** 2026-07-29

## Context

The backend talks to the device over serial and will eventually expose an HTTP/WebSocket
API. It is tempting to make everything `asyncio` from the start.

## Decision

Keep the device-facing core **synchronous** for now: send a command, block (with a
timeout) until the correlated response arrives. Introduce `asyncio` later, and only in
the API layer, when serving concurrent clients actually requires it.

## Rationale

- The device link is fundamentally **request/response over a single serial port** —
  inherently serial work. A synchronous client models it directly and is dramatically
  easier to read, test, and reason about.
- `asyncio` serial on Windows has real sharp edges (event-loop/transport quirks). Paying
  that cost now, before any concurrent consumer exists, is complexity for its own sake —
  which this project explicitly avoids.
- When the FastAPI layer arrives, a synchronous, thread-safe `DeviceClient` can be driven
  from async handlers via a worker thread / executor. The synchronous core does not block
  that future; it just defers the complexity until it pays for itself.

## Consequences

- The `Transport` interface is blocking-with-timeout (`read_line(timeout)`).
- Event handling in the synchronous client is cooperative: events are drained while
  waiting for responses and dispatched to a callback. A future async layer may replace
  this with a dedicated reader task.
