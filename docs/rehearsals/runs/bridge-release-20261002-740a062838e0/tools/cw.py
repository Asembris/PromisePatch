import concurrent.futures as cf, hashlib, json, re, sys, time
from datetime import datetime, timezone
import boto3
G = "/promisepatch/prod"
start = int(datetime(2026, 10, 1, 21, 24, tzinfo=timezone.utc).timestamp() * 1000)
end = int(time.time() * 1000)
logs = boto3.client("logs", region_name="us-east-1")
streams, tok = [], None
while True:
    kw = {"logGroupName": G, "orderBy": "LastEventTime", "descending": True}
    if tok: kw["nextToken"] = tok
    r = logs.describe_log_streams(**kw)
    stop = False
    for s in r["logStreams"]:
        if s.get("lastEventTimestamp", 0) < start: stop = True; break
        streams.append(s["logStreamName"])
    tok = r.get("nextToken")
    if stop or not tok: break
def fetch(name):
    out, tok = [], None
    while True:
        kw = {"logGroupName": G, "logStreamName": name, "startTime": start, "endTime": end, "startFromHead": True}
        if tok: kw["nextToken"] = tok
        r = logs.get_log_events(**kw)
        out += [e["message"] for e in r["events"]]
        if r["nextForwardToken"] == tok: break
        tok = r["nextForwardToken"]
    return out
msgs = []
with cf.ThreadPoolExecutor(8) as ex:
    for m in ex.map(fetch, streams): msgs += m
hashes = set()
for m in msgs:
    for t in re.findall(r"[0-9]{6,15}", m) + re.findall(r"[A-Za-z0-9_:\-]{16,}", m):
        for v in {t, t[3:] if t.startswith("bot") else t}:
            hashes.add(hashlib.sha256(v.encode()).hexdigest())
report = {"streams": len(streams), "events": len(msgs),
          "token_shaped": sum(bool(re.search(r"v1\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}", m)) for m in msgs),
          "unredacted_query": sum(bool(re.search(r"approve=(?!REDACTED)", m)) for m in msgs),
          "unredacted_path": sum(bool(re.search(r"approval/(?!REDACTED)", m)) for m in msgs),
          "candidate_hashes": len(hashes)}
json.dump(report, open(sys.argv[1], "w"), indent=2)
open(sys.argv[2], "w").write("\n".join(sorted(hashes)))
print(json.dumps(report))
