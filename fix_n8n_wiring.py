#!/usr/bin/env python3
"""
Fix n8n_post_content.json wiring to preserve payload across notification nodes.

The problem: Telegram notification nodes are being used as serial bridge nodes, 
outputting Telegram API response instead of the original job payload.

The fix: 
- Build Notify nodes connect to BOTH Notify node AND next main workflow node
- Notify nodes do NOT continue the main workflow (they are side effects only)
"""

import json

def main():
    with open('n8n_post_content.json') as f:
        data = json.load(f)

    connections = data.get('connections', {})

    # Build Notify nodes: connect to both Notify AND main workflow node
    fixes = {
        "Build Notify Render Started": {
            "main": [[
                {"node": "Notify Render Started", "type": "main", "index": 0},
                {"node": "Remap Render Job ID", "type": "main", "index": 0}
            ]]
        },
        "Build Notify Render Completed": {
            "main": [[
                {"node": "Notify Render Completed", "type": "main", "index": 0},
                {"node": "Trigger Opening Narration", "type": "main", "index": 0}
            ]]
        },
        "Build Notify Opening Started": {
            "main": [[
                {"node": "Notify Opening Started", "type": "main", "index": 0},
                {"node": "Cek Status Opening", "type": "main", "index": 0}
            ]]
        },
        "Build Notify Opening Completed": {
            "main": [[
                {"node": "Notify Opening Completed", "type": "main", "index": 0},
                {"node": "Trigger Subtitle Generator", "type": "main", "index": 0}
            ]]
        },
        "Build Notify Subtitle Started": {
            "main": [[
                {"node": "Notify Subtitle Started", "type": "main", "index": 0},
                {"node": "Cek Status Subtitle", "type": "main", "index": 0}
            ]]
        },
        "Build Notify Subtitle Completed": {
            "main": [[
                {"node": "Notify Subtitle Completed", "type": "main", "index": 0},
                {"node": "Trigger Watermark", "type": "main", "index": 0}
            ]]
        },
        "Build Notify Watermark Started": {
            "main": [[
                {"node": "Notify Watermark Started", "type": "main", "index": 0},
                {"node": "Cek Status Watermark", "type": "main", "index": 0}
            ]]
        },
        "Build Notify Watermark Completed": {
            "main": [[
                {"node": "Notify Watermark Completed", "type": "main", "index": 0},
                {"node": "Get Watermark Result1", "type": "main", "index": 0}
            ]]
        },
        "Build Notify Delivery Started": {
            "main": [[
                {"node": "Notify Delivery Started", "type": "main", "index": 0},
                {"node": "Send a text message1", "type": "main", "index": 0},
                {"node": "Download Watermark Video1", "type": "main", "index": 0}
            ]]
        },
    }

    # Notify nodes: should NOT continue main workflow (clear connections)
    notify_nodes_to_clear = [
        "Notify Render Started",
        "Notify Render Completed",
        "Notify Opening Started",
        "Notify Opening Completed",
        "Notify Subtitle Started",
        "Notify Subtitle Completed",
        "Notify Watermark Started",
        "Notify Watermark Completed",
        "Notify Delivery Started",
    ]

    # Apply fixes to Build Notify nodes
    for node_name, new_conn in fixes.items():
        if node_name in connections:
            print(f"Updating {node_name}")
            connections[node_name] = new_conn
        else:
            print(f"WARNING: {node_name} not found in connections!")

    # Clear Notify nodes (set to empty main connection)
    for node_name in notify_nodes_to_clear:
        if node_name in connections:
            connections[node_name] = {"main": [[]]}
            print(f"Cleared {node_name}")
        else:
            print(f"WARNING: {node_name} not found in connections!")

    # Write the fixed JSON
    with open('n8n_post_content.json', 'w') as f:
        json.dump(data, f, indent=2)

    print("\nDone! File written.")

    # Verification
    print("\n=== Verification ===")
    for node_name in list(fixes.keys())[:3]:
        print(f"{node_name}: {json.dumps(connections.get(node_name, {}))}")
    for node_name in notify_nodes_to_clear[:3]:
        print(f"{node_name}: {json.dumps(connections.get(node_name, {}))}")

if __name__ == "__main__":
    main()
