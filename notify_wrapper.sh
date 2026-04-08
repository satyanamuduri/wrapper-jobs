#!/bin/bash
cd "$(dirname "$0")"
python3 job_agent.py "embedded C++ developer" -l "Stockholm" \
    --sources indeed linkedin --min-score 50 -o /tmp/jobs_latest.json 2>&1

count=$(python3 -c "import json; print(len(json.load(open('/tmp/jobs_latest.json'))))" 2>/dev/null || echo 0)

if [ "$count" -gt 0 ]; then
    osascript -e "display notification \"$count matching jobs found on Indeed & LinkedIn\" with title \"Job Agent\" sound name \"Glass\""
fi
