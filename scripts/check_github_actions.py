import json
import subprocess
import urllib.request

p = subprocess.Popen(['git', 'credential', 'fill'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
out, _ = p.communicate(input='protocol=https\nhost=github.com\n\n')
token = None
for l in out.splitlines():
    if l.startswith('password='):
        token = l.split('=', 1)[1]

headers = {'Authorization': f'token {token}', 'User-Agent': 'AAGAM-Audit'}

# 1. Check Workflows
req = urllib.request.Request('https://api.github.com/repos/bitsubhayu/AAGAM/actions/workflows', headers=headers)
try:
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode())
        print(f"Total Workflows on GitHub: {data.get('total_count')}")
        for w in data.get('workflows', []):
            print(f"  Workflow ID: {w['id']} | Name: {w['name']} | State: {w['state']} | Path: {w['path']}")
except Exception as e:
    print('Workflows query error:', e)

# 2. Check Secrets
req2 = urllib.request.Request('https://api.github.com/repos/bitsubhayu/AAGAM/actions/secrets', headers=headers)
try:
    with urllib.request.urlopen(req2) as resp:
        data2 = json.loads(resp.read().decode())
        print(f"\nTotal Secrets on GitHub: {data2.get('total_count')}")
        for s in data2.get('secrets', []):
            print(f"  Secret: {s['name']}")
except Exception as e:
    print('Secrets query error:', e)
