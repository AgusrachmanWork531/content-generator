#!/usr/bin/env python3
"""
Add connections for all notification nodes in n8n_post_content.json
Following the TODO plan for notification flow
"""

import json

# Load workflow
with open('n8n_post_content.json', 'r') as f:
    workflow = json.load(f)

# Get node name to ID mapping
node_name_to_id = {node['name']: node['id'] for node in workflow['nodes']}
id_to_name = {node['id']: node['name'] for node in workflow['nodes']}

# Get existing connections
connections = workflow.get('connections', {})

# Add new connections following the TODO plan

# Render Flow Connections:
# HTTP Request5 -> Build Notify Render Started -> Notify Render Started -> Remap Render Job ID
connections['HTTP Request5'] = {
    "main": [
        [{"node": "Build Notify Render Started", "type": "main", "index": 0}]
    ]
}

connections['Build Notify Render Started'] = {
    "main": [
        [{"node": "Notify Render Started", "type": "main", "index": 0}]
    ]
}

connections['Notify Render Started'] = {
    "main": [
        [{"node": "Remap Render Job ID", "type": "main", "index": 0}]
    ]
}

# HTTP Request -> Keep Render Status Context -> If Render Failed
connections['HTTP Request'] = {
    "main": [
        [{"node": "Keep Render Status Context", "type": "main", "index": 0}]
    ]
}

connections['Keep Render Status Context'] = {
    "main": [
        [{"node": "If Render Failed", "type": "main", "index": 0}]
    ]
}

# If Render Failed -> true branch -> Build Notify Render Failed -> Notify Render Failed
connections['If Render Failed'] = {
    "main": [
        [{"node": "Build Notify Render Failed", "type": "main", "index": 0}],
        [{"node": "If", "type": "main", "index": 0}]  # false -> existing If
    ]
}

connections['Build Notify Render Failed'] = {
    "main": [
        [{"node": "Notify Render Failed", "type": "main", "index": 0}]
    ]
}

# If Render failed = false -> existing "If" (which checks completed)
# If true (from existing If, means completed) -> Build Notify Render Completed -> Notify Render Completed -> Trigger Opening Narration
# We need to connect from "If" completed to notification flow

# Update existing "If" connection to go through completed notification first
# Currently: If true -> Trigger Opening Narration
# Change to: If true -> Build Notify Render Completed -> Notify Render Completed -> Trigger Opening Narration
connections['If'] = {
    "main": [
        [{"node": "Build Notify Render Completed", "type": "main", "index": 0}],
        [{"node": "Wait", "type": "main", "index": 0}]  # false -> wait for next poll
    ]
}

connections['Build Notify Render Completed'] = {
    "main": [
        [{"node": "Notify Render Completed", "type": "main", "index": 0}]
    ]
}

connections['Notify Render Completed'] = {
    "main": [
        [{"node": "Trigger Opening Narration", "type": "main", "index": 0}]
    ]
}

print("Added Render flow connections")

# Opening Flow Connections:
# Trigger Opening Narration -> Remap Opening Job ID -> Build Notify Opening Started -> Notify Opening Started -> Cek Status Opening

# Update existing Trigger Opening Narration connection
connections['Trigger Opening Narration'] = {
    "main": [
        [{"node": "Remap Opening Job ID", "type": "main", "index": 0}]
    ]
}

# Add notification between Remap and Cek
connections['Remap Opening Job ID'] = {
    "main": [
        [{"node": "Build Notify Opening Started", "type": "main", "index": 0}]
    ]
}

connections['Build Notify Opening Started'] = {
    "main": [
        [{"node": "Notify Opening Started", "type": "main", "index": 0}]
    ]
}

connections['Notify Opening Started'] = {
    "main": [
        [{"node": "Cek Status Opening", "type": "main", "index": 0}]
    ]
}

# Cek Status Opening -> Keep Opening Status Context -> If Opening Failed
connections['Cek Status Opening'] = {
    "main": [
        [{"node": "Keep Opening Status Context", "type": "main", "index": 0}]
    ]
}

connections['Keep Opening Status Context'] = {
    "main": [
        [{"node": "If Opening Failed", "type": "main", "index": 0}]
    ]
}

# If Opening Failed -> true -> Build Notify Opening Failed -> Notify Opening Failed
connections['If Opening Failed'] = {
    "main": [
        [{"node": "Build Notify Opening Failed", "type": "main", "index": 0}],
        [{"node": "If Opening Completed", "type": "main", "index": 0}]  # false -> existing completed
    ]
}

connections['Build Notify Opening Failed'] = {
    "main": [
        [{"node": "Notify Opening Failed", "type": "main", "index": 0}]
    ]
}

# If Opening Completed true -> Build Notify Opening Completed -> Notify Opening Completed -> Trigger Subtitle Generator
# Update existing
connections['If Opening Completed'] = {
    "main": [
        [{"node": "Build Notify Opening Completed", "type": "main", "index": 0}],
        [{"node": "Wait Opening", "type": "main", "index": 0}]  # false -> wait
    ]
}

connections['Build Notify Opening Completed'] = {
    "main": [
        [{"node": "Notify Opening Completed", "type": "main", "index": 0}]
    ]
}

connections['Notify Opening Completed'] = {
    "main": [
        [{"node": "Trigger Subtitle Generator", "type": "main", "index": 0}]
    ]
}

print("Added Opening flow connections")

# Subtitle Flow Connections:
# Trigger Subtitle Generator -> Remap Subtitle Job ID -> Build Notify Subtitle Started -> Notify Subtitle Started -> Cek Status Subtitle

connections['Trigger Subtitle Generator'] = {
    "main": [
        [{"node": "Remap Subtitle Job ID", "type": "main", "index": 0}]
    ]
}

connections['Remap Subtitle Job ID'] = {
    "main": [
        [{"node": "Build Notify Subtitle Started", "type": "main", "index": 0}]
    ]
}

connections['Build Notify Subtitle Started'] = {
    "main": [
        [{"node": "Notify Subtitle Started", "type": "main", "index": 0}]
    ]
}

connections['Notify Subtitle Started'] = {
    "main": [
        [{"node": "Cek Status Subtitle", "type": "main", "index": 0}]
    ]
}

# Cek Status Subtitle -> Keep Subtitle Status Context -> If Subtitle Failed
connections['Cek Status Subtitle'] = {
    "main": [
        [{"node": "Keep Subtitle Status Context", "type": "main", "index": 0}]
    ]
}

connections['Keep Subtitle Status Context'] = {
    "main": [
        [{"node": "If Subtitle Failed", "type": "main", "index": 0}]
    ]
}

connections['If Subtitle Failed'] = {
    "main": [
        [{"node": "Build Notify Subtitle Failed", "type": "main", "index": 0}],
        [{"node": "If Subtitle Completed", "type": "main", "index": 0}]  # false -> existing completed
    ]
}

connections['Build Notify Subtitle Failed'] = {
    "main": [
        [{"node": "Notify Subtitle Failed", "type": "main", "index": 0}]
    ]
}

# If Subtitle Completed true -> Build Notify Subtitle Completed -> Notify Subtitle Completed -> Trigger Watermark
connections['If Subtitle Completed'] = {
    "main": [
        [{"node": "Build Notify Subtitle Completed", "type": "main", "index": 0}],
        [{"node": "Wait Subtitle", "type": "main", "index": 0}]  # false -> wait
    ]
}

connections['Build Notify Subtitle Completed'] = {
    "main": [
        [{"node": "Notify Subtitle Completed", "type": "main", "index": 0}]
    ]
}

connections['Notify Subtitle Completed'] = {
    "main": [
        [{"node": "Trigger Watermark", "type": "main", "index": 0}]
    ]
}

print("Added Subtitle flow connections")

# Watermark Flow Connections:
# Trigger Watermark -> Remap Watermark Job ID -> Build Notify Watermark Started -> Notify Watermark Started -> Cek Status Watermark

connections['Trigger Watermark'] = {
    "main": [
        [{"node": "Remap Watermark Job ID", "type": "main", "index": 0}]
    ]
}

connections['Remap Watermark Job ID'] = {
    "main": [
        [{"node": "Build Notify Watermark Started", "type": "main", "index": 0}]
    ]
}

connections['Build Notify Watermark Started'] = {
    "main": [
        [{"node": "Notify Watermark Started", "type": "main", "index": 0}]
    ]
}

connections['Notify Watermark Started'] = {
    "main": [
        [{"node": "Cek Status Watermark", "type": "main", "index": 0}]
    ]
}

# Cek Status Watermark -> Keep Watermark Status Context -> If Watermark Failed
connections['Cek Status Watermark'] = {
    "main": [
        [{"node": "Keep Watermark Status Context", "type": "main", "index": 0}]
    ]
}

connections['Keep Watermark Status Context'] = {
    "main": [
        [{"node": "If Watermark Failed", "type": "main", "index": 0}]
    ]
}

connections['If Watermark Failed'] = {
    "main": [
        [{"node": "Build Notify Watermark Failed", "type": "main", "index": 0}],
        [{"node": "If Watermark Completed", "type": "main", "index": 0}]  # false
    ]
}

connections['Build Notify Watermark Failed'] = {
    "main": [
        [{"node": "Notify Watermark Failed", "type": "main", "index": 0}]
    ]
}

# If Watermark Completed true -> Build Notify Watermark Completed -> Notify Watermark Completed -> Get Watermark Result1
connections['If Watermark Completed'] = {
    "main": [
        [{"node": "Build Notify Watermark Completed", "type": "main", "index": 0}],
        [{"node": "Wait Watermark", "type": "main", "index": 0}]  # false -> wait
    ]
}

connections['Build Notify Watermark Completed'] = {
    "main": [
        [{"node": "Notify Watermark Completed", "type": "main", "index": 0}]
    ]
}

connections['Notify Watermark Completed'] = {
    "main": [
        [{"node": "Get Watermark Result1", "type": "main", "index": 0}]
    ]
}

print("Added Watermark flow connections")

# Delivery Flow Connections:
# Get Watermark Result1 -> Prepare Telegram Payload1 -> Build Notify Delivery Started -> Notify Delivery Started
# Then split to existing delivery nodes

connections['Get Watermark Result1'] = {
    "main": [
        [{"node": "Prepare Telegram Payload1", "type": "main", "index": 0}]
    ]
}

connections['Prepare Telegram Payload1'] = {
    "main": [
        [{"node": "Build Notify Delivery Started", "type": "main", "index": 0}]
    ]
}

connections['Build Notify Delivery Started'] = {
    "main": [
        [{"node": "Notify Delivery Started", "type": "main", "index": 0}]
    ]
}

# Notify Delivery Started -> splits to both existing final delivery paths
connections['Notify Delivery Started'] = {
    "main": [
        [
            {"node": "Send a text message1", "type": "main", "index": 0},
            {"node": "Download Watermark Video1", "type": "main", "index": 0}
        ]
    ]
}

# After Send a video1, add final delivery completed notification
connections['Send a video1'] = {
    "main": [
        [{"node": "Build Notify Delivery Completed", "type": "main", "index": 0}]
    ]
}

connections['Build Notify Delivery Completed'] = {
    "main": [
        [{"node": "Notify Delivery Completed", "type": "main", "index": 0}]
    ]
}

print("Added Delivery flow connections")

# Update workflow with connections
workflow['connections'] = connections

# Save updated workflow
with open('n8n_post_content.json', 'w') as f:
    json.dump(workflow, f, indent=2)

print("\n✓ All connections added successfully!")

# Run validations
print("\n" + "="*60)
print("VALIDATION")
print("="*60)

# Validate JSON
try:
    json.dumps(workflow)
    print("✓ JSON valid")
except Exception as e:
    print(f"✗ JSON error: {e}")

# Validate connections
names = set(n['name'] for n in workflow['nodes'])
bad = []
for source, conn in connections.items():
    if source not in names:
        bad.append(f"missing source {source}")
    for group in conn.get('main', []):
        for edge in group:
            if edge['node'] not in names:
                bad.append(f"missing target {source} -> {edge['node']}")

if bad:
    print(f"Connection issues: {bad}")
else:
    print("✓ All connections valid")

# Count connections
conn_count = sum(len(conn.get('main', [[]])[0]) for conn in connections.values())
print(f"\nTotal connections: {conn_count}")
