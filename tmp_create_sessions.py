import os, time, re
pwd=''
try:
    with open('.env', 'r', encoding='utf-8') as f:
        for line in f:
            m=re.match(r'\s*REDIS_PASSWORD\s*=\s*(\S+)', line)
            if m:
                pwd=m.group(1).strip()
                break
except Exception as e:
    print('Could not read .env:', e)
os.environ['CELERY_BROKER_URLS'] = f"redis://default:{pwd}@localhost:6380/0"
from swarm.celery_app import app
print('CELERY_BROKER_URLS used:', os.getenv('CELERY_BROKER_URLS'))
N = 12
session_ids = []
for i in range(N):
    res = app.send_task('browser.start', kwargs={}).get(timeout=30)
    sid = res.get('session_id')
    print(f'{i+1}/{N} started session {sid}')
    session_ids.append(sid)
    time.sleep(0.2)
print('Created sessions:', len(session_ids))
