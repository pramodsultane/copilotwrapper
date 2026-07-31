# copilotwrapper

copilotwrapper is a clean-room, open-source wrapper framework for AI coding assistant workflows.

## Clean-Room First

This repository is intentionally built from scratch as an original implementation.

- No copied code from existing projects.
- No mirrored internal logic patterns.
- No verbatim structural reuse from protected works.

See the full architecture and compliance specification:
- docs/CLEAN_ROOM_SPEC.md

## Copilot proxy mode

Set `COPILOTWRAPPER_UPSTREAM_BASE_URL` to your Copilot-compatible upstream, then run:

```bash
copilotwrapper proxy
```

Route requests through:

```bash
export COPILOT_PROVIDER_API_URL=http://127.0.0.1:8787
```

## License

This project is licensed under MIT.

## Planned Layout

```text
copilotwrapper/
  docs/
    CLEAN_ROOM_SPEC.md
  src/
  tests/
  tools/
  .github/
```
