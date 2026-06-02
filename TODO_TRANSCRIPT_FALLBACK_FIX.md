# TODO: Fix Transcript Fallback Review Issues

## Status: IN_PROGRESS

## Bugs to Fix

- [ ] Bug 1: Missing n8n node "If Transcript Status"
- [ ] Bug 2: Wrong chat_id expression in Send Transcript Error  
- [ ] Bug 3: Error message doesn't include backend error
- [ ] Bug 4: Backend transcript output validation too loose

## Implementation Steps

### Step 1: Fix n8n_node.json

1. Rename `if1` to `If Transcript Status`
2. Create `If Transcript Failed` node
3. Fix connections:
   - `Ekstract Trunscribe1` -> `If Transcript Failed`
   - `If Transcript Failed` true -> `Send Transcript Error`
   - `If Transcript Failed` false -> `If Transcript Status`
   - `If Transcript Status` true -> `Convert to File`
   - `If Transcript Status` false -> `Wait5`
   - `Wait5` -> `Check Status Extract transcribe1`
   - `Check Status Extract transcribe1` -> `If Transcript Failed`
4. Fix `Send Transcript Error`:
   - chatId: `{{ $('Telegram Trigger').first().json.message.chat.id }}`
   - text: include `$json.error`

### Step 2: Fix api_server.py

- Tighten `step_output_exists("transcript", video_id)` to require specific files

## Validation

- [ ] n8n JSON valid
- [ ] n8n connections valid
- [ ] Python syntax valid
- [ ] Transcript output check strict
