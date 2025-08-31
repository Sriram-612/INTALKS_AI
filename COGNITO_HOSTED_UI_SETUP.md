# Amazon Cognito Hosted UI Setup Guide

## 🎯 Overview
This guide helps you complete the Amazon Cognito hosted UI setup for your Voice Assistant application deployed on AWS. When properly configured, visitors to your domain will be automatically redirected to Amazon Cognito's hosted login/signup UI.

## ✅ What's Already Done
- ✅ Cognito hosted UI authentication module created (`utils/cognito_hosted_auth.py`)
- ✅ Main application updated to redirect unauthenticated users to Cognito login
- ✅ OAuth callback handling implemented (`/auth/callback`)
- ✅ Logout functionality with Cognito hosted UI (`/auth/logout`)
- ✅ User info endpoint (`/auth/me`)
- ✅ Required packages installed (PyJWT, httpx)

## 🔧 Final Configuration Steps

### Step 1: Update Your AWS Domain URLs
Update these values in your `.env` file with your actual AWS domain:

```bash
# Replace "https://your-domain.com" with your actual AWS domain
COGNITO_REDIRECT_URI="https://YOUR-ACTUAL-DOMAIN.com/auth/callback"
COGNITO_LOGOUT_URI="https://YOUR-ACTUAL-DOMAIN.com/"
```

### Step 2: Configure Cognito App Client in AWS Console

1. **Go to AWS Cognito Console:**
   - Navigate to Amazon Cognito in AWS Console
   - Select your User Pool: `ap-south-1_MYtre8r4L`
   - Go to "App Integration" → "App clients and analytics"
   - Click on your app client: `6vvpsk667mdsq42kqlokc25il`

2. **Update Hosted UI Settings:**
   - Click "Edit" in the Hosted UI section
   - **Allowed callback URLs:** Add your domain
     ```
     https://YOUR-ACTUAL-DOMAIN.com/auth/callback
     ```
   - **Allowed sign-out URLs:** Add your domain
     ```
     https://YOUR-ACTUAL-DOMAIN.com/
     ```
   - **OAuth 2.0 grant types:** Ensure "Authorization code grant" is selected
   - **OAuth scopes:** Ensure these are selected:
     - `openid`
     - `email`
     - `profile`

3. **Save the configuration**

### Step 3: Test the Authentication Flow

1. **Deploy your updated application to AWS**

2. **Test the flow:**
   - Visit your domain: `https://YOUR-ACTUAL-DOMAIN.com`
   - You should be redirected to Cognito hosted UI for login/signup
   - After successful authentication, you should be redirected back to your dashboard

## 🔄 How It Works

### Authentication Flow:
1. **User visits your domain** → `https://YOUR-DOMAIN.com/`
2. **App checks authentication** → Not authenticated
3. **Redirects to Cognito** → `https://ap-south-1mytre8r4l.auth.ap-south-1.amazoncognito.com/login`
4. **User logs in/signs up** → Cognito hosted UI
5. **Cognito redirects back** → `https://YOUR-DOMAIN.com/auth/callback?code=...`
6. **App exchanges code for tokens** → Stores user in session
7. **User redirected to dashboard** → `https://YOUR-DOMAIN.com/`

### Key Endpoints:
- **`/`** - Main dashboard (requires authentication)
- **`/auth/callback`** - OAuth callback handler
- **`/auth/logout`** - Logout and redirect to Cognito logout
- **`/auth/me`** - Get current user info

## 🛠️ Troubleshooting

### Common Issues:

1. **"Invalid redirect URI" error:**
   - Check that callback URLs in Cognito match your `.env` file exactly
   - Ensure HTTPS is used (required for production)

2. **"Token exchange failed" error:**
   - Verify CLIENT_SECRET is correct in `.env`
   - Check that authorization code grant is enabled in Cognito

3. **User not redirected after login:**
   - Verify COGNITO_REDIRECT_URI points to your actual domain
   - Check callback URL configuration in Cognito

### Debug Information:
- Check logs for detailed error messages
- Cognito User Pool ID: `ap-south-1_MYtre8r4L`
- Cognito App Client ID: `6vvpsk667mdsq42kqlokc25il`
- Cognito Domain: `https://ap-south-1mytre8r4l.auth.ap-south-1.amazoncognito.com`

## 🚀 Next Steps After Setup

1. **Update environment variables** with your actual domain
2. **Configure Cognito callback URLs** in AWS Console  
3. **Deploy to AWS** and test the authentication flow
4. **Monitor logs** for any authentication issues

## 📝 Configuration Example

Here's how your `.env` should look after setup:

```bash
# Replace with your actual domain
COGNITO_REDIRECT_URI="https://myvoiceapp.example.com/auth/callback"
COGNITO_LOGOUT_URI="https://myvoiceapp.example.com/"

# These remain the same
COGNITO_USER_POOL_ID="ap-south-1_MYtre8r4L"
COGNITO_CLIENT_ID="6vvpsk667mdsq42kqlokc25il"
COGNITO_CLIENT_SECRET="a78uufrt4cf4566q0eugtmp6a4s02t71avjoo176gcq090inhvo"
COGNITO_DOMAIN="https://ap-south-1mytre8r4l.auth.ap-south-1.amazoncognito.com"
```

Once these steps are complete, your Voice Assistant application will have full Cognito hosted UI authentication where all visitors are redirected to login before accessing the dashboard!
