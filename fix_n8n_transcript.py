#!/usr/bin/env python3
"""Fix n8n_node.json for transcript fallback issues."""
import json

with open('n8n_node.json', 'r') as f:
    j = json.load(f)

print("=== Fixing n8n_node.json ===")

# Step 1: Rename 'if1' to 'If Transcript Status'
for node in j['nodes']:
    if node['name'] == 'if1':
        node['name'] = 'If Transcript Status'
        print(f"Renamed 'if1' to '{node['name']}'")

# Step 2: Create 'If Transcript Failed' node
failed_node = {
    "parameters": {
        "conditions": {
            "options": {
                "caseSensitive": True,
                "leftValue": "",
                "typeValidation": "strict",
                "version": 2
            },
            "conditions": [
                {
                    "id": "transcript-failed-status",
                    "leftValue": "=failed",
                    "rightValue": "={{ $json.status }}",
                    "operator": {
                        "type": "string",
                        "operation": "equals"
                    }
                }
            ],
            "combinator": "and"
        },
        "options": {}
    },
    "type": "n8n-nodes-base.if",
    "typeVersion": 2.2,
    "position": [-96, 448],
    "id": "27500967-e8a3-48c4-9fa6-99832c79ee50",
    "name": "If Transcript Failed"
}
j['nodes'].append(failed_node)
print(f"Added new node: '{failed_node['name']}'")

# Step 3: Fix Send Transcript Error - chatId and text
for node in j['nodes']:
    if node['name'] == 'Send Transcript Error':
        node['parameters']['chatId'] = "{{ $('Telegram Trigger').first().json.message.chat.id }}"
        node['parameters']['text'] = "{{ 'Transcript gagal untuk video ' + ($json.video_id || $('Parse Source & Video ID').first().json.video_id || '-') + '\\n\\n' + ($json.error || 'Unknown transcript error') }}"
        print(f"Fixed Send Transcript Error parameters")

# Step 4: Fix connections - remove ALL old transcript-related connections
for key in ['If Transcript Status', 'Check Status Extract transcribe1', 'if1']:
    if key in j['connections']:
        del j['connections'][key]

j['connections']['Ekstract Trunscribe1'] = {
    "main": [[{"node": "Check Status Extract transcribe1", "type": "main", "index": 0}]]
}
j['connections']['Check Status Extract transcribe1'] = {
    "main": [[{"node": "If Transcript Failed", "type": "main", "index": 0}]]
}
j['connections']['If Transcript Failed'] = {
    "main": [
        [{"node": "Send Transcript Error", "type": "main", "index": 0}],
        [{"node": "If Transcript Status", "type": "main", "index": 0}]
    ]
}
j['connections']['If Transcript Status'] = {
    "main": [
        [{"node": "Convert to File", "type": "main", "index": 0}],
        [{"node": "Wait5", "type": "main", "index": 0}]
    ]
}
j['connections']['Wait5'] = {
    "main": [[{"node": "Check Status Extract transcribe1", "type": "main", "index": 0}]]
}
j['connections']['Send Transcript Error'] = {
    "main": [[]]
}

print("Fixed all connections")

# Save
with open('n8n_node.json', 'w') as f:
    json.dump(j, f, indent=2)

# Verify
print("\n=== VERIFICATION ===")
node_names = {n['name'] for n in j['nodes']}
bad = []
for source, conn in j['connections'].items():
    if source not in node_names:
        bad.append(f"Missing source: {source}")
    for group in conn.get('main', []):
        for edge in group:
            if edge['node'] not in node_names:
                bad.append(f"Missing target: {source} -> {edge['node']}")

if bad:
    print("BAD:", bad)
else:
    print("Connections OK!")

print("\nDone!")
