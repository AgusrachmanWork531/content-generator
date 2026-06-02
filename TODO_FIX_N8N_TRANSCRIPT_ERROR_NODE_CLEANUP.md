# TODO: Fix N8N Transcript Error Node Cleanup

## Status

PLANNED

## Goal

Fix the last two n8n issues found after implementing:

```text
TODO_FIX_TRANSCRIPT_FALLBACK_REVIEW_ISSUES.md
```

This issue only touches the transcript error branch in:

```text
n8n_node.json
```

Do not edit `api_server.py` for this issue.

## Current Bugs

### Bug 1: Telegram expressions are missing `=`

Current `Send Transcript Error` node has:

```json
"chatId": "{{ $('Telegram Trigger').first().json.message.chat.id }}",
"text": "{{ 'Transcript gagal untuk video ' + ($json.video_id || $('Parse Source & Video ID').first().json.video_id || '-') + '\\n\\n' + ($json.error || 'Unknown transcript error') }}"
```

This is unsafe because n8n exported expressions should use:

```text
={{ ... }}
```

### Bug 2: Duplicate `If Transcript Failed` node

Current `n8n_node.json` has two nodes with:

```json
"name": "If Transcript Failed"
```

Both also have the same id:

```text
27500967-e8a3-48c4-9fa6-99832c79ee50
```

n8n workflows must not have duplicate node names or duplicate node ids.

## Files To Edit

Edit only:

```text
n8n_node.json
```

Do not edit:

```text
api_server.py
prompt.md
render nodes
watermark nodes
Telegram video delivery nodes
```

## Plan

### Step 1: Fix `Send Transcript Error` expressions

Find node:

```text
"name": "Send Transcript Error"
```

Set:

```json
"chatId": "={{ $('Telegram Trigger').first().json.message.chat.id }}"
```

Set:

```json
"text": "={{ 'Transcript gagal untuk video ' + ($json.video_id || $('Parse Source & Video ID').first().json.video_id || '-') + '\\n\\n' + ($json.error || 'Unknown transcript error') }}"
```

Keep:

```json
"parse_mode": "Markdown"
```

Keep existing Telegram credentials unchanged.

### Step 2: Remove duplicate `If Transcript Failed`

Find all nodes where:

```json
"name": "If Transcript Failed"
```

There must be exactly one node left.

Use this exact node shape for the remaining node:

```json
{
  "parameters": {
    "conditions": {
      "options": {
        "caseSensitive": true,
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
  "position": [
    -96,
    448
  ],
  "id": "27500967-e8a3-48c4-9fa6-99832c79ee50",
  "name": "If Transcript Failed"
}
```

If both duplicate nodes are identical, delete one of them.

### Step 3: Keep transcript connections unchanged

After cleanup, the connections must be:

```text
Check Status Extract transcribe1 -> If Transcript Failed
If Transcript Failed true -> Send Transcript Error
If Transcript Failed false -> If Transcript Status
If Transcript Status true -> Convert to File
If Transcript Status false -> Wait5
Wait5 -> Check Status Extract transcribe1
```

Do not change other workflow branches.

## Validation Commands

Run these commands from repo root.

### Validate JSON

```bash
node -e "JSON.parse(require('fs').readFileSync('n8n_node.json','utf8')); console.log('json ok')"
```

Expected:

```text
json ok
```

### Validate duplicate nodes

```bash
node - <<'NODE'
const fs=require('fs');
const j=JSON.parse(fs.readFileSync('n8n_node.json','utf8'));
const counts = {};
for (const node of j.nodes) {
  counts[node.name] = (counts[node.name] || 0) + 1;
}
const duplicates = Object.entries(counts).filter(([, count]) => count > 1);
console.log(duplicates.length ? JSON.stringify(duplicates) : 'no duplicate node names');
NODE
```

Expected:

```text
no duplicate node names
```

### Validate duplicate ids

```bash
node - <<'NODE'
const fs=require('fs');
const j=JSON.parse(fs.readFileSync('n8n_node.json','utf8'));
const counts = {};
for (const node of j.nodes) {
  counts[node.id] = (counts[node.id] || 0) + 1;
}
const duplicates = Object.entries(counts).filter(([, count]) => count > 1);
console.log(duplicates.length ? JSON.stringify(duplicates) : 'no duplicate node ids');
NODE
```

Expected:

```text
no duplicate node ids
```

### Validate n8n connections

```bash
node - <<'NODE'
const fs=require('fs');
const j=JSON.parse(fs.readFileSync('n8n_node.json','utf8'));
const names=new Set(j.nodes.map(n=>n.name));
let bad=[];
for (const [source, conn] of Object.entries(j.connections||{})) {
  if (!names.has(source)) bad.push(`missing source ${source}`);
  for (const group of conn.main||[]) {
    for (const edge of group||[]) {
      if (!names.has(edge.node)) bad.push(`missing target ${source} -> ${edge.node}`);
    }
  }
}
console.log(bad.join('\n') || 'connections ok');
NODE
```

Expected:

```text
connections ok
```

### Validate expression prefix

```bash
node - <<'NODE'
const fs=require('fs');
const j=JSON.parse(fs.readFileSync('n8n_node.json','utf8'));
const node = j.nodes.find(n => n.name === 'Send Transcript Error');
console.log(node.parameters.chatId.startsWith('={{') ? 'chatId ok' : node.parameters.chatId);
console.log(node.parameters.text.startsWith('={{') ? 'text ok' : node.parameters.text);
NODE
```

Expected:

```text
chatId ok
text ok
```

## Acceptance Criteria

- [ ] `Send Transcript Error.chatId` starts with `={{`.
- [ ] `Send Transcript Error.text` starts with `={{`.
- [ ] There is exactly one node named `If Transcript Failed`.
- [ ] There are no duplicate node ids.
- [ ] No connection points to a missing node.
- [ ] Transcript failed branch still sends Telegram error.
- [ ] Transcript running/queued branch still waits and polls again.
- [ ] Transcript completed branch still goes to `Convert to File`.

