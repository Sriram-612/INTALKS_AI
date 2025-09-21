# Amazon Cognito Authentication Integration Guide

## Overview

This guide explains how to set up and use the Amazon Cognito authentication system that has been integrated into your Voice Assistant Call Management System.

## 🔧 Setup Requirements

### 1. AWS Cognito User Pool Setup

Before using the authentication system, you need to create and configure an Amazon Cognito User Pool:

1. **Create a User Pool:**
   - Go to AWS Console → Cognito → User Pools
   - Click "Create user pool"
   - Choose "Email" as the sign-in option
   - Configure password policy as needed
   - Enable email verification

2. **Create an App Client:**
   - In your User Pool → App Integration → App clients
   - Click "Create app client"
   - Choose "Public client" (no client secret) or "Confidential client" (with secret)
   - Enable "USER_PASSWORD_AUTH" flow
   - Note down the **Client ID** (and **Client Secret** if applicable)

3. **Configure Your User Pool:**
   - Note down your **User Pool ID** 
   - Note down your **AWS Region**

### 2. Environment Configuration

Update your `.env` file with the following Cognito settings:

```bash
# Amazon Cognito Configuration
COGNITO_USER_POOL_ID="eu-north-1_XXXXXXXXX"        # Your User Pool ID
COGNITO_CLIENT_ID="1234567890abcdefghijk"          # Your App Client ID  
COGNITO_CLIENT_SECRET=""                           # Optional - only if using confidential client
AWS_REGION="eu-north-1"                           # Your AWS region (already set)
```

### 3. Required Dependencies

The following packages have been added to your `requirements.txt`:

```
PyJWT>=2.8.0
cryptography>=41.0.0
```

Install them with:
```bash
pip install PyJWT cryptography
```

## 🔒 Authentication System

### New Authentication Routes

The following authentication endpoints have been added to your application:

#### 1. User Registration
```
POST /auth/signup
```

#### 2. Email Confirmation (if required)
```
POST /auth/confirm-signup
```

#### 3. User Login
```
POST /auth/login
```

#### 4. Token Refresh
```
POST /auth/refresh
```

#### 5. User Logout
```
POST /auth/logout
```

#### 6. Get User Info
```
GET /auth/me
```

### Protected API Routes

Your existing API routes now require authentication:

- `POST /api/upload-customers` - Upload customer data (Protected)
- `POST /api/trigger-single-call` - Trigger single call (Protected)
- `POST /api/trigger-bulk-calls` - Trigger bulk calls (Protected)
- `GET /api/customers` - Get customer list (Protected)

### Unprotected Routes

These routes remain public (no authentication required):

- `GET /` - Dashboard (public)
- `GET /original` - Original dashboard (public)
- `GET /ws-url` - WebSocket URL generator (public)
- `GET /passthru-handler` - Exotel passthrough (public)
- `POST /exotel-webhook` - Exotel webhooks (public)
- WebSocket endpoints (public)

## 📝 Usage Examples

### 1. User Registration

```bash
curl -X POST "http://localhost:8000/auth/signup" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "SecurePassword123!",
    "first_name": "John",
    "last_name": "Doe"
  }'
```

**Response:**
```json
{
  "success": true,
  "message": "User registered successfully",
  "user_sub": "12345678-1234-1234-1234-123456789012",
  "confirmation_required": true
}
```

### 2. Email Confirmation (if required)

```bash
curl -X POST "http://localhost:8000/auth/confirm-signup" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "confirmation_code": "123456"
  }'
```

**Response:**
```json
{
  "success": true,
  "message": "User confirmed successfully"
}
```

### 3. User Login

```bash
curl -X POST "http://localhost:8000/auth/login" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "SecurePassword123!"
  }'
```

**Response:**
```json
{
  "success": true,
  "access_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
  "id_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "Bearer",
  "expires_in": 3600,
  "user": {
    "sub": "12345678-1234-1234-1234-123456789012",
    "username": "user@example.com",
    "email": "user@example.com",
    "email_verified": true
  }
}
```

### 4. Accessing Protected Routes

Use the `access_token` from login response in the Authorization header:

```bash
# Get customer list
curl -X GET "http://localhost:8000/api/customers" \
  -H "Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."

# Upload customers file  
curl -X POST "http://localhost:8000/api/upload-customers" \
  -H "Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..." \
  -F "file=@customers.csv"

# Trigger single call
curl -X POST "http://localhost:8000/api/trigger-single-call" \
  -H "Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..." \
  -H "Content-Type: application/json" \
  -d '{"customer_id": "12345"}'
```

### 5. Get Current User Info

```bash
curl -X GET "http://localhost:8000/auth/me" \
  -H "Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."
```

**Response:**
```json
{
  "success": true,
  "user": {
    "sub": "12345678-1234-1234-1234-123456789012",
    "username": "user@example.com",
    "email": "user@example.com",
    "email_verified": true,
    "token_use": "access",
    "scope": "openid email",
    "auth_time": 1672531200,
    "iat": 1672531200,
    "exp": 1672534800
  }
}
```

### 6. Token Refresh

```bash
curl -X POST "http://localhost:8000/auth/refresh" \
  -H "Content-Type: application/json" \
  -d '{
    "refresh_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."
  }'
```

### 7. Logout

```bash
curl -X POST "http://localhost:8000/auth/logout" \
  -H "Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."
```

## 🔧 Frontend Integration

### JavaScript Example

```javascript
class VoiceAssistantAuth {
  constructor(baseUrl = 'http://localhost:8000') {
    this.baseUrl = baseUrl;
    this.token = localStorage.getItem('access_token');
  }

  async signup(email, password, firstName, lastName) {
    const response = await fetch(`${this.baseUrl}/auth/signup`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        email,
        password,
        first_name: firstName,
        last_name: lastName
      })
    });
    
    return await response.json();
  }

  async login(email, password) {
    const response = await fetch(`${this.baseUrl}/auth/login`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ email, password })
    });
    
    const data = await response.json();
    
    if (data.success) {
      localStorage.setItem('access_token', data.access_token);
      localStorage.setItem('refresh_token', data.refresh_token);
      this.token = data.access_token;
    }
    
    return data;
  }

  async makeAuthenticatedRequest(url, options = {}) {
    const headers = {
      'Authorization': `Bearer ${this.token}`,
      'Content-Type': 'application/json',
      ...options.headers
    };

    const response = await fetch(`${this.baseUrl}${url}`, {
      ...options,
      headers
    });

    // Handle token expiration
    if (response.status === 401) {
      await this.refreshToken();
      // Retry the request with new token
      headers['Authorization'] = `Bearer ${this.token}`;
      return fetch(`${this.baseUrl}${url}`, { ...options, headers });
    }

    return response;
  }

  async refreshToken() {
    const refreshToken = localStorage.getItem('refresh_token');
    if (!refreshToken) {
      throw new Error('No refresh token available');
    }

    const response = await fetch(`${this.baseUrl}/auth/refresh`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ refresh_token: refreshToken })
    });

    const data = await response.json();
    
    if (data.success) {
      localStorage.setItem('access_token', data.access_token);
      this.token = data.access_token;
    }
    
    return data;
  }

  async logout() {
    if (this.token) {
      await fetch(`${this.baseUrl}/auth/logout`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${this.token}`
        }
      });
    }
    
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    this.token = null;
  }
}

// Usage example
const auth = new VoiceAssistantAuth();

// Login
const loginResult = await auth.login('user@example.com', 'password');
if (loginResult.success) {
  console.log('Logged in successfully');
  
  // Make authenticated requests
  const customersResponse = await auth.makeAuthenticatedRequest('/api/customers');
  const customers = await customersResponse.json();
  console.log('Customers:', customers);
}
```

## 🚨 Error Handling

The authentication system returns consistent error responses:

### Common Error Responses

```json
{
  "success": false,
  "message": "Invalid email or password"
}
```

### HTTP Status Codes

- `200` - Success
- `201` - Created (successful signup)
- `400` - Bad Request (invalid input, user already exists, etc.)
- `401` - Unauthorized (invalid credentials, expired token)
- `404` - Not Found (user not found)
- `500` - Internal Server Error

## 🔒 Security Features

1. **JWT Token Validation**: All tokens are validated against Cognito's JWKS endpoint
2. **Token Expiration**: Access tokens expire after 1 hour by default
3. **Refresh Tokens**: Long-lived tokens for getting new access tokens
4. **Password Policies**: Configurable through Cognito User Pool settings
5. **Email Verification**: Optional email verification for new users
6. **Rate Limiting**: Built into Cognito service
7. **Secure Headers**: Proper WWW-Authenticate headers for 401 responses

## 🛠️ Testing Your Setup

1. **Start your application:**
   ```bash
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```

2. **Test signup (replace with your Cognito config):**
   ```bash
   curl -X POST "http://localhost:8000/auth/signup" \
     -H "Content-Type: application/json" \
     -d '{"email": "test@example.com", "password": "TestPassword123!"}'
   ```

3. **Test login:**
   ```bash
   curl -X POST "http://localhost:8000/auth/login" \
     -H "Content-Type: application/json" \
     -d '{"email": "test@example.com", "password": "TestPassword123!"}'
   ```

4. **Test protected endpoint:**
   ```bash
   curl -X GET "http://localhost:8000/api/customers" \
     -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
   ```

## 📋 Next Steps

1. **Configure your Cognito User Pool** with the settings above
2. **Update your `.env` file** with the Cognito configuration
3. **Test the authentication flow** using the examples provided
4. **Update your frontend** to use the new authentication system
5. **Configure additional Cognito features** like MFA, custom attributes, etc.

## 🔧 Troubleshooting

### Common Issues

1. **"Cognito not configured" error**: Ensure all required environment variables are set
2. **Token validation fails**: Check that your User Pool ID and region are correct
3. **CORS issues**: The application already has CORS enabled for all origins
4. **User Pool not found**: Verify your AWS credentials and region settings

### Debug Tips

- Check application logs for detailed error messages
- Verify AWS credentials have proper Cognito permissions
- Test Cognito configuration using AWS CLI first
- Use AWS Cognito console to manually verify user creation

Your Voice Assistant application now has enterprise-grade authentication powered by Amazon Cognito!
