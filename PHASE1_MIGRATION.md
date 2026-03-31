# Phase 1 Security Migration Guide

## Overview
This document describes the security improvements implemented in Phase 1 and how to migrate existing code.

## What Changed

### 1. JWT Storage (XSS Protection)
**Before:** JWT tokens stored ONLY in localStorage (vulnerable to XSS)
**After Phase 1:** JWT tokens stored in BOTH localStorage AND HttpOnly cookies
- **localStorage:** Temporary compatibility with existing pages
- **HttpOnly cookie:** Secure storage set by backend (XSS protected)
**After Phase 2:** localStorage will be removed completely

### 2. API Authentication
**Before:** Manual Authorization header in each request
**After:** Automatic cookie inclusion with `withCredentials: true`

## Migration Steps for Developers

### Frontend: Using the New API Client

Instead of manually setting Authorization headers:

```javascript
// ❌ OLD WAY (Phase 0)
import axios from 'axios';
const token = localStorage.getItem('token');
const response = await axios.get(`${API_URL}/agents`, {
  headers: { Authorization: `Bearer ${token}` }
});
```

Use the new api client:

```javascript
// ✅ NEW WAY (Phase 1)
import api from '../lib/api';
const response = await api.get('/agents');
// Token automatically included via HttpOnly cookie
```

### Backend: Using Cookie Authentication

The backend now supports both methods during transition:
1. HttpOnly cookie (preferred, XSS protected)
2. Authorization header (backward compatibility)

To use the new cookie-based auth:

```python
# Import the new verify function
from auth import verify_token_from_cookie

# Use in endpoints
@app.get("/protected-endpoint")
async def protected_route(
    request: Request,
    user_id: str = Depends(verify_token_from_cookie),  # ✅ New
    db: Session = Depends(get_db)
):
    # user_id automatically extracted from cookie or header
    ...
```

## Backward Compatibility

During Phase 1, both methods work:
- HttpOnly cookie (recommended)
- Authorization header (deprecated, will be removed in Phase 2)

This allows gradual migration of all frontend components.

## Testing

### Test HttpOnly Cookie
```bash
# Login and check cookie is set
curl -X POST http://localhost:8080/login \
  -H "Content-Type: application/json" \
  -d '{"username":"test","password":"test123"}' \
  -c cookies.txt -v

# Use cookie for authenticated request
curl http://localhost:8080/agents \
  -b cookies.txt
```

### Verify XSS Protection
Try accessing the token from browser console:
```javascript
// This should return null (token not accessible to JavaScript)
document.cookie.split(';').find(c => c.includes('token'))
// HttpOnly cookies are not visible to JavaScript
```

## Security Improvements

1. **XSS Protection:** Tokens cannot be stolen via XSS attacks
2. **CSRF Protection:** SameSite=Strict prevents CSRF
3. **Secure Transport:** Secure flag ensures HTTPS-only in production

## Next Steps (Phase 2)

- Remove Authorization header support
- Remove all `localStorage.getItem('token')` usage
- Migrate all frontend pages to use `api` client
- Reduce JWT expiration from 24h to 15-30min
- Implement refresh token rotation

## Troubleshooting

### "Not authenticated" errors
- Ensure axios client uses `withCredentials: true`
- Check that CORS allows credentials (`allow_credentials=True`)
- Verify cookie domain matches request domain

### Cookie not being set
- Check ENVIRONMENT variable is set correctly
- In dev, ensure `secure: false` (HTTP allowed)
- In prod, ensure `secure: true` (HTTPS only)

### Old code still using localStorage
- Gradually migrate using the api client from `lib/api.js`
- Both methods work during Phase 1 transition period
