#!/usr/bin/env python3
"""Apply watermark fix to n8n_watermark_delivery_only.json"""

import json

def main():
    with open('n8n_watermark_delivery_only.json') as f:
        wf = json.load(f)

    # Find Prepare Telegram Payload node
    for node in wf.get('nodes', []):
        if node.get('name') == 'Prepare Telegram Payload':
            new_code = '''// Prepare Telegram Payload (with fallback to local storage)
const original = $('Code in JavaScript2').first().json;
const result = $input.first().json;

const API_BASE_URL = 'https://authentic-linguist-scoundrel.ngrok-free.dev';

const chat_id = original.telegram?.chat_id;
if (!chat_id) {
  throw new Error('chat_id tidak ditemukan dari payload Telegram');
}

const yt = original.render_payload?.youtube_metadata;
if (!yt) {
  throw new Error('youtube_metadata tidak ditemukan dari render_payload');
}

const video_id = original.video_id;
let files = result.files || [];

// FIX: If files is empty, use local storage path directly
let watermarkedVideo = null;
if (files.length === 0) {
  const wmPath = `free-viral-shorts/${video_id}/watermarked`;
  watermarkedVideo = {
    filename: `${video_id}_wm.mp4`,
    path: wmPath,
    absolute_path: wmPath,
    download_url: `${API_BASE_URL}/storage/free-viral-shorts/${video_id}/watermarked/${video_id}_wm.mp4`
  };
  console.log('[FALLBACK] Using local storage path:', wmPath);
} else {
  watermarkedVideo =
    files.find(file =>
      file.filename?.endsWith('.mp4') &&
      (file.filename.includes('_wm') || file.path?.includes('/watermarked/'))
    ) ||
    files.find(file => file.filename?.endsWith('.mp4'));
}

if (!watermarkedVideo) {
  throw new Error(`File video watermark tidak ditemukan. files=${JSON.stringify(files)}`);
}

const rawVideoPath = watermarkedVideo.absolute_path || watermarkedVideo.file_path || watermarkedVideo.path;
const video_path = rawVideoPath?.startsWith('/') ? rawVideoPath : rawVideoPath ? `/Users/agusrachman/Documents/Codex/content-short/storage/${rawVideoPath}` : null;

const video_download_url = watermarkedVideo.download_url || (watermarkedVideo.url ? `${API_BASE_URL}${watermarkedVideo.url}` : null);

if (!video_download_url) {
  throw new Error(`Download URL video tidak ditemukan: ${JSON.stringify(watermarkedVideo)}`);
}

const hashtags = Array.isArray(yt.hashtags) ? yt.hashtags.join(' ') : '';
const hookText = original.render_payload?.hook_3_5_seconds?.text || '-';
const thumbnailText = yt.thumbnail_text || '-';
const viralScore = original.render_payload?.viral_score ?? '-';
const clipType = original.render_payload?.clip_type || '-';
const duration = original.render_payload?.duration || original.render_payload?.calculated_duration || '-';

const caption = [yt.title || 'Video pendek', hashtags].filter(Boolean).join('\n\n').slice(0, 1024);

const metadata_text = [
  '✅ Render Watermark Selesai',
  '', `🎬 Title:\n${yt.title || '-'}`,
  '', `📝 Description:\n${yt.description || '-'}`,
  '', `🏷 Hashtags:\n${hashtags || '-'}`,
  '', `🖼 Thumbnail Text:\n${thumbnailText}`,
  '', `🪝 Hook:\n${hookText}`,
  '', `⭐ Viral Score:\n${viralScore}`,
  '', `🎭 Clip Type:\n${clipType}`,
  '', `⏱ Duration:\n${duration} detik`,
  '', `🔗 Source Video ID:\n${video_id}`,
  '', `📁 File:\n${watermarkedVideo.filename || video_path || video_download_url}`,
  '', `⬇️ Download:\n${video_download_url}`
].join('\n');

return [{
  json: { chat_id, video_id, video_path, video_download_url, caption, metadata_text, filename: watermarkedVideo.filename || video_path || video_download_url }
}];'''
            
            node['parameters']['jsCode'] = new_code
            print('Updated Prepare Telegram Payload code')
            break

    # Save
    with open('n8n_watermark_delivery_only.json', 'w') as f:
        json.dump(wf, f, indent=2)
    
    print('Saved n8n_watermark_delivery_only.json')

if __name__ == '__main__':
    main()
