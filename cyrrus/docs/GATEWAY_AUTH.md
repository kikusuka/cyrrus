# Gateway authentication

Cyrrus has two different API keys. Do not confuse them:

| Setting | Direction | Purpose |
|---|---|---|
| `gateway.api_key_env` | Incoming | Names the environment variable holding the Bearer token clients must present to the Cyrrus gateway. |
| `provider.api_key_env` | Outgoing | Names the environment variable holding the upstream provider key; Cyrrus sends it to the provider and never accepts it from clients. |

Incoming authentication is enabled only when `gateway.api_key_env` is set to
the **name** of an environment variable (or a `.env` entry). The value of that
variable is the token. It is never written to logs or returned in a response.

## Route matrix

These are the only HTTP routes the gateway serves when `gateway.api_key_env`
is set. `/health` is deliberately public; every other route is protected.

| Method | Route | Protected? | No / wrong token | Correct token |
|---|---|---|---|---|
| GET | `/health` | No (public) | `200 {"status": "ok"}` | `200 {"status": "ok"}` |
| GET | `/cyrrus/status` | Yes | `401` | `200` |
| GET | `/cyrrus/last` | Yes | `401` | `200` |
| GET | `/v1/models` | Yes | `401` | `200` (proxied or local fallback) |
| POST | `/v1/chat/completions` | Yes | `401` | proxied response |
| any | any other path | Yes | `401` | `404` |

There are **no memory or admin HTTP routes**. Memory operations live in the
`cyrrus memory` CLI, not in the gateway. Unknown routes are authenticated before
the `404`, so an unauthenticated client cannot probe which paths exist.

`/health` is public on purpose: it returns only liveness, and the container
`HEALTHCHECK` uses it without needing the token. If your deployment policy
requires every route to be authenticated, put the gateway behind a reverse
proxy that protects `/health` too.

## Header rules

```http
Authorization: Bearer <token>
```

* The `Bearer` scheme is case-insensitive (`bearer`, `BEARER` are accepted).
* The token is compared exactly and case-sensitively in constant time
  (`hmac.compare_digest` on bytes). `s3cret` and `S3CRET` are different.
* Exactly one space separates the scheme and token. A missing header, a wrong
  token, `Bearer` with no token, a different scheme, a doubled space, or
  leading/trailing whitespace all produce `401`:

  ```json
  {"error": {"message": "Unauthorized", "type": "authentication_error"}}
  ```

* The token is never logged and is not echoed in the `401` body.

This matrix is covered by `tests/test_gateway.py` (route matrix, scheme case,
malformed headers, token-not-logged, and startup refusal tests).

## Startup rules

`create_server()` refuses to start, raising `ValueError`, when:

1. the bind host is not loopback and `gateway.api_key_env` is not set; or
2. `gateway.api_key_env` is set but the named environment variable is unset,
   empty, or whitespace-only.

Rule 2 also applies on loopback. This prevents a typo in the variable name from
silently producing a gateway that starts without usable authentication.

## Example

```json
{
  "gateway": {
    "host": "0.0.0.0",
    "port": 8787,
    "api_key_env": "CYRRUS_GATEWAY_TOKEN"
  }
}
```

```sh
export CYRRUS_GATEWAY_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
cyrrus serve --config /path/to/project
curl -H "Authorization: Bearer $CYRRUS_GATEWAY_TOKEN" http://127.0.0.1:8787/cyrrus/status
```

Put TLS in front of a publicly reachable gateway (reverse proxy); the gateway
itself speaks plain HTTP.
