# 🧪 Postman Testing Guide for Amazon Cognito Authentication

## Overview

This guide provides step-by-step instructions for testing the Amazon Cognito authentication system using Postman. The authentication system includes user signup, login, token validation, and protected routes.

## 🚀 Prerequisites

1. **Server Running**: Ensure your FastAPI server is running on `http://localhost:8000`
2. **AWS Cognito Setup**: Configure your AWS Cognito User Pool and App Client
3. **Environment Variables**: Set up your `.env` file with Cognito credentials
4. **Postman Installed**: Download and install Postman

## 📋 Environment Setup in Postman

### Step 1: Create a New Environment

1. Open Postman
2. Click on **Environments** in the left sidebar
3. Click **Create Environment**
4. Name it: `Voice Assistant Auth`
5. Add the following variables:

| Variable Name | Initial Value | Current Value |
|---------------|---------------|---------------|
| `base_url` | `http://localhost:8000` | `http://localhost:8000` |
| `access_token` | | (will be set automatically) |
| `refresh_token` | | (will be set automatically) |
| `user_email` | `test@example.com` | `test@example.com` |
| `user_password` | `TempPassword123!` | `TempPassword123!` |
| `oauth_state` | `test_state_123` | `test_state_123` |
| `redirect_uri` | `http://localhost:8000/auth/callback` | `http://localhost:8000/auth/callback` |

6. Click **Save**

### Step 2: Select the Environment
- In the top-right corner of Postman, select the "Voice Assistant Auth" environment

## 🔐 Authentication Flow Testing

### Test 1: User Signup

**Purpose**: Register a new user in Cognito

1. **Create New Request**:
   - Method: `POST`
   - URL: `{{base_url}}/auth/signup`

2. **Headers**:
   ```
   Content-Type: application/json
   ```

3. **Body** (raw JSON):
   ```json
   {
     "email": "{{user_email}}",
     "password": "{{user_password}}",
     "additional_attributes": {
       "name": "Test User",
       "phone_number": "+1234567890"
     }
   }
   ```

4. **Expected Response** (200 OK):
   ```json
   {
     "success": true,
     "message": "User registered successfully",
     "user_sub": "uuid-string",
     "confirmation_required": true
   }
   ```

5. **Common Errors**:
   - `400`: User already exists or invalid password
   - `500`: AWS configuration error

### Test 2: Confirm Signup (If Required)

**Purpose**: Confirm user registration with verification code

1. **Create New Request**:
   - Method: `POST`
   - URL: `{{base_url}}/auth/confirm-signup`

2. **Headers**:
   ```
   Content-Type: application/json
   ```

3. **Body** (raw JSON):
   ```json
   {
     "email": "{{user_email}}",
     "confirmation_code": "123456"
   }
   ```

4. **Expected Response** (200 OK):
   ```json
   {
     "success": true,
     "message": "User confirmed successfully"
   }
   ```

**Note**: You'll need to check your email for the actual confirmation code.

### Test 3: User Login

**Purpose**: Authenticate user and get JWT tokens

1. **Create New Request**:
   - Method: `POST`
   - URL: `{{base_url}}/auth/login`

2. **Headers**:
   ```
   Content-Type: application/json
   ```

3. **Body** (raw JSON):
   ```json
   {
     "email": "{{user_email}}",
     "password": "{{user_password}}"
   }
   ```

4. **Tests** (Add this to the Tests tab):
   ```javascript
   // Save tokens to environment variables
   if (pm.response.code === 200) {
       const response = pm.response.json();
       pm.environment.set("access_token", response.access_token);
       pm.environment.set("refresh_token", response.refresh_token);
       console.log("Tokens saved to environment");
   }
   ```

5. **Expected Response** (200 OK):
   ```json
   {
     "success": true,
     "access_token": "eyJraWQiOiI...",
     "refresh_token": "eyJjdHki...",
     "id_token": "eyJraWQi...",
     "token_type": "Bearer",
     "expires_in": 3600,
     "user": {
       "sub": "uuid-string",
       "username": "test@example.com",
       "email": "test@example.com",
       "email_verified": true
     }
   }
   ```

6. **Common Errors**:
   - `401`: Invalid email or password
   - `400`: User not confirmed
   - `404`: User not found

### Test 4: Get Current User Info

**Purpose**: Verify token validation works

1. **Create New Request**:
   - Method: `GET`
   - URL: `{{base_url}}/auth/me`

2. **Headers**:
   ```
   Authorization: Bearer {{access_token}}
   ```

3. **Expected Response** (200 OK):
   ```json
   {
     "sub": "uuid-string",
     "username": "test@example.com",
     "email": "test@example.com",
     "email_verified": true,
     "iat": 1630000000,
     "exp": 1630003600
   }
   ```

4. **Common Errors**:
   - `401`: Invalid or expired token
   - `403`: Token validation failed

### Test 5: Refresh Token

**Purpose**: Get new access token using refresh token

1. **Create New Request**:
   - Method: `POST`
   - URL: `{{base_url}}/auth/refresh`

2. **Headers**:
   ```
   Content-Type: application/json
   ```

3. **Body** (raw JSON):
   ```json
   {
     "refresh_token": "{{refresh_token}}"
   }
   ```

4. **Tests** (Add this to the Tests tab):
   ```javascript
   // Update access token
   if (pm.response.code === 200) {
       const response = pm.response.json();
       pm.environment.set("access_token", response.access_token);
       console.log("Access token refreshed");
   }
   ```

5. **Expected Response** (200 OK):
   ```json
   {
     "success": true,
     "access_token": "eyJraWQiOiI...",
     "token_type": "Bearer",
     "expires_in": 3600
   }
   ```

## 🔒 Testing Protected Routes

### Test 6: Protected Route (Upload Customers)

**Purpose**: Test that protected routes require authentication

1. **Create New Request**:
   - Method: `POST`
   - URL: `{{base_url}}/api/upload-customers`

2. **Headers**:
   ```
   Authorization: Bearer {{access_token}}
   Content-Type: multipart/form-data
   ```

3. **Body** (form-data):
   - Key: `file`
   - Type: File
   - Value: Upload a CSV file with customer data

4. **Expected Response** (200 OK):
   ```json
   {
     "message": "File uploaded and processed successfully",
     "processed_count": 5,
     "total_count": 5
   }
   ```

### Test 7: Protected Route Without Token

**Purpose**: Verify authentication is required

1. **Create New Request**:
   - Method: `GET`
   - URL: `{{base_url}}/api/customers`

2. **Headers**: (Don't include Authorization header)

3. **Expected Response** (401 Unauthorized):
   ```json
   {
     "detail": "Not authenticated"
   }
   ```

### Test 8: Protected Route With Invalid Token

**Purpose**: Test invalid token handling

1. **Create New Request**:
   - Method: `GET`
   - URL: `{{base_url}}/api/customers`

2. **Headers**:
   ```
   Authorization: Bearer invalid_token_here
   ```

3. **Expected Response** (401 Unauthorized):
   ```json
   {
     "detail": "Invalid token"
   }
   ```

## 📊 Testing Collection Setup

### Create a Postman Collection

1. **Create Collection**:
   - Click **Collections** in left sidebar
   - Click **Create Collection**
   - Name: `Voice Assistant Auth Tests`

2. **Add Requests**: Add all the above requests to this collection

3. **Collection Variables**: Set collection-level variables for common values

4. **Pre-request Scripts**: Add to collection level:
   ```javascript
   // Check if access token is expired
   const token = pm.environment.get("access_token");
   if (token) {
       try {
           const payload = JSON.parse(atob(token.split('.')[1]));
           const exp = payload.exp * 1000; // Convert to milliseconds
           const now = Date.now();
           
           if (now >= exp) {
               console.log("Token expired, need to refresh");
               // Set a flag to refresh token
               pm.environment.set("token_expired", "true");
           }
       } catch (e) {
           console.log("Error parsing token:", e);
       }
   }
   ```

## 🚨 Error Scenarios to Test

### Test 9: Signup with Existing Email
```json
{
  "email": "existing@example.com",
  "password": "Password123!"
}
```
**Expected**: 400 Bad Request - "User already exists"

### Test 10: Login with Wrong Password
```json
{
  "email": "test@example.com",
  "password": "WrongPassword123!"
}
```
**Expected**: 401 Unauthorized - "Invalid email or password"

### Test 11: Weak Password
```json
{
  "email": "test@example.com",
  "password": "123"
}
```
**Expected**: 400 Bad Request - "Password does not meet requirements"

### Test 12: Get Cognito Login URL

**Purpose**: Generate Cognito hosted UI login URL for OAuth flow

1. **Create New Request**:
   - Method: `GET`
   - URL: `{{base_url}}/auth/login-url`

2. **Query Parameters** (optional):
   - `redirect_uri`: `http://localhost:8000/auth/callback`
   - `state`: `random_state_string_123`

3. **Expected Response** (200 OK):
   ```json
   {
     "success": true,
     "auth_url": "https://your-user-pool.auth.region.amazoncognito.com/login?client_id=xxx&response_type=code&scope=email+openid+phone+profile&redirect_uri=http://localhost:8000/auth/callback&state=random_state_string_123",
     "redirect_uri": "http://localhost:8000/auth/callback",
     "state": "random_state_string_123"
   }
   ```

### Test 13: Handle OAuth Callback (Success)

**Purpose**: Test successful OAuth callback after Cognito redirect

1. **Create New Request**:
   - Method: `GET`
   - URL: `{{base_url}}/auth/callback`

2. **Query Parameters**:
   - `code`: `authorization_code_from_cognito`
   - `state`: `random_state_string_123`

3. **Expected Response** (200 OK):
   - **Content-Type**: `text/html`
   - **Body**: HTML page with "Authentication Successful!" message
   - **Behavior**: Page automatically redirects to main dashboard (`/`) after 2 seconds
   - **Manual Redirect**: Link to main dashboard if auto-redirect fails

### Test 14: Handle OAuth Callback (Error)

**Purpose**: Test OAuth callback error handling

1. **Create New Request**:
   - Method: `GET`
   - URL: `{{base_url}}/auth/callback`

2. **Query Parameters**:
   - `error`: `access_denied`
   - `error_description`: `User denied access`
   - `state`: `random_state_string_123`

3. **Expected Response** (400 Bad Request):
   - **Content-Type**: `text/html`
   - **Body**: HTML error page with error details and "Try Again" button
   - **Error Display**: Shows the error type and description from Cognito
   - **Retry Action**: "Try Again" button links to `/auth/login`

## � OAuth Flow Testing

### Complete OAuth Flow Test

To test the complete OAuth flow:

1. **Step 1: Get Login URL**
   ```
   GET {{base_url}}/auth/login-url?redirect_uri=http://localhost:8000/auth/callback&state=test123
   ```

2. **Step 2: Copy the auth_url from response and open in browser**
   - User will be redirected to Cognito hosted UI
   - User can login or signup
   - After successful authentication, user is redirected back to your callback URL

3. **Step 3: Test the callback**
   - Extract the `code` parameter from the callback URL
   - Test the callback endpoint with the authorization code

4. **Step 4: Verify authentication**
   - Use the tokens to access protected routes

### OAuth Flow Environment Variables

Add these to your Postman environment for OAuth testing:

| Variable Name | Initial Value | Description |
|---------------|---------------|-------------|
| `oauth_state` | `test_state_123` | State parameter for OAuth security |
| `redirect_uri` | `http://localhost:8000/auth/callback` | OAuth callback URL |
| `authorization_code` | | (will be set from callback URL) |

### OAuth Flow Collection Script

Add this to your collection's Pre-request Script for OAuth flow automation:

```javascript
// OAuth Flow Helper
const oauthState = pm.environment.get("oauth_state") || "test_" + Math.random().toString(36).substr(2, 9);
pm.environment.set("oauth_state", oauthState);

// Log OAuth flow step
console.log("OAuth State:", oauthState);
console.log("Redirect URI:", pm.environment.get("redirect_uri"));
```

## �🔧 Troubleshooting

### Common Issues:

1. **"AWS credentials not configured"**
   - Ensure AWS credentials are set in environment or IAM role
   - Check AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY

2. **"COGNITO_USER_POOL_ID must be set"**
   - Update your `.env` file with correct Cognito settings
   - Restart the server after updating environment variables

3. **"Token validation failed"**
   - Check that your User Pool region matches the configuration
   - Verify JWKS endpoint is accessible

4. **Connection refused**
   - Ensure the server is running on port 8000
   - Check if there are any firewall restrictions

### Debug Tips:

1. **Check Server Logs**: Monitor the terminal where you started the server
2. **Validate Environment**: Use `GET /auth/config` to check configuration
3. **Test Network**: Use `GET /health` to verify server connectivity
4. **Check AWS Console**: Verify users are being created in Cognito

## 🎯 Advanced Testing

### Test Automation Script

Create a Postman test to automate the full flow:

```javascript
// Collection Pre-request Script
pm.test("Authentication Flow", function () {
    // This will run through the complete auth flow
    const signupRequest = {
        url: pm.environment.get("base_url") + "/auth/signup",
        method: "POST",
        header: {
            "Content-Type": "application/json"
        },
        body: {
            mode: "raw",
            raw: JSON.stringify({
                email: pm.environment.get("user_email"),
                password: pm.environment.get("user_password")
            })
        }
    };
    
    pm.sendRequest(signupRequest, function (err, response) {
        if (err) {
            console.log("Signup failed:", err);
        } else {
            console.log("Signup response:", response.json());
        }
    });
});
```

## 📝 Test Results Documentation

Keep track of your test results:

| Test Case | Status | Response Time | Notes |
|-----------|--------|---------------|-------|
| Signup | ✅ Pass | 250ms | User created successfully |
| Login | ✅ Pass | 180ms | Tokens received |
| Token Validation | ✅ Pass | 50ms | User info retrieved |
| Protected Route | ✅ Pass | 120ms | Access granted |
| Invalid Token | ✅ Pass | 30ms | Properly rejected |

## 🔄 Continuous Testing

Set up a monitor in Postman to run these tests automatically:

1. Go to your collection
2. Click **Monitor**
3. Set up schedule (e.g., every hour)
4. Configure notifications for failures

This will help you catch authentication issues early in development or production.

---

**Remember**: Always test in a development environment first, and never use real production credentials in Postman collections that might be shared.
