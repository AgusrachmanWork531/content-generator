#!/usr/bin/env python3
"""
Fix n8n_post_content.json to add Prepare Subtitle Video Path node
and update connections for proper subtitle video artifact path.
"""
import json

# Read the current workflow
with open('n8n_post_content.json', 'r') as f:
    data = json.load(f)

nodes = data['nodes']
connections = data['connections']

print("=== FIXING SUBTITLE VIDEO PATH ===\n")

# Determine which Code node comes before subtitle
code_node_name = 'Code in JavaScript1'
for n in nodes:
    if n['name'] in ['Code in JavaScript1', 'Code in JavaScript2']:
        code_node_name = n['name']
        break
        
print(f"Using input node: {code_node_name}")

# Step 1: Add new Code node "Prepare Subtitle Video Path"
js_code = """const original = $('""" + code_node_name + """').first().json;
const current = $input.first().json;

const videoId = original.video_id;
if (!videoId) {
  throw new Error('video_id tidak ditemukan dari payload utama');
}

const clipIndex = Number(original.render_payload?.clip_index || 1);
if (!Number.isInteger(clipIndex) || clipIndex < 1) {
  throw new Error(`render_payload.clip_index tidak valid: ${original.render_payload?.clip_index}`);
}

const clipNumber = String(clipIndex).padStart(2, '0');
const baseDir = `/Users/agusrachman/Documents/Codex/content-short/storage/free-viral-shorts/${videoId}`;

return [
  {
    json: {
      ...current,
      video_id: current.video_id || videoId,
      subtitle_video_path: `${baseDir}/opening/short_${clipNumber}_with_opening.mp4`,
      subtitle_fallback_video_path: `${baseDir}/shorts/short_${clipNumber}.mp4`,
      clip_index: clipIndex,
      clip_number: clipNumber
    }
  }
];"""

new_node = {
    "parameters": {
        "jsCode": js_code
    },
    "type": "n8n-nodes-base.code",
    "typeVersion": 2,
    "position": [2550, 7584],
    "id": "prepare-subtitle-video-path-node-id",
    "name": "Prepare Subtitle Video Path"
}

nodes.append(new_node)
print('✅ Step 1: Added "Prepare Subtitle Video Path" node')

# Step 2: Update video_path in Trigger Subtitle Generator1
for node in nodes:
    if node['name'] == 'Trigger Subtitle Generator1':
        body_params = node['parameters']['bodyParameters']['parameters']
        for p in body_params:
            if p['name'] == 'video_path':
                old_value = p['value']
                p['value'] = '={{ $json.subtitle_video_path }}'
                print(f'✅ Step 2: Updated video_path')
                print(f'   OLD: {old_value[:60]}...')
                print(f'   NEW: {p["value"]}')
                break

# Step 3: Update Remap Subtitle Job ID1
remap_js = """const items = $('Trigger Subtitle Generator1').all();
const prepared = $('Prepare Subtitle Video Path').first().json;

return items.map(item => {
  const body = item.json.body || item.json;

  if (!body.job_id) {
    throw new Error(`Subtitle job_id tidak ditemukan. Response: ${JSON.stringify(item.json)}`);
  }

  return {
    json: {
      job_id: body.job_id,
      step: 'subtitle',
      status_url: body.status_url || `/subtitle/jobs/${body.job_id}`,
      result_url: body.result_url || `/subtitle/jobs/${body.job_id}`,
      source: $('""" + code_node_name + """').first().json.source,
      video_id: $('""" + code_node_name + """').first().json.video_id,
      subtitle_video_path: prepared.subtitle_video_path,
      subtitle_fallback_video_path: prepared.subtitle_fallback_video_path,
      clip_index: prepared.clip_index,
      clip_number: prepared.clip_number
    }
  };
});"""

for node in nodes:
    if node['name'] == 'Remap Subtitle Job ID1':
        node['parameters']['jsCode'] = remap_js
        print('✅ Step 3: Updated Remap Subtitle Job ID1')

# Step 4: Update connections - redirect any node that connects to Trigger Subtitle Generator1
nodes_to_redirect = []
for source, conns in connections.items():
    if 'main' in conns:
        for i, edge_list in enumerate(conns['main']):
            for edge in edge_list:
                if edge['node'] == 'Trigger Subtitle Generator1':
                    nodes_to_redirect.append((source, i))

# Update each connection
for source, idx in nodes_to_redirect:
    old_target = connections[source]['main'][idx][0]['node']
    connections[source]['main'][idx] = [{"node": "Prepare Subtitle Video Path", "type": "main", "index": 0}]
    print(f'✅ Step 4a: Updated {source} -> Prepare Subtitle Video Path')

# Add connection from Prepare Subtitle Video Path to Trigger Subtitle Generator1
connections['Prepare Subtitle Video Path'] = {
    "main": [
        [{"node": "Trigger Subtitle Generator1", "type": "main", "index": 0}]
    ]
}
print('✅ Step 4b: Connection added: Prepare Subtitle Video Path -> Trigger Subtitle Generator1')

# Save the modified workflow
with open('n8n_post_content.json', 'w') as f:
    json.dump(data, f, indent=2)

print('\n🎉 All changes applied successfully!')
print('\n=== VALIDATION ===')

# Quick validation
with open('n8n_post_content.json', 'r') as f:
    data = json.load(f)

# Check video_path
node = next((n for n in data['nodes'] if n['name'] == 'Trigger Subtitle Generator1'), None)
if node:
    video_path = next((p['value'] for p in node['parameters']['bodyParameters']['parameters'] if p['name'] == 'video_path'), None)
    print(f'video_path = {video_path}')

# Check new node exists
names = {n['name'] for n in data['nodes']}
print(f'"Prepare Subtitle Video Path" exists: {"Prepare Subtitle Video Path" in names}')
print(f'Total nodes: {len(names)}')
