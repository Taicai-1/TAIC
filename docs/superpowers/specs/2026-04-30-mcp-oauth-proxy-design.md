# MCP OAuth Proxy Design

## Problem

Claude Code cannot authenticate with the TAIC MCP server. The server currently points Claude Code to Google as the authorization server via RFC 9728, but Claude Code cannot complete the OAuth flow directly with Google because:
- Google doesn't implement MCP-compatible OAuth discovery
- The client secret exchange fails in the CLI context
- There's no intermediary to bridge the MCP OAuth protocol with Google's OAuth

## Solution

Transform the MCP server into its own OAuth authorization server that delegates identity verification to Google. The server handles the full OAuth 2.1 + PKCE flow with Claude Code, and internally uses Google OAuth to verify user identity.

## Architecture

### Flow

1. Claude Code contacts `/mcp` -> gets 401
2. Claude Code discovers OAuth metadata via `/.well-known/oauth-protected-resource` -> learns the MCP server itself is the authorization server
3. Claude Code fetches `/.well-known/oauth-authorization-server` -> gets authorize/token endpoints
4. Claude Code opens browser to `/authorize` with PKCE challenge
5. MCP server stores PKCE params, redirects browser to Google OAuth
6. User logs in with Google (@taic.co account)
7. Google redirects to MCP server's `/oauth/callback` with auth code
8. MCP server exchanges code with Google, validates email domain, generates an MCP authorization code
9. MCP server redirects browser to Claude Code's localhost callback with the MCP auth code
10. Claude Code calls `/token` with auth code + PKCE verifier
11. MCP server validates PKCE, returns a signed JWT access token
12. Claude Code uses the JWT for all subsequent `/mcp` requests

### New Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/.well-known/oauth-authorization-server` | GET | RFC 8414 metadata (authorization_endpoint, token_endpoint, etc.) |
| `/.well-known/oauth-protected-resource` | GET | RFC 9728 metadata (updated to point to self) |
| `/authorize` | GET | Start OAuth flow, store PKCE, redirect to Google |
| `/oauth/callback` | GET | Receive Google auth code, validate, generate MCP code |
| `/token` | POST | Exchange MCP code + PKCE verifier for JWT access token |

### Session Storage

In-memory Python dict with TTL-based cleanup. Stores:
- **Pending authorizations** (5 min TTL): PKCE code_challenge, redirect_uri, state, client_id
- **Authorization codes** (5 min TTL, single-use): linked to validated email
- No long-lived session storage needed — JWT tokens are self-contained

This is acceptable for Cloud Run (0-2 instances). If a cold start invalidates a pending flow, the user simply re-authenticates.

### Token Format

JWT signed with a server-side secret (`MCP_JWT_SECRET` env var):
- `sub`: user email
- `iss`: MCP server URL
- `aud`: "taic-mcp"
- `exp`: 24 hours from issuance
- `iat`: issuance time

### Updated Auth Middleware

The existing `GoogleOAuthMiddleware` is replaced with a simpler JWT validation:
- Extract `Authorization: Bearer <token>` header
- Verify JWT signature and expiration
- Extract email from `sub` claim
- Attach to `request.state.user_email`

### Security

- Only `@taic.co` verified emails accepted (checked during Google token exchange)
- PKCE S256 required and validated
- Authorization codes are single-use with 5-min expiry
- JWT tokens expire after 24h
- Google OAuth validates real identity
- Server-side JWT secret stored in GCP Secret Manager
- No client secret needed in `.mcp.json` (public client with PKCE)

### Client Configuration

`.mcp.json` simplified:
```json
{
  "mcpServers": {
    "taic-monitoring": {
      "type": "http",
      "url": "https://dev-taic-mcp-server-817946451913.europe-west1.run.app/mcp"
    }
  }
}
```

Claude Code auto-discovers everything via RFC 9728 -> RFC 8414.

### Dependencies Added

- `PyJWT>=2.8.0` for JWT signing/verification

### Environment Variables

| Variable | Purpose | Where |
|---|---|---|
| `GOOGLE_OAUTH_CLIENT_ID` | Google OAuth client ID (existing) | Secret Manager |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Google OAuth client secret (new) | Secret Manager |
| `MCP_JWT_SECRET` | JWT signing key | Secret Manager |
| `MCP_SERVER_URL` | Public URL of the MCP server | Cloud Run env |

### Files Modified

- `mcp-server/auth_middleware.py` — Rewrite: OAuth proxy + JWT validation
- `mcp-server/server.py` — Mount OAuth endpoints, update middleware
- `mcp-server/requirements.txt` — Add PyJWT
- `cloudbuild_mcp.yaml` — Add new secrets (GOOGLE_OAUTH_CLIENT_SECRET, MCP_JWT_SECRET)
- `.mcp.json` — Simplify (remove oauth block)

### Google Cloud Console Setup

The existing OAuth 2.0 client needs one change:
- Add `https://dev-taic-mcp-server-817946451913.europe-west1.run.app/oauth/callback` as an Authorized redirect URI

### Rollback

If the new auth fails, revert `auth_middleware.py` to the previous Google tokeninfo validation. The old approach works for direct API calls, just not for Claude Code MCP integration.
