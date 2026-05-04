 (cd "$(git rev-parse --show-toplevel)" && git apply --3way <<'EOF' 
diff --git a/app/services/clipper_engine.py b/app/services/clipper_engine.py
index c22e13ee45e103533adedcfd651d67a92ebc91fc..97f4f32e8022b826f4c2cd48214373f34ade81da 100644
--- a/app/services/clipper_engine.py
+++ b/app/services/clipper_engine.py
@@ -174,85 +174,105 @@ class ClipperEngine:
         return smoothed
 
     def render(self, input_path: str, output_path: str, metadata: List[Dict], original_width: int, original_height: int, title: str = None, ass_path: str = None, anti_bot_vfx: bool = True, use_broll: bool = False):
         """
         Phase 2 Dynamic Render Engine:
         - Detects layout_mode changes
         - Toggles between Single Focus and Split Screen
         """
         hw_encoder = self._detect_hw_encoder()
         stream = ffmpeg.input(input_path)
         
         v_std = stream.video.filter('fps', fps=30).filter('setpts', 'PTS-STARTPTS').filter('format', 'yuv420p')
         
         a_main = stream.audio.filter('asetpts', 'PTS-STARTPTS').filter('aresample', 48000).filter('loudnorm', I=-14, TP=-1, LRA=7)
         
         # 1. Prepare Tracking Expressions
         crop_w_split = int(original_height * (1080 / 960))
         crop_w_focus = int(original_height * (1080 / 1920))
         
         x_top_expr, x_bot_expr, x_focus_expr = [], [], []
         for i in range(len(metadata) - 1):
             t_s, t_e = metadata[i]['time'], metadata[i+1]['time']
             p_top = max(0, min(original_width - crop_w_split, metadata[i]['x_top'] * original_width - crop_w_split/2))
             p_bot = max(0, min(original_width - crop_w_split, metadata[i]['x_bot'] * original_width - crop_w_split/2))
             p_foc = max(0, min(original_width - crop_w_focus, ((metadata[i]['x_top'] + metadata[i]['x_bot'])/2) * original_width - crop_w_focus/2))
-            
-            x_top_expr.append(f"{p_top}*between(t,{t_s:.3f},{t_e:.3f})")
-            x_bot_expr.append(f"{p_bot}*between(t,{t_s:.3f},{t_e:.3f})")
-            x_focus_expr.append(f"{p_foc}*between(t,{t_s:.3f},{t_e:.3f})")
+
+            # Use half-open time windows [t_s, t_e) so exactly one segment is active.
+            # `between()` is inclusive on both ends and can cause one-frame overlaps,
+            # producing a sudden x-position spike (visual glitch) at segment boundaries.
+            gate = f"gte(t,{t_s:.3f})*lt(t,{t_e:.3f})"
+            x_top_expr.append(f"{p_top}*{gate}")
+            x_bot_expr.append(f"{p_bot}*{gate}")
+            x_focus_expr.append(f"{p_foc}*{gate}")
+
+        if metadata:
+            last = metadata[-1]
+            p_top = max(0, min(original_width - crop_w_split, last['x_top'] * original_width - crop_w_split/2))
+            p_bot = max(0, min(original_width - crop_w_split, last['x_bot'] * original_width - crop_w_split/2))
+            p_foc = max(0, min(original_width - crop_w_focus, ((last['x_top'] + last['x_bot'])/2) * original_width - crop_w_focus/2))
+            x_top_expr.append(f"{p_top}*gte(t,{last['time']:.3f})")
+            x_bot_expr.append(f"{p_bot}*gte(t,{last['time']:.3f})")
+            x_focus_expr.append(f"{p_foc}*gte(t,{last['time']:.3f})")
+        else:
+            # Metadata bisa kosong jika analisis gagal; gunakan center crop agar FFmpeg tetap valid.
+            default_top = max(0, (original_width - crop_w_split) / 2)
+            default_foc = max(0, (original_width - crop_w_focus) / 2)
+            x_top_expr.append(str(default_top))
+            x_bot_expr.append(str(default_top))
+            x_focus_expr.append(str(default_foc))
 
         # 2. Build Layer Nodes (Safe split syntax)
         splits1 = v_std.split()
         v_top_node = splits1[0]
         v_temp = splits1[1]
         
         splits2 = v_temp.split()
         v_bot_node = splits2[0]
         v_foc_node = splits2[1]
 
         v_top = v_top_node.filter('crop', crop_w_split, 'ih', x=" + ".join(x_top_expr), y=0).filter('scale', 1080, 960, force_original_aspect_ratio='increase').filter('crop', 1080, 960)
         v_bot = v_bot_node.filter('crop', crop_w_split, 'ih', x=" + ".join(x_bot_expr), y=0).filter('scale', 1080, 960, force_original_aspect_ratio='increase').filter('crop', 1080, 960)
         v_split_stack = ffmpeg.filter([v_top, v_bot], 'vstack')
         
         # Focus Layer (Single 9:16)
         v_focus = v_foc_node.filter('crop', crop_w_focus, 'ih', x=" + ".join(x_focus_expr), y=0).filter('scale', 1080, 1920, force_original_aspect_ratio='increase').filter('crop', 1080, 1920)
 
         # 3. Dynamic Switcher (Single Overlay Logic)
         # Combine all split segments into one expression to avoid multiple outgoing edges
         split_ranges = []
         if metadata:
             curr_mode = metadata[0]['layout_mode']
             start_t = metadata[0]['time']
             for m in metadata:
                 if m['layout_mode'] != curr_mode:
                     if curr_mode == 'split':
-                        split_ranges.append(f"between(t,{start_t:.3f},{m['time']:.3f})")
+                        split_ranges.append(f"gte(t,{start_t:.3f})*lt(t,{m['time']:.3f})")
                     curr_mode = m['layout_mode']
                     start_t = m['time']
             if curr_mode == 'split':
-                split_ranges.append(f"between(t,{start_t:.3f},{metadata[-1]['time'] + 1.0:.3f})")
+                split_ranges.append(f"gte(t,{start_t:.3f})")
 
         video = v_focus
         if split_ranges:
             combined_enable = "+".join(split_ranges)
             video = ffmpeg.filter([video, v_split_stack], 'overlay', enable=combined_enable)
 
         if ass_path and os.path.exists(ass_path):
             video = video.filter('ass', os.path.abspath(ass_path))
             
         video = video.filter('drawtext', text='KILASAN VIDEO', fontcolor='white', alpha=0.5, fontsize=40, x='(w-text_w)/2', y='(h-text_h)/2 + 200')
         if title:
             video = video.filter('drawtext', text=title.upper(), fontcolor='white', borderw=4, bordercolor='black', fontsize=75, x='(w-text_w)/2', y='(h-text_h)/2')
             
         video, audio = audio_engine.apply_bgm_with_ducking(video, a_main)
         
         import subprocess
         import time
 
         try:
             logger.info(f"Rendering Dynamic Phase 2 Output: {output_path}")
             vcodec_args = {'vcodec': hw_encoder, 'b:v': '10M'} if hw_encoder != 'libx264' else {'vcodec': 'libx264', 'crf': '19', 'preset': 'superfast'}
             
             output_node = ffmpeg.output(video, audio, output_path, **vcodec_args, acodec='aac', audio_bitrate='192k', map_metadata=-1)
             cmd = ffmpeg.compile(output_node.global_args('-fps_mode', 'cfr', '-r', '30', '-threads', '0'), overwrite_output=True)
             
 
EOF
)