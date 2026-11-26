# Deployment Information

## Public URL
https://day14-ai-agent-0x1a.onrender.com

## Platform
Render (Free Web Service using Docker from `06-lab-complete/Dockerfile` + Free Render Key Value / Redis)

## Test Commands

### Health Check (Liveness)
```bash
curl https://day14-ai-agent-0x1a.onrender.com/health
# Expected: {"status":"ok","environment":"production"}
```

### Readiness Check (Redis connection)
```bash
curl https://day14-ai-agent-0x1a.onrender.com/ready
# Expected: {"status":"ready"}
```

### Authentication Check (without API key → 401)
```bash
curl -sS -o /dev/null -w '%{http_code}\n' -X POST https://day14-ai-agent-0x1a.onrender.com/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "Hello"}'
# Expected: 401
```

### API Test (with authentication → 200)
```bash
curl -X POST https://day14-ai-agent-0x1a.onrender.com/ask \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "Hello"}'
# Expected: 200 {"question":"Hello","answer":"..."}
```

## Environment Variables Set
- `PORT` (injected automatically by Render, e.g., `10000`)
- `ENVIRONMENT=production`
- `REDIS_URL` (Internal Render Key Value / Redis URL)
- `AGENT_API_KEY` (set securely in Render Dashboard)
- `RATE_LIMIT_PER_MINUTE=10`
- `DAILY_BUDGET_USD=1.0`

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
