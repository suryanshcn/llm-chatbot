# Deploy checklist
**Backend (Fly.io, keeps a persistent /data volume for SQLite)**
1. `cd backend && fly launch --no-deploy --copy-config` (edit `app` name in fly.toml)
2. `fly volumes create data --size 1`
3. `fly secrets set LLM_API_KEYS=key1,key2 ALLOWED_ORIGINS=https://YOUR-FRONTEND-URL`
4. `fly deploy` then `curl https://<app>.fly.dev/health`
(`ENABLE_FAILURE_SIMULATION=true` is already in fly.toml.) Render's free tier has no persistent disk, so history would reset on restart.

**Frontend (Vercel/Netlify/Cloudflare Pages)**
Root dir `frontend`, build `npm run build`, output `dist`, env var `VITE_API_BASE_URL=https://<app>.fly.dev`.
Then update `ALLOWED_ORIGINS` on the backend with the final frontend URL.
