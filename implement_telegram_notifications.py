#!/usr/bin/env python3
"""
Implement Telegram Process Notifications for n8n_post_content.json

This script adds notification nodes for each step:
- render, opening, subtitle, watermark, delivery
For each step: started, completed, failed

Following TODO_IMPROVE_N8N_POST_CONTENT_TELEGRAM_PROCESS_NOTIFICATIONS.md
"""

import json
import uuid
import copy
from datetime import datetime

# Load the current workflow
with open('n8n_post_content.json', 'r') as f:
    workflow = json.load(f)

# Create a node name to ID lookup
node_name_to_id = {node['name']: node['id'] for node in workflow['nodes']}
node_id_to_name = {node['id']: node['name'] for node in workflow['nodes']}
node_name_to_node = {node['name']: node for node in workflow['nodes']}

# Telegram credentials (shared across all notification nodes)
TELEGRAM_CREDENTIALS = {
    "telegramApi": {
        "id": "wo2KtQA3GKUjikub",
        "name": "Telegram account"
    }
}

def generate_id():
    return str(uuid.uuid4())

def create_notification_builder(name, emoji_text):
    """Create a Build Notify X node"""
    
    # Determine the message type based on name
    if "Failed" in name:
        error_line = "`Error:\\n${current.error || 'Unknown error'}`"
    elif "Delivery Started" in name:
        error_line = "`File: ${current.filename || '-'}`"
    elif "Delivery Completed" in name:
        emoji_text = "✅ Semua proses selesai\\n\\nVideo watermark dan metadata YouTube sudah dikirim."
        error_line = "null"
    else:
        error_line = "`Status: ${current.status || 'queued'}`"
    
    # Build the JavaScript code
    if "Delivery Completed" in name:
        js_code = f"""const original = $('Code in JavaScript').first().json;
const current = $input.first().json;

const chat_id = original.telegram?.chat_id;
if (!chat_id) {{
  throw new Error('chat_id tidak ditemukan untuk notifikasi Telegram');
}}

return [{{
  json: {{
    ...current,
    chat_id,
    video_id: current.video_id || original.video_id || '-',
    notification_text: [
      '✅ Semua proses selesai',
      '',
      'Video watermark dan metadata YouTube sudah dikirim.'
    ].join('\\n')
  }}
}}];"""
    elif "Render Started" in name or "Opening Started" in name or "Subtitle Started" in name or "Watermark Started" in name:
        js_code = f"""const original = $('Code in JavaScript').first().json;
const current = $input.first().json;
const yt = original.render_payload?.youtube_metadata || {{}};

const chat_id = original.telegram?.chat_id;
if (!chat_id) {{
  throw new Error('chat_id tidak ditemukan untuk notifikasi Telegram');
}}

const stepName = "{name.replace('Build Notify ', '').replace(' Started', '')}";
return [{{
  json: {{
    ...current,
    chat_id,
    video_id: current.video_id || original.video_id || '-',
    notification_text: [
      '{emoji_text}',
      '',
      `Video ID: ${{current.video_id || original.video_id || '-'}}`,
      `Judul: ${{yt.title || '-'}}`,
      `Job ID: ${{current.job_id || '-'}}`,
      `Status: ${{current.status || 'queued'}}`
    ].join('\\n')
  }}
}}];"""
    elif "Render Completed" in name or "Opening Completed" in name or "Subtitle Completed" in name or "Watermark Completed" in name:
        js_code = f"""const original = $('Code in JavaScript').first().json;
const current = $input.first().json;
const yt = original.render_payload?.youtube_metadata || {{}};

const chat_id = original.telegram?.chat_id;
if (!chat_id) {{
  throw new Error('chat_id tidak ditemukan untuk notifikasi Telegram');
}}

return [{{
  json: {{
    ...current,
    chat_id,
    video_id: current.video_id || original.video_id || '-',
    notification_text: [
      '{emoji_text}',
      '',
      `Video ID: ${{current.video_id || original.video_id || '-'}}`,
      `Judul: ${{yt.title || '-'}}`,
      `Job ID: ${{current.job_id || '-'}}`
    ].join('\\n')
  }}
}}];"""
    elif "Render Failed" in name or "Opening Failed" in name or "Subtitle Failed" in name or "Watermark Failed" in name:
        js_code = f"""const original = $('Code in JavaScript').first().json;
const current = $input.first().json;
const yt = original.render_payload?.youtube_metadata || {{}};

const chat_id = original.telegram?.chat_id;
if (!chat_id) {{
  throw new Error('chat_id tidak ditemukan untuk notifikasi Telegram');
}}

return [{{
  json: {{
    ...current,
    chat_id,
    video_id: current.video_id || original.video_id || '-',
    notification_text: [
      '{emoji_text}',
      '',
      `Video ID: ${{current.video_id || original.video_id || '-'}}`,
      `Judul: ${{yt.title || '-'}}`,
      `Job ID: ${{current.job_id || '-'}}`,
      '',
      `Error:\\n${{current.error || 'Unknown error'}}`
    ].join('\\n')
  }}
}}];"""
    elif "Delivery Started" in name:
        js_code = f"""const original = $('Code in JavaScript').first().json;
const current = $input.first().json;
const yt = original.render_payload?.youtube_metadata || {{}};

const chat_id = original.telegram?.chat_id;
if (!chat_id) {{
  throw new Error('chat_id tidak ditemukan untuk notifikasi Telegram');
}}

return [{{
  json: {{
    ...current,
    chat_id,
    video_id: current.video_id || original.video_id || '-',
    notification_text: [
      '{emoji_text}',
      '',
      `Video ID: ${{current.video_id || original.video_id || '-'}}`,
      `File: ${{current.filename || '-'}}`
    ].join('\\n')
  }}
}}];"""
    else:
        js_code = "// Notification builder"
    
    node_id = generate_id()
    
    # Calculate position - we'll adjust later based on connection order
    base_position = [800, 4000]
    
    node = {
        "parameters": {
            "jsCode": js_code
        },
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": base_position,
        "id": node_id,
        "name": name
    }
    
    return node


def create_telegram_notify_node(name):
    """Create a Notify X Telegram node"""
    node_id = generate_id()
    
    node = {
        "parameters": {
            "chatId": "={{ $json.chat_id }}",
            "text": "={{ $json.notification_text }}",
            "additionalFields": {
                "parse_mode": "Markdown"
            }
        },
        "type": "n8n-nodes-base.telegram",
        "typeVersion": 1.2,
        "position": [1200, 4000],  # Will adjust
        "id": node_id,
        "name": name,
        "webhookId": generate_id(),
        "credentials": TELEGRAM_CREDENTIALS
    }
    
    return node


def create_failed_if_node(name, step_name):
    """Create a If X Failed node"""
    node_id = generate_id()
    
    # The step name used in the condition
    step_value = step_name.lower()
    
    node = {
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
                        "id": f"{step_value}-failed-status",
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
        "position": [2000, 4000],  # Will adjust
        "id": node_id,
        "name": name
    }
    
    return node


# Define all notification nodes to create
NOTIFICATION_BUILDERS = [
    ("Build Notify Render Started", "🚀 Render dimulai"),
    ("Build Notify Render Completed", "✅ Render selesai"),
    ("Build Notify Render Failed", "❌ Render gagal"),
    ("Build Notify Opening Started", "🚀 Opening dimulai"),
    ("Build Notify Opening Completed", "✅ Opening selesai"),
    ("Build Notify Opening Failed", "❌ Opening gagal"),
    ("Build Notify Subtitle Started", "🚀 Subtitle dimulai"),
    ("Build Notify Subtitle Completed", "✅ Subtitle selesai"),
    ("Build Notify Subtitle Failed", "❌ Subtitle gagal"),
    ("Build Notify Watermark Started", "🚀 Watermark dimulai"),
    ("Build Notify Watermark Completed", "✅ Watermark selesai"),
    ("Build Notify Watermark Failed", "❌ Watermark gagal"),
    ("Build Notify Delivery Started", "📤 Mengirim hasil ke Telegram"),
    ("Build Notify Delivery Completed", "✅ Semua proses selesai"),
]

NOTIFICATION_TELEGRAM_NODES = [
    "Notify Render Started",
    "Notify Render Completed",
    "Notify Render Failed",
    "Notify Opening Started",
    "Notify Opening Completed",
    "Notify Opening Failed",
    "Notify Subtitle Started",
    "Notify Subtitle Completed",
    "Notify Subtitle Failed",
    "Notify Watermark Started",
    "Notify Watermark Completed",
    "Notify Watermark Failed",
    "Notify Delivery Started",
    "Notify Delivery Completed",
]

FAILED_IF_NODES = [
    ("If Render Failed", "render"),
    ("If Opening Failed", "opening"),
    ("If Subtitle Failed", "subtitle"),
    ("If Watermark Failed", "watermark"),
]

# Create all new nodes
new_nodes = []

# Add builder nodes
for name, emoji in NOTIFICATION_BUILDERS:
    node = create_notification_builder(name, emoji)
    new_nodes.append(node)
    node_name_to_id[name] = node['id']
    node_name_to_node[name] = node

print(f"Created {len(NOTIFICATION_BUILDERS)} notification builder nodes")

# Add Telegram notify nodes
for name in NOTIFICATION_TELEGRAM_NODES:
    node = create_telegram_notify_node(name)
    new_nodes.append(node)
    node_name_to_id[name] = node['id']
    node_name_to_node[name] = node

print(f"Created {len(NOTIFICATION_TELEGRAM_NODES)} notification Telegram nodes")

# Add failed IF nodes
for name, step in FAILED_IF_NODES:
    node = create_failed_if_node(name, step)
    new_nodes.append(node)
    node_name_to_id[name] = node['id']
    node_name_to_node[name] = node

print(f"Created {len(FAILED_IF_NODES)} failed IF nodes")

# Add all new nodes to workflow
workflow['nodes'].extend(new_nodes)

# Now fix positions and connections
# First let's organize the positions better
# Current nodes have positions spread across x: 704-3648, y: 4640-5856

# Get existing node positions
def get_next_position(base_x, base_y, offset_index, x_offset=240, y_offset=0):
    """Calculate position with offset"""
    return [base_x + offset_index * x_offset, base_y + offset_index * y_offset]

# Define position zones for each step
# Render flow: x around 1072-2112
# Opening flow: x around 1488-2512
# Subtitle flow: x around 2048-2800
# Watermark flow: x around 1760-3008
# Delivery flow: x around 3008-3648

print("\nTODO: Manual positioning and connection wiring required")
print("This script provides the node structure but requires manual connection in n8n editor")
print("\nNew nodes added:")
for node in new_nodes:
    print(f"  - {node['name']}")

# Save the updated workflow
with open('n8n_post_content.json', 'w') as f:
    json.dump(workflow, f, indent=2)

print(f"\nSaved updated workflow with {len(workflow['nodes'])} nodes")

# Create validation report
print("\n" + "="*60)
print("VALIDATION")
print("="*60)

# Check required notification nodes
names = set(n['name'] for n in workflow['nodes'])
required = [n[0] for n in NOTIFICATION_BUILDERS] + NOTIFICATION_TELEGRAM_NODES
missing = [n for n in required if n not in names]
if missing:
    print(f"WARNING: Missing notification nodes: {missing}")
else:
    print("✓ All notification nodes present")

# Validate JSON
try:
    json.dumps(workflow)
    print("✓ JSON valid")
except Exception as e:
    print(f"✗ JSON error: {e}")

print("\n" + "="*60)
print("NEXT STEPS - Edit in n8n Editor:")
print("="*60)
print("""
1. Position all new notification nodes appropriately
2. Wire up connections per the TODO plan:

Render Flow:
  HTTP Request5 -> Build Notify Render Started -> Notify Render Started -> Remap Render Job ID
  HTTP Request -> Keep Render Status Context -> If Render Failed
  If Render Failed true -> Build Notify Render Failed -> Notify Render Failed
  If Render Failed false -> If
  If true -> Build Notify Render Completed -> Notify Render Completed -> Trigger Opening Narration

Opening Flow:
  Trigger Opening Narration -> Remap Opening Job ID -> Build Notify Opening Started -> Notify Opening Started -> Cek Status Opening
  Cek Status Opening -> Keep Opening Status Context -> If Opening Failed
  If Opening Failed true -> Build Notify Opening Failed -> Notify Opening Failed
  If Opening Failed false -> If Opening Completed
  If Opening Completed true -> Build Notify Opening Completed -> Notify Opening Completed -> Trigger Subtitle Generator

Subtitle Flow:
  Same pattern...

Watermark Flow:
  Same pattern...

Delivery Flow:
  Get Watermark Result1 -> Prepare Telegram Payload1 -> Build Notify Delivery Started -> Notify Delivery Started
  Notify Delivery Started -> Send a text message1 / Download Watermark Video1
  Send a video1 -> Build Notify Delivery Completed -> Notify Delivery Completed
""")
