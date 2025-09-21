# 📞 Agent Number Configuration Guide

## How to Change Agent Phone Number

### ✅ **Simple 3-Step Process:**

1. **Open the `.env` file** in your project root
2. **Find this line:**
   ```
   AGENT_PHONE_NUMBER="+917417119014"
   ```
3. **Change the number to your desired agent number:**
   ```
   AGENT_PHONE_NUMBER="+919876543210"  # Replace with your agent's number
   ```

### 🔄 **After Making Changes:**

1. **Save the `.env` file**
2. **Restart your application** (stop and start the server)
3. **All call transfers will now go to the new number**

### 📋 **Important Notes:**

- ✅ **Format**: Always include the country code (e.g., `+91` for India)
- ✅ **Quotes**: Keep the number in quotes
- ✅ **No Spaces**: Don't add spaces in the phone number
- ✅ **Valid Example**: `AGENT_PHONE_NUMBER="+919876543210"`
- ❌ **Invalid Example**: `AGENT_PHONE_NUMBER=9876543210` (missing + and country code)

### 🧪 **Test Your Configuration:**

Run this command to validate your setup:
```bash
python validate_agent_config.py
```

### 🔍 **Where Agent Number is Used:**

Your agent number is automatically used in:
- ✅ Call transfers when customers request agent assistance
- ✅ Call analysis and reporting
- ✅ Agent connection workflows
- ✅ All Exotel API calls

### 🎯 **Current Configuration:**

- **Agent Phone Number**: `+917417119014`
- **All files are properly configured** to use the environment variable
- **No hardcoded numbers** - everything is centralized in `.env`

---

**🎉 You're all set!** Just update the number in `.env` and restart the application whenever you need to change the agent number.
