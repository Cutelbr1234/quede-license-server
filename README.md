# QUEDE License Server

## Deploy to Railway

### Step 1 — Push to GitHub
1. Create a new repo on github.com called `quede-license-server`
2. Upload these files to it

### Step 2 — Deploy on Railway
1. Go to railway.app and sign up with your GitHub account
2. Click "New Project" → "Deploy from GitHub repo"
3. Select `quede-license-server`
4. Railway auto-detects Python and deploys

### Step 3 — Add PostgreSQL database
1. In your Railway project click "New" → "Database" → "PostgreSQL"
2. Railway automatically sets DATABASE_URL in your environment

### Step 4 — Set environment variables
In Railway → your service → Variables, add:

```
SECRET_KEY=any-random-long-string
ADMIN_PASSWORD=your-secret-admin-password
STRIPE_SECRET_KEY=sk_live_... (from Stripe dashboard)
STRIPE_WEBHOOK_SECRET=whsec_... (from Stripe webhook setup)
STRIPE_SOLO_PRICE_ID=price_... (from Stripe product setup)
STRIPE_TEAM_PRICE_ID=price_... (from Stripe product setup)
SMTP_HOST=smtp.gmail.com (optional - for sending license emails)
SMTP_PORT=587
SMTP_USER=your@email.com
SMTP_PASS=your-app-password
```

### Step 5 — Get your server URL
Railway gives you a URL like: `https://quede-license-server.up.railway.app`
Add this to the QUEDE app as LICENSE_SERVER_URL.

## Admin Dashboard
Visit your Railway URL in a browser.
Enter your ADMIN_PASSWORD when prompted.
You can generate keys manually, deactivate/reactivate licenses, and see stats.

## API Endpoints

POST /validate — validates a license key
  Body: { "key": "QUEDE-XXXX-XXXX-XXXX" }
  Returns: { "valid": true, "plan": "solo", "max_users": 1 }

POST /admin/generate — generate a new key (admin only)
POST /admin/deactivate — deactivate a key (admin only)
POST /admin/reactivate — reactivate a key (admin only)
GET /admin/licenses — list all licenses (admin only)
GET /admin/stats — revenue and usage stats (admin only)
