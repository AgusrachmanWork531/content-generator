#!/usr/bin/env python3
"""Apply watermark delivery fix to n8n_watermark_delivery_only.json"""

import json
import uuid


def main():
    with open('n8n_watermark_delivery_only.json') as f:
        wf = json.load(f)

    # Get existing node names
    existing_names = {node["name"] for node in wf.get("nodes", [])}
    
    # Required nodes that must exist
    required = {
        "Prepare Telegram Payload",
        "Send a text message",
        "Download Watermark Video",
        "Send a video",
    }
    
    missing = required - existing_names
    if missing:
        print(f"ERROR: Missing required nodes: {sorted(missing)}")
        exit(1)
    
    # Find required node IDs
    node_ids = {}
    for node in wf["nodes"]:
        if node["name"] == "Prepare Telegram Payload":
            node_ids["prepare"] = node["id"]
        elif node["name"] == "Send a text message":
            node_ids["send_text"] = node["id"]
        elif node["name"] == "Download Watermark Video":
            node_ids["download_wm"] = node["id"]
        elif node["name"] == "Send a video":
            node_ids["send_video"] = node["id"]
    
    print(f"Found node IDs: {node_ids}")
    
    # Check if merge node already exists
    merge_node_id = None
    schedule_node_id = None
    
    for node in wf["nodes"]:
        if node["name"] == "Merge Telegram Delivery Success":
            merge_node_id = node["id"]
        elif node["name"] == "Schedule Cleanup After Delivery":
            schedule_node_id = node["id"]
    
    # Generate IDs if needed
    if not merge_node_id:
        merge_node_id = str(uuid.uuid4())
    if not schedule_node_id:
        schedule_node_id = str(uuid.uuid4())
    
    print(f"Using merge_node_id: {merge_node_id}")
    print(f"Using schedule_node_id: {schedule_node_id}")
    
    # Step 1: Update Prepare Telegram Payload code (only if not already updated)
    for node in wf.get('nodes', []):
        if node.get('name') == 'Prepare Telegram Payload':
            # Check if already has the new code with "fallback to local storage"
            current_code = node.get('parameters', {}).get('jsCode', '')
            if 'fallback to local storage' not in current_code:
                new_code = '''// Prepare Telegram Payload (with fallback to local storage)
const original = $('Code in JavaScript2').first().json;
const result = $input.first().json;

const API_BASE_URL = 'https://authentic-linguist-scoundrel.ngrok-free.dev';

const chat_id = original.telegram?.chat_id;
if (!chat_id) {
  throw new Error('chat_id tidak ditemukan dari payload Telegram');
}

const yt = original.render_payload?.youtube_metadata;
if (!yt) {
  throw new Error('youtube_metadata tidak ditemukan dari render_payload');
}

const video_id = original.video_id;
let files = result.files || [];

// FIX: If files is empty, use local storage path directly
let watermarkedVideo = null;
if (files.length === 0) {
  const wmPath = `free-viral-shorts/${video_id}/watermarked`;
  watermarkedVideo = {
    filename: `${video_id}_wm.mp4`,
    path: wmPath,
    absolute_path: wmPath,
    download_url: `${API_BASE_URL}/storage/free-viral-shorts/${video_id}/watermarked/${video_id}_wm.mp4`
  };
  console.log('[FALLBACK] Using local storage path:', wmPath);
} else {
  watermarkedVideo =
    files.find(file =>
      file.filename?.endsWith('.mp4') &&
      (file.filename.includes('_wm') || file.path?.includes('/watermarked/'))
    ) ||
    files.find(file => file.filename?.endsWith('.mp4'));
}

if (!watermarkedVideo) {
  throw new Error(`File video watermark tidak ditemukan. files=${JSON.stringify(files)}`);
}

const rawVideoPath = watermarkedVideo.absolute_path || watermarkedVideo.file_path || watermarkedVideo.path;
const video_path = rawVideoPath?.startsWith('/') ? rawVideoPath : rawVideoPath ? `/Users/agusrachman/Documents/Codex/content-short/storage/${rawVideoPath}` : null;

const video_download_url = watermarkedVideo.download_url || (watermarkedVideo.url ? `${API_BASE_URL}${watermarkedVideo.url}` : null);

if (!video_download_url) {
  throw new Error(`Download URL video tidak ditemukan: ${JSON.stringify(watermarkedVideo)}`);
}

const hashtags = Array.isArray(yt.hashtags) ? yt.hashtags.join(' ') : '';
const hookText = original.render_payload?.hook_3_5_seconds?.text || '-';
const thumbnailText = yt.thumbnail_text || '-';
const viralScore = original.render_payload?.viral_score ?? '-';
const clipType = original.render_payload?.clip_type || '-';
const duration = original.render_payload?.duration || original.render_payload?.calculated_duration || '-';

const caption = [yt.title || 'Video pendek', hashtags].filter(Boolean).join('\n\n').slice(0, 1024);

const metadata_text = [
  '✅ Render Watermark Selesai',
  '', `🎬 Title:\n${yt.title || '-'}`,
  '', `📝 Description:\n${yt.description || '-'}`,
  '', `🏷 Hashtags:\n${hashtags || '-'}`,
  '', `🖼 Thumbnail Text:\n${thumbnailText}`,
  '', `🪝 Hook:\n${hookText}`,
  '', `⭐ Viral Score:\n${viralScore}`,
  '', `🎭 Clip Type:\n${clipType}`,
  '', `⏱ Duration:\n${duration} detik`,
  '', `🔗 Source Video ID:\n${video_id}`,
  '', `📁 File:\n${watermarkedVideo.filename || video_path || video_download_url}`,
  '', `⬇️ Download:\n${video_download_url}`
].join('\n');

return [{
  json: { chat_id, video_id, video_path, video_download_url, caption, metadata_text, filename: watermarkedVideo.filename || video_path || video_download_url }
}];'''
                node['parameters']['jsCode'] = new_code
                print('Updated Prepare Telegram Payload code')
            else:
                print('Prepare Telegram Payload code already updated')
            break
    
    # Step 2: Add Merge node if not exists
    if "Merge Telegram Delivery Success" not in existing_names:
        merge_node = {
            "parameters": {
                "mode": "wait",
                "discardWorkflow": False
            },
            "type": "n8n-nodes-base.merge",
            "typeVersion": 3.3,
            "position": [7040, 6176],
            "id": merge_node_id,
            "name": "Merge Telegram Delivery Success"
        }
        wf["nodes"].append(merge_node)
        print("Added Merge Telegram Delivery Success node")
    else:
        print("Merge Telegram Delivery Success node already exists")
    
    # Step 3: Add Schedule Cleanup After Delivery node if not exists
    if "Schedule Cleanup After Delivery" not in existing_names:
        schedule_node = {
            "parameters": {
                "url": "https://authentic-linguist-scoundrel.ngrok-free.dev/jobs/cleanup/schedule",
                "method": "POST",
                "sendHeaders": True,
                "headerParameters": {
                    "parameters": [
                        {"name": "Authorization", "value": "Bearer change-me"},
                        {"name": "Content-Type", "value": "application/json"}
                    ]
                },
                "sendBody": True,
                "bodyParameters": {
                    "parameters": [
                        {
                            "name": "body",
                            "value": "={{ JSON.stringify({ video_id: $('Prepare Telegram Payload').first().json.video_id, artifact_cleanup_after_seconds: 600, source_cleanup_after_seconds: 1200 }) }}"
                        }
                    ]
                },
                "options": {}
            },
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.3,
            "position": [7232, 6176],
            "id": schedule_node_id,
            "name": "Schedule Cleanup After Delivery"
        }
        wf["nodes"].append(schedule_node)
        print("Added Schedule Cleanup After Delivery node")
    else:
        print("Schedule Cleanup After Delivery node already exists")
    
    # Step 4: Update connections to route through merge node
    new_connections = {
        "Prepare Telegram Payload": {
            "main": [
                [
                    {"node": node_ids["send_text"], "type": "main", "index": 0},
                    {"node": node_ids["download_wm"], "type": "main", "index": 0}
                ]
            ]
        },
        "Download Watermark Video": {
            "main": [
                [{"node": node_ids["send_video"], "type": "main", "index": 0}]
            ]
        },
        "Send a text message": {
            "main": [
                [{"node": merge_node_id, "type": "main", "index": 0}]
            ]
        },
        "Send a video": {
            "main": [
                [{"node": merge_node_id, "type": "main", "index": 0}]
            ]
        },
        merge_node_id: {
            "main": [
                [{"node": schedule_node_id, "type": "main", "index": 0}]
            ]
        }
    }
    
    wf["connections"] = new_connections
    print("Updated connections")
    
    # Save
    with open('n8n_watermark_delivery_only.json', 'w') as f:
        json.dump(wf, f, indent=2)
    
    print('Saved n8n_watermark_delivery_only.json')
    print('SUCCESS: All fixes applied')


if __name__ == '__main__':
    main()
