#!/usr/bin/env python3
"""Apply fix to n8n_node.json for absolute path handling"""
import json

def main():
    # Load the file
    with open('n8n_node.json', 'r') as f:
        wf = json.load(f)

    # Find Prepare Telegram Payload node
    for node in wf['nodes']:
        if node.get('name') == 'Prepare Telegram Payload':
            js = node['parameters']['jsCode']
            print(f"Found node, JS length: {len(js)}")
            
            # Check current state
            has_storage = 'STORAGE_BASE_DIR' in js
            has_raw = 'rawVideoPath' in js
            
            print(f"Has STORAGE_BASE_DIR: {has_storage}")
            print(f"Has rawVideoPath: {has_raw}")
            
            # Step 1: Add STORAGE_BASE_DIR if not present
            if not has_storage:
                # Use simple string to find
                if "const result = $input.first().json;\n\nconst chat_id" in js:
                    js = js.replace(
                        "const result = $input.first().json;\n\nconst chat_id",
                        "const result = $input.first().json;\n\nconst STORAGE_BASE_DIR = '/Users/agusrachman/Documents/Codex/content-short/storage';\n\nconst chat_id"
                    )
                    print("Step 1: Added STORAGE_BASE_DIR")
            
            # Step 2: Update path logic
            if not has_raw:
                old = "const videoPath =\n  watermarkedVideo.path ||\n  watermarkedVideo.file_path ||\n  watermarkedVideo.absolute_path;\n\nif (!videoPath)"
                new = "const rawVideoPath =\n  watermarkedVideo.absolute_path ||\n  watermarkedVideo.file_path ||\n  watermarkedVideo.path;\n\nif (!rawVideoPath) {\n  throw new Error(`Path video tidak ditemukan dari file: ${JSON.stringify(watermarkedVideo)}`);\n}\n\nconst videoPath = rawVideoPath.startsWith('/')\n  ? rawVideoPath\n  : `${STORAGE_BASE_DIR}/${rawVideoPath}`;\n\nif (!videoPath)"
                
                if old in js:
                    js = js.replace(old, new)
                    print("Step 2: Updated path logic")
                else:
                    print("Old pattern not found, trying simpler replacement")
                    # Just change the variable name
                    if "const videoPath =\n  watermarkedVideo.path ||" in js:
                        js = js.replace(
                            "const videoPath =\n  watermarkedVideo.path ||\n  watermarkedVideo.file_path ||\n  watermarkedVideo.absolute_path;",
                            "const rawVideoPath =\n  watermarkedVideo.absolute_path ||\n  watermarkedVideo.file_path ||\n  watermarkedVideo.path;"
                        )
                        print("Step 2a: Renamed videoPath to rawVideoPath")
            
            # Update node
            node['parameters']['jsCode'] = js
            
            # Verify
            print(f"After fix - Has STORAGE_BASE_DIR: {'STORAGE_BASE_DIR' in js}")
            print(f"After fix - Has rawVideoPath: {'rawVideoPath' in js}")
            
            break
    else:
        print("Node not found!")
        return

    # Save
    with open('n8n_node.json', 'w') as f:
        json.dump(wf, f, indent=2)

    print("Saved!")

if __name__ == "__main__":
    main()
