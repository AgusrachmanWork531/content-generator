#!/usr/bin/env python3
import json

# Read
with open('n8n_node.json', 'r') as f:
    wf = json.load(f)

# Find and update node
for node in wf['nodes']:
    if node.get('name') == 'Prepare Telegram Payload':
        js = node['parameters']['jsCode']
        
        # Step 1
        js = js.replace(
            "const result = $input.first().json;\n\nconst chat_id",
            "const result = $input.first().json;\n\nconst STORAGE_BASE_DIR = '/Users/agusrachman/Documents/Codex/content-short/storage';\n\nconst chat_id"
        )
        
        # Step 2
        js = js.replace(
            "const videoPath =\n  watermarkedVideo.path ||\n  watermarkedVideo.file_path ||\n  watermarkedVideo.absolute_path;\n\nif (!videoPath) {",
            "const rawVideoPath =\n  watermarkedVideo.absolute_path ||\n  watermarkedVideo.file_path ||\n  watermarkedVideo.path;\n\nif (!rawVideoPath) {\n  throw new Error(`Path video tidak ditemukan dari file: ${JSON.stringify(watermarkedVideo)}`);\n}\n\nconst videoPath = rawVideoPath.startsWith('/')\n  ? rawVideoPath\n  : `${STORAGE_BASE_DIR}/${rawVideoPath}`;\n\nif (!videoPath) {"
        )
        
        node['parameters']['jsCode'] = js
        print("Updated")
        break

# Write
with open('n8n_node.json', 'w') as f:
    json.dump(wf, f, indent=2)

print("Done")
