# Google Sheets Setup (one-time)

## Step 1 – Create a Google Cloud project
1. Go to https://console.cloud.google.com
2. Click "New Project" → name it anything (e.g. "JobSearch")
3. Select the project

## Step 2 – Enable APIs
1. Go to APIs & Services → Library
2. Search and enable **Google Sheets API**
3. Search and enable **Google Drive API**

## Step 3 – Create a service account
1. Go to APIs & Services → Credentials
2. Click "Create Credentials" → Service Account
3. Name it anything (e.g. "job-search-bot") → Done
4. Click the service account → Keys tab → Add Key → JSON
5. Download the JSON file
6. Rename it to `google_credentials.json`
7. Move it to `D:\Joe\Resume\google_credentials.json`

## Step 4 – Create the Google Sheet
1. Go to https://sheets.google.com
2. Create a new blank spreadsheet
3. Name it exactly: **Remote Job Leads – Youssef**
4. Open your `google_credentials.json` and find `"client_email"`
5. In the spreadsheet → Share → paste that email → Editor → Done

## Step 5 – Run the script
```
python -X utf8 D:\Joe\Resume\job_search.py
```
The script will auto-create the header row and start appending new jobs.

## Access from anywhere
Bookmark the Google Sheets URL on your phone, tablet, or any browser.
The "Status" column is yours to fill in: Applied / Interested / Skip / etc.
