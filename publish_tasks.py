"""Creates or updates the Actor tasks from tasks.json, runs each once and publishes it when the run succeeds.

Usage: python apify/publish_tasks.py [--no-publish] [<actor id> ...]   (default: all Actors in tasks.json)
Auth as in document-to-markdown/tools/deploy.py (APIFY_TOKEN or a proxy network secret).
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'document-to-markdown', 'tools'))
from deploy import call  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def run_task(task_id):
    r = call('POST', f'/actor-tasks/{task_id}/runs?waitForFinish=120')
    while r['status'] in ('READY', 'RUNNING'):
        time.sleep(5)
        r = call('GET', f"/actor-runs/{r['id']}?waitForFinish=60")
    items = call('GET', f"/datasets/{r['defaultDatasetId']}/items?clean=1") or []
    return r['status'] == 'SUCCEEDED' and items and not any(i.get('error') for i in items), r, items


def main():
    cfg = json.load(open(os.path.join(HERE, 'tasks.json'), encoding='utf-8'))
    publish = '--no-publish' not in sys.argv
    existing = {t['name']: t for t in call('GET', '/actor-tasks?limit=1000')['items']}
    only = [a for a in sys.argv[1:] if not a.startswith('--')]
    for act_id, tasks in cfg['actors'].items():
        if only and act_id not in only:
            continue
        for t in tasks:
            body = {
                'actId': act_id, 'name': t['name'], 'title': t['title'], 'description': t['description'],
                'input': {'sources': [{'url': cfg['sampleBase'] + s} for s in t['samples']], **t['input']},
                'options': {'memoryMbytes': 2048, 'timeoutSecs': 600},
                'publicConfig': {'seoTitle': t['title'][:60], 'seoDescription': t['description'][:160],
                                 'inputSchemaFields': t['fields'], 'datasetView': 'overview'},
            }
            if t['name'] in existing:
                task = call('PUT', f"/actor-tasks/{existing[t['name']]['id']}",
                            {k: v for k, v in body.items() if k not in ('actId', 'name')})
            else:
                task = call('POST', '/actor-tasks', body)
            ok, r, items = run_task(task['id'])
            status = 'run OK' if ok else f"run PROBLEM ({r['status']}, items={len(items)})"
            if ok and publish:
                task = call('PUT', f"/actor-tasks/{task['id']}", {'isPublic': True})
                status += ', published'
            print(f"{t['name']:34} {status}  {task.get('publishedAt') or ''}")


if __name__ == '__main__':
    main()
