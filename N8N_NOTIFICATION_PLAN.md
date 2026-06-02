# N8N Telegram Process Notifications Implementation Plan

## Overview

This plan implements Telegram process notifications for the n8n_post_content.json workflow based on TODO_IMPROVE_N8N_POST_CONTENT_TELEGRAM_PROCESS_NOTIFICATIONS.md.

## Current Workflow Structure

```
Telegram Trigger3 → Code in JavaScript → HTTP Request5 → Remap Render Job ID → HTTP Request → Keep Render Status Context → If → Trigger Opening Narration
Trigger Opening Narration → Remap Opening Job ID → Cek Status Opening → Keep Opening Status Context → If Opening Completed → Trigger Subtitle
Trigger Subtitle → Remap Subtitle Job ID → Cek Status Subtitle → Keep Subtitle Status Context → If Subtitle Completed → Trigger Watermark
Trigger Watermark → Remap Watermark Job ID → Cek Status Watermark → Keep Watermark Status Context → If Watermark Completed → Get Result → Delivery
```

## Implementation Steps

### Step 1: Add Notification Builder Code Nodes

Add 14 builder nodes at strategic positions. Each returns { chat_id, video_id, notification_text }.

| Node Name | Emoji | Message Format |
|----------|-------|----------------|
| Build Notify Render Started | 🚀 | Render dimulai |
| Build Notify Render Completed | ✅ | Render selesai |
| Build Notify Render Failed | ❌ | Render gagal + Error |
| Build Notify Opening Started | 🚀 | Opening dimulai |
| Build Notify Opening Completed | ✅ | Opening selesai |
| Build Notify Opening Failed | ❌ | Opening gagal + Error |
| Build Notify Subtitle Started | 🚀 | Subtitle dimulai |
| Build Notify Subtitle Completed | ✅ | Subtitle selesai |
| Build Notify Subtitle Failed | ❌ | Subtitle gagal + Error |
| Build Notify Watermark Started | 🚀 | Watermark dimulai |
| Build Notify Watermark Completed | ✅ | Watermark selesai |
| Build Notify Watermark Failed | ❌ | Watermark gagal + Error |
| Build Notify Delivery Started | 📤 | Mengirim hasil ke Telegram |
| Build Notify Delivery Completed | ✅ | Semua proses selesai |

### Step 2: Add Notification Telegram Nodes

Add 14 Telegram nodes with credential `wo2KtQA3GKUjikub`:

```
chatId: =={{ $json.chat_id }}
text: =={{ $json.notification_text }}
parse_mode: Markdown
```

### Step 3: Add Failed IF Nodes

Add before existing completed IF nodes:

- If Render Failed (check status == failed)
- If Opening Failed (check status == failed)
- If Subtitle Failed (check status == failed)
- If Watermark Failed (check status == failed)

### Step 4: Update Connections

**Render Flow:**
```
HTTP Request5 → Remap Render Job ID → Build Notify Render Started → Notify Render Started → HTTP Request
HTTP Request → Keep Render Status Context → If Render Failed
If Render Failed true → Build Notify Render Failed → Notify Render Failed
If Render Failed false → If
If true → Build Notify Render Completed → Notify Render Completed → Trigger Opening Narration
If false → Wait → HTTP Request
```

**Opening Flow:**
```
Trigger Opening Narration → Remap Opening Job ID → Build Notify Opening Started → Notify Opening Started → Cek Status Opening
Cek Status Opening → Keep Opening Status Context → If Opening Failed
If Opening Failed true → Build Notify Opening Failed → Notify Opening Failed
If Opening Failed false → If Opening Completed
If Opening Completed true → Build Notify Opening Completed → Notify Opening Completed → Trigger Subtitle
If Opening Completed false → Wait Opening → Cek Status Opening
```

**Subtitle Flow:**
```
Trigger Subtitle Generator → Remap Subtitle Job ID → Build Notify Subtitle Started → Notify Subtitle Started → Cek Status Subtitle
Cek Status Subtitle → Keep Subtitle Status Context → If Subtitle Failed
If Subtitle Failed true → Build Notify Subtitle Failed → Notify Subtitle Failed
If Subtitle Failed false → If Subtitle Completed
If Subtitle Completed true → Build Notify Subtitle Completed → Notify Subtitle Completed → Trigger Watermark
If Subtitle Completed false → Wait Subtitle → Cek Status Subtitle
```

**Watermark Flow:**
```
Trigger Watermark → Remap Watermark Job ID → Build Notify Watermark Started → Notify Watermark Started → Cek Status Watermark
Cek Status Watermark → Keep Watermark Status Context → If Watermark Failed
If Watermark Failed true → Build Notify Watermark Failed → Notify Watermark Failed
If Watermark Failed false → If Watermark Completed
If Watermark Completed true → Build Notify Watermark Completed → Notify Watermark Completed → Get Watermark Result1
If Watermark Completed false → Wait Watermark → Cek Status Watermark
```

**Delivery Flow:**
```
Get Watermark Result1 → Prepare Telegram Payload1 → Build Notify Delivery Started → Notify Delivery Started
Notify Delivery Started → Send a text message1
Notify Delivery Started → Download Watermark Video1 → Send a video1
Send a video1 → Build Notify Delivery Completed → Notify Delivery Completed
```

## Node ID Assignments

New nodes will use generated UUIDs for IDs.

## Validation

After implementation, run:

1. JSON validation: `node -e "JSON.parse(require('fs').readFileSync('n8n_post_content.json','utf8')); console.log('json ok')"`
2. Connection validation: Check all source/target nodes exist
3. Duplicate name check: No duplicates allowed
4. Required notification nodes check: All 14 nodes exist

## Acceptance Criteria

- [ ] User receives notification when render starts
- [ ] User receives notification when render completes
- [ ] User receives notification when render fails
- [ ] User receives notification when opening starts
- [ ] User receives notification when opening completes
- [ ] User receives notification when opening fails
- [ ] User receives notification when subtitle starts
- [ ] User receives notification when subtitle completes
- [ ] User receives notification when subtitle fails
- [ ] User receives notification when watermark starts
- [ ] User receives notification when watermark completes
- [ ] User receives notification when watermark fails
- [ ] User receives notification when delivery starts
- [ ] User receives notification when delivery completes
- [ ] No notification spam (only on state transitions)
- [ ] Failed steps stop flow and notify user
- [ ] Existing delivery still works
