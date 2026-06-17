# Playbook: Deploy QuotaLedger
When: any change to tracker/site/ (including site/data/*.json refreshes).

1. Ensure fresh data is copied: tracker/data/*.json → tracker/site/data/
2. Run via bash: `bash <Master mount>/Engine/tracker/scripts/deploy.sh`
   - Script sources secrets/cloudflare.env (scoped engine-deploy token), installs wrangler to /tmp/wr if missing (~30s), deploys to Pages project `quotaledger`, branch main.
3. Verify: fetch https://quotaledger.pages.dev — confirm new snapshot date renders. quotaledger.com is the proxied custom domain (CNAME, SSL auto).
4. Log the deployment URL in RUNLOG.
Failure modes: token revoked → propose re-mint in DIGEST (credential-minting playbook); wrangler install timeout → retry once, then deploy via Pages Direct Upload API with curl.
