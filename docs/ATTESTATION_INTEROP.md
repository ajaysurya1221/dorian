# Attestation interop — `dorian export --in-toto` (experimental)

dorian can project a sealed `.warrant` into an [in-toto](https://in-toto.io/) Statement so a
claim-verification result can ride the same attestation rails as build provenance (SLSA),
Test Result, and Vulnerability predicates. This is **experimental interop**, not an official
predicate standard.

## Why

in-toto's vetted predicate registry has no `ClaimVerification` type (the closest are Test
Result, Vulnerability, and the Verification Summary Attestation). A sealed warrant — a
natural-language claim bound to a deterministic checker, verified at a content digest — is a
natural fit for one. dorian emits its own experimental predicate type until/unless a standard
one exists.

## Usage

```bash
dorian export --in-toto path/to/note.md     # -> JSON in-toto Statement on stdout
```

It reads `path/to/note.md.warrant`, verifies the sidecar's content-addressed id, and prints a
Statement. It is a **pure, deterministic projection** of the warrant: no signing, no DSSE
envelope, no network, no model, no extra dependencies. Pipe it to a file or a signer of your
choice.

## Shape

```json
{
  "_type": "https://in-toto.io/Statement/v1",
  "subject": [{ "name": "<artifact-uri>", "digest": { "sha256": "<artifact-hash>" } }],
  "predicateType": "https://dorian.vwp/attestations/ClaimVerification/v0.1",
  "predicate": {
    "warrantId": "sha256:...",
    "specVersion": "...",
    "dorianVersion": "1.0.0",
    "gitRef": "<commit at seal>",
    "sealedAt": "<RFC3339>",
    "bornVerifiable": true,
    "producedBy": { "runner": "...", "captured_at": "..." },
    "claims": [
      { "id": "...", "text": "...", "kind": "...", "loadBearing": true, "backed": true,
        "checkers": [{ "type": "C3", "program": "config-value:..." }] }
    ]
  }
}
```

## Honest scope

- The Statement attests **what dorian sealed and verified at seal time** (`bornVerifiable`
  means the seal exists only because every backed claim passed its checker then). The **live**
  trust state — which can later flip to REVOKED as code drifts — comes from `dorian status` /
  `dorian revalidate`, **not** from this static export. Re-export after a revalidate to capture
  a newer state.
- `predicateType` is a dorian-namespaced, **experimental** URI (`…/v0.1`); it is not a
  registered in-toto predicate and may change.
- No signing is performed. Wrap the Statement in DSSE / sign with your own tooling (cosign,
  etc.) if you need a verifiable envelope.
