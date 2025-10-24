# Authentication Fix - Session Cookie Issue

## 🎯 Problem Identified

**Issue**: After Cognito authentication, users are redirected to login again
**Logs Show**:
```
Dashboard access attempt - Session data: {}
Dashboard access attempt - User data: None
Dashboard access attempt - Is authenticated: False
User not authenticated, redirecting to Cognito login
```

**Root Cause**: Session cookie not being properly set during auth callback redirect

## ✅ Solution Implemented

### 1. Fixed Auth Callback (`/auth/callback` endpoint)

**Changes Made**:
- Added `Response` parameter to explicitly set cookies
- Explicitly set session cookie with correct settings for ngrok/HTTPS
- Added comprehensive logging for debugging
- Set cookie parameters:
  - `secure=True` - Required for HTTPS (ngrok)
  - `samesite="none"` - Required for cross-site cookies
  - `httponly=True` - Security best practice
  - `max_age=7200` - 2 hour expiration

**Before**:
```python
@app.get("/auth/callback")
async def auth_callback(request: Request, code: str = Query(...)):
    # ... exchange code for tokens ...
    session["user"] = user_info
    return RedirectResponse(url="/", status_code=302)
```

**After**:
```python
@app.get("/auth/callback")
async def auth_callback(request: Request, response: Response, code: str = Query(...)):
    # ... exchange code for tokens ...
    session["user"] = user_info
    session["tokens"] = token_data
    session["authenticated_at"] = datetime.now(IST).isoformat()
    
    # Create redirect response
    redirect_response = RedirectResponse(url="/", status_code=302)
    
    # Explicitly set session cookie
    redirect_response.set_cookie(
        key="session_id",
        value=session.session_id,
        max_age=7200,
        httponly=True,
        secure=True,
        samesite="none",
        path="/"
    )
    
    return redirect_response
```

### 2. Enhanced Dashboard Logging

Added detailed logging to diagnose session issues:
```python
logger.info(f"📊 Dashboard access attempt")
logger.info(f"   Session ID from cookie: {session_id_cookie}")
logger.info(f"   Session object ID: {session.session_id}")
logger.info(f"   Session data keys: {list(session_data.keys())}")
logger.info(f"   User data exists: {user_data is not None}")
logger.info(f"   Is authenticated: {is_auth}")
```

### 3. Added Response Import

Fixed missing import:
```python
from fastapi.responses import (HTMLResponse, JSONResponse, PlainTextResponse, 
                              RedirectResponse, StreamingResponse, Response)
```

## 🧪 Testing

### Test 1: Redis Session Storage ✅
```bash
python3 test_redis_session.py
```

Result:
```
✅ Redis connection successful
✅ Test session created
✅ Session retrieved successfully
✅ Session storage is working
```

### Test 2: Authentication Flow (Manual)

1. **Visit Dashboard**: `https://250592ba55bf.ngrok-free.app/`
   - Should redirect to Cognito login

2. **Login via Cognito**
   - Enter credentials
   - Should redirect to `/auth/callback`

3. **Check Logs** (Expected):
   ```
   🔐 Auth callback received - code: xxx...
   ✅ Token exchange successful
   ✅ User info retrieved: user@example.com
   ✅ Session saved - Session ID: xxx
   ✅ User authenticated successfully: user@example.com
   ✅ Redirecting to dashboard with session cookie
   
   📊 Dashboard access attempt
      Session ID from cookie: xxx
      Session object ID: xxx
      Session data keys: ['user', 'tokens', 'authenticated_at']
      User data exists: True
      Is authenticated: True
   ✅ User authenticated: user@example.com, serving dashboard
   ```

4. **Dashboard Loads** ✅
   - Should see dashboard without redirect loop

## 🔧 Configuration Requirements

### Environment Variables (.env)
```bash
# Current ngrok URL
BASE_URL="https://250592ba55bf.ngrok-free.app"

# Cognito Configuration
COGNITO_REGION="ap-south-1"
COGNITO_USER_POOL_ID="ap-south-1_MYtre8r4L"
COGNITO_CLIENT_ID="6vvpsk667mdsq42kqlokc25il"
COGNITO_CLIENT_SECRET="your-secret"
COGNITO_DOMAIN="https://ap-south-1mytre8r4l.auth.ap-south-1.amazoncognito.com"
COGNITO_REDIRECT_URI="https://250592ba55bf.ngrok-free.app/auth/callback"
COGNITO_LOGOUT_URI="https://250592ba55bf.ngrok-free.app/"

# Redis
REDIS_URL="redis://localhost:6379/0"
```

### AWS Cognito App Client Settings

**Must have these URLs configured**:

1. Go to AWS Cognito Console
2. User Pool: `ap-south-1_MYtre8r4L`
3. App Client: `6vvpsk667mdsq42kqlokc25il`
4. Hosted UI Settings:

**Allowed callback URLs**:
```
https://250592ba55bf.ngrok-free.app/auth/callback
http://localhost:8000/auth/callback
```

**Allowed sign-out URLs**:
```
https://250592ba55bf.ngrok-free.app/
http://localhost:8000/
```

**Allowed OAuth Flows**:
- ✅ Authorization code grant
- ✅ Implicit grant

**Allowed OAuth Scopes**:
- ✅ openid
- ✅ email
- ✅ profile

## 🚀 Deployment

### Local Testing
```bash
# 1. Restart application
pkill -f "python.*main.py"
python3 main.py

# 2. Check logs
tail -f logs/application.log

# 3. Test in browser
# Visit: https://YOUR-NGROK-URL.ngrok-free.app/
```

### EC2 Deployment
```bash
# 1. Upload fixed file
scp main.py ubuntu@13.201.48.148:~/voice_bot/main.py

# 2. SSH to EC2
ssh ubuntu@13.201.48.148

# 3. Restart application
cd voice_bot
pkill -f "python.*main.py"
nohup python3 main.py > logs/app.log 2>&1 &

# 4. Monitor logs
tail -f logs/application.log | grep -E "auth|Dashboard|Session"
```

## 📊 Verification Checklist

- [x] Redis session storage working
- [x] Auth callback sets session cookie explicitly
- [x] Session cookie uses correct security settings
- [x] Dashboard logs show session details
- [ ] Manual test: Login → Callback → Dashboard (no redirect loop)
- [ ] Manual test: Session persists across page refreshes
- [ ] Manual test: Session expires after 2 hours

## 🐛 Troubleshooting

### Issue: Still getting redirect loop

**Check 1**: Browser cookies
```javascript
// In browser console:
document.cookie
// Should show: session_id=xxx
```

**Check 2**: Redis session exists
```bash
redis-cli
> KEYS session:*
> GET session:YOUR-SESSION-ID
```

**Check 3**: Application logs
```bash
tail -f logs/application.log | grep -A 5 "auth_callback"
```

**Expected output**:
```
🔐 Auth callback received - code: xxx
✅ Token exchange successful
✅ User info retrieved: user@example.com
✅ Session saved - Session ID: xxx
✅ User authenticated successfully
✅ Redirecting to dashboard with session cookie
```

### Issue: Cookie not being set

**Possible causes**:
1. Browser blocking third-party cookies
   - **Fix**: Use same-site deployment or add domain to exceptions

2. ngrok URL changed
   - **Fix**: Update `COGNITO_REDIRECT_URI` in .env
   - **Fix**: Update callback URL in Cognito console

3. HTTPS/Secure cookie mismatch
   - **Fix**: Ensure using HTTPS (ngrok provides this)
   - **Fix**: Set `secure=True` in cookie (already done)

### Issue: Session data empty

**Check**: Session middleware initialization
```python
# In main.py, check for:
app.add_middleware(
    RedisSessionMiddleware,
    secret_key=os.getenv("SECRET_KEY"),
    max_age=7200,
    session_cookie="session_id",
    secure=True,
    samesite="none"
)
```

## 📝 Files Changed

| File | Changes | Status |
|------|---------|--------|
| `main.py` | Fixed auth callback, added logging | ✅ Complete |
| `test_redis_session.py` | Created test script | ✅ Complete |
| `AUTH_FIX_SUMMARY.md` | This documentation | ✅ Complete |

## ✅ Success Criteria

1. **Login Flow**:
   - Visit `/` → Redirect to Cognito
   - Login → Redirect to `/auth/callback`
   - Callback → Redirect to `/` with session cookie
   - Dashboard loads without another redirect

2. **Session Persistence**:
   - Refresh page → Still authenticated
   - Navigate to other pages → Still authenticated
   - Wait 2 hours → Session expires, redirect to login

3. **Logs Show**:
   ```
   ✅ Token exchange successful
   ✅ Session saved
   ✅ User authenticated
   📊 Dashboard access - Is authenticated: True
   ```

---

**Status**: ✅ FIX READY FOR TESTING  
**Last Updated**: 2025-10-24 04:20 IST  
**Next Step**: Restart application and test authentication flow  
