#!/usr/bin/env python3
"""Fix N8N Prepare Telegram Payload node for absolute file paths."""
import json

def main():
    with open('n8n_node.json', 'r') as f:
        wf = json.load(f)

    found = False
    for n in wf['nodes']:
        if n.get('name') == 'Prepare Telegram Payload':
            js = n['parameters']['jsCode']
            if 'const STORAGE_BASE_DIR' not in js:
                print('Not found, applying fix...')
                
                # Step 1: Add STORAGE_BASE_DIR after result = $input.first().json;
                old = 'const result = $input.first().json;\n\nconst chat_id'
                new = 'const result = $input.first().json;\n\nconst STORAGE_BASE_DIR = \'/Users/agusrachman/Documents/Codex/content-short/storage\';\n\nconst chat_id'
                if old in js:
                    js = js.replace(old, new)
                    print('Step 1 done')
                
                # Step 2: Update video path logic
                old2 = 'const videoPath =\n  watermarkedVideo.path ||\n  watermarkedVideo.file_path ||\n  watermarkedVideo.absolute_path;\n\nif (!videoPath) {'
                new2 = 'const rawVideoPath =\n  watermarkedVideo.absolute_path ||\n  watermarkedVideo.file_path ||\n  watermarkedVideo.path;\n\nif (!rawVideoPath) {\n  throw new Error(`Path video tidak ditemukan dari file: ${JSON.stringify(watermarkedVideo)}`);\n}\n\nconst videoPath = rawVideoPath.startsWith(\'/\')\n  ? rawVideoPath\n  : `${STORAGE_BASE_DIR}/${rawVideoPath}`;\n\nif (!videoPath) {'
                if old2 in js:
                    js = js.replace(old2, new2)
                    print('Step 2 done')
                
                n['parameters']['jsCode'] = js
                found = True
            else:
                print('Fix already applied')

    if found:
        with open('n8n_node.json', 'w') as f:
            json.dump(wf, f, indent=2)
        print('File saved')
    else:
        print('No changes made')

if __name__ == '__main__':
    main()
