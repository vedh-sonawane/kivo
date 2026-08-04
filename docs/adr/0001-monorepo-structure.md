# ADR-0001: Single repository for firmware, backend, and protocol

- **Status:** Accepted
- **Date:** 2026-07-29

## Context

Kivo has (at least) three parts that must agree with each other: the Arduino firmware,
the Python backend, and the wire protocol between them. They could live in separate
repositories or in one.

## Decision

Use a **single repository (monorepo)** with top-level `firmware/`, `backend/`, and
`protocol/` directories.

## Rationale

- The wire protocol is a **contract implemented on both sides**. A change to it must
  update the spec, the C++ codec, and the Python codec together. In one repo that is a
  single atomic commit; across repos it is a fragile multi-repo dance with version
  skew.
- It is one person's learning project. The coordination overhead of multiple repos
  (cross-repo versioning, submodules, release pinning) buys nothing here.
- Each part still has its own toolchain and build (PlatformIO for firmware, a Python
  package for the backend); the monorepo does not couple their builds.

## Consequences

- CI (when added) will need to run two toolchains from one repo - a minor, well-trodden
  cost.
- If a part ever needs to be reused independently, it can be extracted later; nothing
  here prevents that.
