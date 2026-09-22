import urllib.request
import json

url = 'https://api.github.com/repos/bitsubhayu/AAGAM/actions/runs?per_page=20'
req = urllib.request.Request(url, headers={'User-Agent': 'AAGAM-Audit'})
try:
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode())
        print(f"Total workflow runs on GitHub: {data.get('total_count', 0)}")
        for run in data.get('workflow_runs', []):
            print(f"ID: {run['id']} | Name: {run.get('name')} | Event: {run.get('event')} | Branch: {run.get('head_branch')} | Status: {run.get('status')} | Conclusion: {run.get('conclusion')} | Created: {run.get('created_at')}")
except Exception as e:
    print('Error querying GitHub API:', e)
