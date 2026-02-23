# Acme Tasks (DiffGR realistic sample)

This directory is a small, realistic-ish codebase snapshot used by DiffGR sample reports.

It intentionally includes a mix of:
- backend routes and middleware
- a tiny in-memory "db" layer
- frontend TSX components
- CI workflow changes
- docs changes

The corresponding DiffGR JSON is under `samples/diffgr/`.

## Endpoints

- `GET /health`
- `POST /auth/login`
- `GET /tasks?limit=20&cursor=...`

## Notes

This is sample code for diff viewing only. It is not intended to be runnable as-is.

