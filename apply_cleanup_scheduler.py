#!/usr/bin/env python3
"""Apply cleanup scheduler to api_server.py"""

import re
import json
import sys

def main():
    with open('api_server.py', 'r') as f:
        content = f.read()
    
    # Add timedelta
    if 'from datetime import datetime, timezone, timedelta' not in content:
        content = content.replace(
            'from datetime import datetime, timezone',
            'from datetime import datetime, timezone, timedelta'
        )
        print("Added timedelta import")
    else:
        print("timedelta already imported")
    
    # Find remove_download_archive_entry position
    pattern = r'(def remove_download_archive_entry\(video_id: str\) -> bool:.*?return False\n    except Exception:\n        return False)'
    match = re.search(pattern, content, re.DOTALL)
    
    if not match:
        print("ERROR: Could not find remove_download_archive_entry")
        sys.exit(1)
    
    insert_pos = match.end()
    
    new_code = '''

def perform_video_cleanup(
    video_id: str,
    delete_assets: bool,
    delete_artifacts: bool,
    delete_jobs: bool,
    delete_source_video: bool,
    delete_transcripts: bool,
) -> dict:
    """Reusable cleanup helper for both immediate and scheduled cleanup."""
    deleted_paths = []
    skipped_paths = []
    deleted_jobs_list = []
    deleted_subtitle_jobs = []

    if delete_assets:
        delete_storage_path(OUTPUT_DIR / video_id, deleted_paths, skipped_paths)

    if delete_source_video:
        for source_file in VIDEO_DIR.glob(f"*{video_id}*"):
            delete_storage_path(source_file, deleted_paths, skipped_paths)
        remove_download_archive_entry(video_id)

    if delete_transcripts:
        delete_storage_path(TRANSCRIPT_DIR / video_id, deleted_paths, skipped_paths)

    if delete_jobs:
        for job_id, job in list(jobs.items()):
            if job.get("video_id") == video_id or video_id in json.dumps(job, ensure_ascii=False):
                jobs.pop(job_id, None)
                deleted_jobs_list.append(job_id)

        for metadata_file in API_JOBS_DIR.glob("*.json"):
            if not json_file_mentions_video_id(metadata_file, video_id):
                continue
            job_id = metadata_file.stem
            for job_file in API_JOBS_DIR.glob(f"{job_id}*"):
                delete_storage_path(job_file, deleted_paths, skipped_paths)
            if job_id not in deleted_jobs_list:
                deleted_jobs_list.append(job_id)

        subtitle_jobs_dir = subtitle_settings.subtitle_output_dir
        if subtitle_jobs_dir.exists():
            for subtitle_job_dir in subtitle_jobs_dir.iterdir():
                if not subtitle_job_dir.is_dir():
                    continue
                input_file = subtitle_job_dir / "input.json"
                result_file = subtitle_job_dir / "result.json"
                if (
                    json_file_mentions_video_id(input_file, video_id)
                    or json_file_mentions_video_id(result_file, video_id)
                ):
                    delete_storage_path(subtitle_job_dir, deleted_paths, skipped_paths)
                    deleted_subtitle_jobs.append(subtitle_job_dir.name)

    if delete_artifacts and not delete_assets:
        skipped_paths.append({
            "path": str(OUTPUT_DIR / video_id),
            "reason": "delete_artifacts_requires_delete_assets_for_video_scoped_artifacts"
        })

    return {
        "status": "completed",
        "video_id": video_id,
        "deleted_paths": deleted_paths,
        "deleted_jobs": deleted_jobs_list,
        "deleted_subtitle_jobs": deleted_subtitle_jobs,
        "skipped_paths": skipped_paths,
    }


async def cleanup_scheduler_loop():
    """Background task to run scheduled cleanup."""
    while True:
        await asyncio.sleep(60)
        
        try:
            schedules = load_cleanup_schedules()
            if not schedules:
                continue
            
            now = datetime.now(timezone.utc)
            modified = False
            
            for video_id, schedule in list(schedules.items()):
                artifact_cleanup_done = schedule.get("artifact_cleanup_done", False)
                source_cleanup_done = schedule.get("source_cleanup_done", False)
                artifact_cleanup_at = schedule.get("artifact_cleanup_at")
                source_cleanup_at = schedule.get("source_cleanup_at")
                
                if not artifact_cleanup_done and artifact_cleanup_at:
                    try:
                        cleanup_time = datetime.fromisoformat(artifact_cleanup_at)
                        if now >= cleanup_time:
                            print(f"Running scheduled artifact cleanup for {video_id}")
                            result = perform_video_cleanup(
                                video_id=video_id,
                                delete_assets=True,
                                delete_artifacts=True,
                                delete_jobs=True,
                                delete_source_video=False,
                                delete_transcripts=True,
                            )
                            schedule["artifact_cleanup_done"] = True
                            modified = True
                            print(f"Artifact cleanup completed for {video_id}: {result.get('deleted_paths', [])}")
                    except Exception as e:
                        print(f"Error processing artifact cleanup for {video_id}: {e}")
                
                if not source_cleanup_done and source_cleanup_at:
                    try:
                        cleanup_time = datetime.fromisoformat(source_cleanup_at)
                        if now >= cleanup_time:
                            print(f"Running scheduled source cleanup for {video_id}")
                            result = perform_video_cleanup(
                                video_id=video_id,
                                delete_assets=False,
                                delete_artifacts=False,
                                delete_jobs=False,
                                delete_source_video=True,
                                delete_transcripts=False,
                            )
                            schedule["source_cleanup_done"] = True
                            modified = True
                            print(f"Source cleanup completed for {video_id}: {result.get('deleted_paths', [])}")
                    except Exception as e:
                        print(f"Error processing source cleanup for {video_id}: {e}")
                
                if schedule.get("artifact_cleanup_done") and schedule.get("source_cleanup_done"):
                    schedules.pop(video_id)
                    modified = True
                    print(f"Removed completed schedule for {video_id}")
            
            if modified:
                save_cleanup_schedules(schedules)
                
        except Exception as e:
            print(f"Cleanup scheduler error: {e}")
'''
    
    content = content[:insert_pos] + new_code + content[insert_pos:]
    print("Added perform_video_cleanup and cleanup_scheduler_loop")
    
    # Add startup event
    startup_code = '''

@app.on_event("startup")
async def start_cleanup_scheduler():
    """Start the background cleanup scheduler."""
    asyncio.create_task(cleanup_scheduler_loop())
'''
    
    health_pattern = r'(@app\.get\("/health"\))'
    health_match = re.search(health_pattern, content)
    
    if not health_match:
        print("ERROR: Could not find @app.get('/health')")
        sys.exit(1)
    
    insert_pos = health_match.start()
    content = content[:insert_pos] + startup_code + '\n' + content[insert_pos:]
    print("Added startup event for cleanup scheduler")
    
    # Add schedule endpoint
    schedule_endpoint = '''

@app.post("/jobs/cleanup/schedule")
async def schedule_cleanup(
    request: CleanupScheduleRequest,
    token: str = Depends(verify_token)
):
    """Schedule cleanup for video after Telegram delivery."""
    video_id = validate_cleanup_video_id(request.video_id)
    
    # Validate timing
    if request.artifact_cleanup_after_seconds < 60:
        raise HTTPException(
            status_code=400,
            detail="artifact_cleanup_after_seconds must be >= 60"
        )
    if request.source_cleanup_after_seconds < request.artifact_cleanup_after_seconds:
        raise HTTPException(
            status_code=400,
            detail="source_cleanup_after_seconds must be >= artifact_cleanup_after_seconds"
        )
    
    # Compute cleanup times
    now = datetime.now(timezone.utc)
    artifact_cleanup_at = now + timedelta(seconds=request.artifact_cleanup_after_seconds)
    source_cleanup_at = now + timedelta(seconds=request.source_cleanup_after_seconds)
    
    # Load existing schedules
    schedules = load_cleanup_schedules()
    
    # Upsert schedule
    schedules[video_id] = {
        "video_id": video_id,
        "artifact_cleanup_at": artifact_cleanup_at.isoformat(),
        "source_cleanup_at": source_cleanup_at.isoformat(),
        "artifact_cleanup_done": False,
        "source_cleanup_done": False,
        "created_at": now.isoformat(),
    }
    
    # Save schedules
    save_cleanup_schedules(schedules)
    
    return {
        "status": "scheduled",
        "video_id": video_id,
        "artifact_cleanup_at": artifact_cleanup_at.isoformat(),
        "source_cleanup_at": source_cleanup_at.isoformat(),
    }
'''
    
    root_pattern = r'(@app\.get\("/"\))'
    root_match = re.search(root_pattern, content)
    
    if not root_match:
        print("ERROR: Could not find @app.get('/')")
        sys.exit(1)
    
    insert_pos = root_match.start()
    content = content[:insert_pos] + schedule_endpoint + '\n' + content[insert_pos:]
    print("Added /jobs/cleanup/schedule endpoint")
    
    # Simplify cleanup_video_artifacts
    old_cleanup = '''@app.post("/jobs/cleanup/video")
async def cleanup_video_artifacts(
    request: CleanupVideoRequest,
    token: str = Depends(verify_token)
):
    """Delete stale assets, artifacts, and job records for a video."""
    video_id = validate_cleanup_video_id(request.video_id)
    deleted_paths: list[str] = []
    skipped_paths: list[dict] = []
    deleted_jobs: list[str] = []
    deleted_subtitle_jobs: list[str] = []

    if request.delete_assets:
        delete_storage_path(OUTPUT_DIR / video_id, deleted_paths, skipped_paths)

    if request.delete_source_video:
        for source_file in VIDEO_DIR.glob(f"*{video_id}*"):
            delete_storage_path(source_file, deleted_paths, skipped_paths)

    if request.delete_transcripts:
        delete_storage_path(TRANSCRIPT_DIR / video_id, deleted_paths, skipped_paths)

    if request.delete_jobs:
        for job_id, job in list(jobs.items()):
            if job.get("video_id") == video_id or video_id in json.dumps(job, ensure_ascii=False):
                jobs.pop(job_id, None)
                deleted_jobs.append(job_id)

        for metadata_file in API_JOBS_DIR.glob("*.json"):
            if not json_file_mentions_video_id(metadata_file, video_id):
                continue

            job_id = metadata_file.stem
            for job_file in API_JOBS_DIR.glob(f"{job_id}*"):
                delete_storage_path(job_file, deleted_paths, skipped_paths)
            if job_id not in deleted_jobs:
                deleted_jobs.append(job_id)

        subtitle_jobs_dir = subtitle_settings.subtitle_output_dir
        if subtitle_jobs_dir.exists():
            for subtitle_job_dir in subtitle_jobs_dir.iterdir():
                if not subtitle_job_dir.is_dir():
                    continue

                input_file = subtitle_job_dir / "input.json"
                result_file = subtitle_job_dir / "result.json"
                if (
                    json_file_mentions_video_id(input_file, video_id)
                    or json_file_mentions_video_id(result_file, video_id)
                ):
                    delete_storage_path(subtitle_job_dir, deleted_paths, skipped_paths)
                    deleted_subtitle_jobs.append(subtitle_job_dir.name)

    if request.delete_artifacts and not request.delete_assets:
        skipped_paths.append({
            "path": str(OUTPUT_DIR / video_id),
            "reason": "delete_artifacts_requires_delete_assets_for_video_scoped_artifacts"
        })

    return {
        "status": "completed",
        "video_id": video_id,
        "deleted_paths": deleted_paths,
        "deleted_jobs": deleted_jobs,
        "deleted_subtitle_jobs": deleted_subtitle_jobs,
        "skipped_paths": skipped_paths,
    }'''
    
    new_cleanup = '''@app.post("/jobs/cleanup/video")
async def cleanup_video_artifacts(
    request: CleanupVideoRequest,
    token: str = Depends(verify_token)
):
    """Delete stale assets, artifacts, and job records for a video."""
    video_id = validate_cleanup_video_id(request.video_id)
    
    return perform_video_cleanup(
        video_id=video_id,
        delete_assets=request.delete_assets,
        delete_artifacts=request.delete_artifacts,
        delete_jobs=request.delete_jobs,
        delete_source_video=request.delete_source_video,
        delete_transcripts=request.delete_transcripts,
    )'''
    
    content = content.replace(old_cleanup, new_cleanup)
    print("Updated cleanup_video_artifacts to use perform_video_cleanup")
    
    # Write
    with open('api_server.py', 'w') as f:
        f.write(content)
    
    print("SUCCESS: api_server.py updated")

if __name__ == '__main__':
    main()
