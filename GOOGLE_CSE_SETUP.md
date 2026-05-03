# Google Custom Search Setup (one-time, ~10 minutes)

Free tier: 100 queries/day. The script uses ~26/day per run × 2 runs = 52/day — well within limit.

---

## Step 1 – Create the Search Engine

1. Go to https://programmablesearchengine.google.com
2. Click **"Add"**
3. Under **"Sites to search"**, add each domain below one by one
4. Name it anything (e.g. "Job Search – Youssef")
5. Click **Create**, then **Customize** on the next screen
6. Copy the **Search engine ID** shown at the top (looks like `abc123:xyz789`)

### Domains to add (paste each on its own line)

**ATS platforms – company jobs hosted here:**
```
boards.greenhouse.io
jobs.lever.co
jobs.ashbyhq.com
apply.workable.com
careers.smartrecruiters.com
jobs.jobvite.com
```

**HRMS / Payroll SaaS companies (Youssef's niche):**
```
deel.com
remote.com
oysterhr.com
rippling.com
gusto.com
hibob.com
personio.com
lattice.com
bamboohr.com
darwinbox.com
keka.com
chargebee.com
freshworks.com
zendesk.com
workato.com
zapier.com
hubspot.com
intercom.com
salesloft.com
gong.io
monday.com
clickup.com
atlassian.com
salesforce.com
servicenow.com
workday.com
sap.com
oracle.com
sage.com
netsuite.com
bill.com
brex.com
ramp.com
airbase.com
expensify.com
stripe.com
```

That's 42 domains — 8 slots left to add any company you want later.

---

## Step 2 – Get an API key

1. Go to https://console.cloud.google.com
2. Select (or create) any project
3. **APIs & Services → Library** → search **Custom Search API** → Enable it
4. **APIs & Services → Credentials → Create Credentials → API key**
5. Copy the key

---

## Step 3 – Save credentials

Create `D:\Joe\Resume\google_cse.json`:

```json
{
  "api_key": "YOUR_API_KEY_HERE",
  "cx": "YOUR_SEARCH_ENGINE_ID_HERE"
}
```

---

## Step 4 – Run

```
python -X utf8 D:\Joe\Resume\job_search.py
```

The script will print `Search: Google CSE` — you'll get real results from those 42 sites.

---

## Adding more companies later

Go to https://programmablesearchengine.google.com → your engine → **Setup** → add domains.
You can use wildcards like `*.mycompany.com` to cover subdomains.
