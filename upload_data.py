import requests
import urllib.parse
import os
import json

with open(os.path.expanduser('~/.config/configstore/firebase-tools.json'), 'r') as f:
    config = json.load(f)
    token = config['tokens']['access_token']

bucket = 'jobhunter-23070.firebasestorage.app'
files = [
    'jobs.jsonl', 'status.json', 'config.json', 'job_feedback.json', 'seen_jobs.json',
    'saved_searches.json', 'google_credentials.json', 'google_cse.json', 'serpapi.json',
    'anthropic_key.json', 'gemini_key.json', 'grok_key.json', 'groq_key.json', 'xai_key.json'
]

for f in files:
    if not os.path.exists(f):
        print(f"Skipping {f}, doesn't exist.")
        continue
    
    url = f"https://storage.googleapis.com/upload/storage/v1/b/{bucket}/o?uploadType=media&name={urllib.parse.quote(f, safe='')}"
    
    with open(f, 'rb') as data:
        resp = requests.post(
            url, 
            headers={
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            },
            data=data
        )
        print(f"{f}: {resp.status_code} {resp.text}")
