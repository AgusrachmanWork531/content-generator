#!/usr/bin/env python3
import asyncio
from fastapi import BackgroundTasks

import api_server

captured = {}

def fake_create_step_job(*, step, request_data, background_tasks, cmd, video_id):
    captured.update(
        step=step,
        request_data=request_data,
        cmd=cmd,
        video_id=video_id,
    )
    return {
        "job_id": "fake",
        "step": step,
        "status_url": "/jobs/fake",
        "result_url": "/jobs/fake/result",
    }

api_server.create_step_job = fake_create_step_job

request = api_server.StepRequest(
    source="https://youtu.be/lo6KE0Kcvoc",
    num_clips=3,
    quality="1080",
    languages="id,en",
    render_payload={
        "start": 5.16,
        "end": 32.96,
        "duration": 999,
        "selected_transcript": [],
    },
)

response = asyncio.run(api_server.create_render_job(request, BackgroundTasks(), token="test"))

assert response["render_payload"]["start"] == 5.16
assert "--crop-start" in captured["cmd"]
assert "--crop-end" in captured["cmd"]
assert captured["request_data"]["render_payload"]["duration"] == 27.8
assert "render_payload_path" in captured["request_data"]

payload_path = api_server.STORAGE_DIR / captured["request_data"]["render_payload_path"]
assert payload_path.exists()

print("ok", payload_path)
