# Gateway service design

> Fictional demo document. Every system, path, and number below is invented;
> this file exists so README examples and `dorian bench churn --doc
> examples/demo-repo/docs/design.md` have a committed, public-safe target.

## Overview

The gateway terminates client requests and forwards them to the booking
backend. It is intentionally small: one process, one config file, no shared
state beyond the session store.

## Request handling

The default request timeout is 30 seconds, set by `TIMEOUT = 30` in
`src/config.py`. Requests that exceed it return HTTP 504 without retry; the
client owns retry policy.

## Authentication

Login is served at `/v1/login`. The handler validates credentials against the
session store and issues a signed session cookie valid for 12 hours. All other
`/v1/*` routes require that cookie.

## Reporting

Nightly reports are emitted as JSON conforming to report schema version 1.1.
The schema adds the `region` field over 1.0; consumers must treat unknown
fields as forward-compatible.

## Non-goals

No request queuing, no multi-region failover, no plugin system. If the
gateway needs any of these, it should be split, not extended.
