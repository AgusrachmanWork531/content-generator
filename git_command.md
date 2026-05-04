 (cd "$(git rev-parse --show-toplevel)" && git apply --3way <<'EOF' 
diff --git a/app/services/clipper_engine.py b/app/services/clipper_engine.py
index 12724d0e631c19ac38a495040b697ed986580098..d817c0a589dfdb3199b019b5e7e8fc4e80e38fc1 100644
--- a/app/services/clipper_engine.py
+++ b/app/services/clipper_engine.py
@@ -97,167 +97,223 @@ class ClipperEngine:
         target_mode = "split" if dist > 0.5 else "focus"
         
         # 2. Hysteresis Check
         if state_duration < MIN_STATE_DURATION:
             return last_mode
             
         return target_mode
 
     def analyze_video(self, video_path: str):
         cap = cv2.VideoCapture(video_path)
         fps = 30
         width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
         height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
         total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
         
         metadata = []
         frame_idx = 0
         last_x_top, last_x_bot = 0.5, 0.5
         last_mode = "focus"
         state_start_time = 0.0
         last_frame_gray = None
         DEAD_ZONE = 0.05
         
         logger.info(f"Starting Phase 2 AI Forensic Analysis: {video_path}")
         
+        sample_interval = 1  # per-frame sampling for temporal consistency
+        history_len = max(5, min(10, int(fps // 3)))
+        min_detection_delta = 0.01
+        velocity_alpha = 0.3
+        max_velocity = 0.06  # normalized x per frame
+        hold_frames_on_drop = max(5, int(fps * 0.25))
+        top_hist: List[float] = [0.5]
+        bot_hist: List[float] = [0.5]
+        vel_top = 0.0
+        vel_bot = 0.0
+        lost_counter = 0
+
         while True:
             ret, frame = cap.read()
             if not ret: break
             
-            if frame_idx % int(fps) == 0:
+            if frame_idx % sample_interval == 0:
                 current_time = frame_idx / fps
                 gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                 
                 # Motion Scoring
                 motion_score = 0.0
                 if last_frame_gray is not None:
                     diff = cv2.absdiff(gray, last_frame_gray)
                     motion_score = np.mean(diff) / 255.0
                 last_frame_gray = gray
                 
                 # Dual Tracking
-                x_top, x_bot = self.get_split_centers(frame)
-                
-                if abs(x_top - last_x_top) < DEAD_ZONE: x_top = last_x_top
-                if abs(x_bot - last_x_bot) < DEAD_ZONE: x_bot = last_x_bot
+                raw_top, raw_bot = self.get_split_centers(frame)
+                detection_valid = not (abs(raw_top - 0.5) < 1e-6 and abs(raw_bot - 0.5) < 1e-6)
+
+                if not detection_valid:
+                    lost_counter += 1
+                else:
+                    lost_counter = 0
+
+                if detection_valid:
+                    if abs(raw_top - last_x_top) < min_detection_delta:
+                        raw_top = last_x_top
+                    if abs(raw_bot - last_x_bot) < min_detection_delta:
+                        raw_bot = last_x_bot
+                elif lost_counter <= hold_frames_on_drop:
+                    raw_top, raw_bot = last_x_top, last_x_bot
+                else:
+                    raw_top = last_x_top + vel_top
+                    raw_bot = last_x_bot + vel_bot
+
+                top_hist.append(raw_top)
+                bot_hist.append(raw_bot)
+                top_hist = top_hist[-history_len:]
+                bot_hist = bot_hist[-history_len:]
+                avg_top = float(np.mean(top_hist))
+                avg_bot = float(np.mean(bot_hist))
+
+                pred_top = last_x_top + vel_top
+                pred_bot = last_x_bot + vel_bot
+                target_top = (0.6 * avg_top) + (0.4 * pred_top)
+                target_bot = (0.6 * avg_bot) + (0.4 * pred_bot)
+
+                step_top = np.clip(target_top - last_x_top, -max_velocity, max_velocity)
+                step_bot = np.clip(target_bot - last_x_bot, -max_velocity, max_velocity)
+                x_top = float(np.clip(last_x_top + step_top, 0.0, 1.0))
+                x_bot = float(np.clip(last_x_bot + step_bot, 0.0, 1.0))
+
+                vel_top = (velocity_alpha * step_top) + ((1 - velocity_alpha) * vel_top)
+                vel_bot = (velocity_alpha * step_bot) + ((1 - velocity_alpha) * vel_bot)
                 
                 # ── Phase 2: Decision Engine ──
                 current_mode = self.decide_layout(x_top, x_bot, last_mode, current_time - state_start_time)
                 if current_mode != last_mode:
                     state_start_time = current_time
                     last_mode = current_mode
                 
                 last_x_top, last_x_bot = x_top, x_bot
                 importance = min(1.0, (motion_score * 5.0) + 0.5) 
                 
                 metadata.append({
                     "time": current_time,
                     "x_top": float(x_top),
                     "x_bot": float(x_bot),
                     "layout_mode": current_mode,
                     "importance": float(importance),
                     "is_peak": importance > 0.8
                 })
             
             frame_idx += 1
             if frame_idx >= total_frames: break
                 
         cap.release()
         return metadata, fps, width, height
 
     def smooth_centers(self, metadata: List[Dict]):
         if not metadata: return []
         smooth_f = 0.15
         smoothed = [m.copy() for m in metadata]
         for i in range(1, len(metadata)):
             smoothed[i]['x_top'] = smooth_f * metadata[i]['x_top'] + (1 - smooth_f) * smoothed[i-1]['x_top']
             smoothed[i]['x_bot'] = smooth_f * metadata[i]['x_bot'] + (1 - smooth_f) * smoothed[i-1]['x_bot']
         return smoothed
 
+    def _build_ease_expr(self, metadata: List[Dict], crop_w: int, original_width: int, target: str) -> str:
+        if not metadata:
+            return str(max(0, (original_width - crop_w) / 2))
+
+        expr_parts = []
+        for i in range(len(metadata) - 1):
+            curr = metadata[i]
+            nxt = metadata[i + 1]
+            t_s, t_e = curr['time'], nxt['time']
+            dt = max(1e-6, t_e - t_s)
+
+            if target == 'focus':
+                c_curr = (curr['x_top'] + curr['x_bot']) / 2
+                c_next = (nxt['x_top'] + nxt['x_bot']) / 2
+            else:
+                c_curr = curr[target]
+                c_next = nxt[target]
+
+            p_curr = max(0, min(original_width - crop_w, c_curr * original_width - crop_w / 2))
+            p_next = max(0, min(original_width - crop_w, c_next * original_width - crop_w / 2))
+            delta = p_next - p_curr
+            nt = f"((t-{t_s:.3f})/{dt:.6f})"
+            ease = f"(3*pow({nt},2)-2*pow({nt},3))"  # smoothstep ease-in-out
+            gate = f"gte(t,{t_s:.3f})*lt(t,{t_e:.3f})"
+            expr_parts.append(f"(({p_curr:.3f})+({delta:.3f})*{ease})*{gate}")
+
+        last = metadata[-1]
+        if target == 'focus':
+            c_last = (last['x_top'] + last['x_bot']) / 2
+        else:
+            c_last = last[target]
+
+        p_last = max(0, min(original_width - crop_w, c_last * original_width - crop_w / 2))
+        expr_parts.append(f"({p_last:.3f})*gte(t,{last['time']:.3f})")
+
+        return " + ".join(expr_parts)
+
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
         
-        x_top_expr, x_bot_expr, x_focus_expr = [], [], []
-        for i in range(len(metadata) - 1):
-            t_s, t_e = metadata[i]['time'], metadata[i+1]['time']
-            p_top = max(0, min(original_width - crop_w_split, metadata[i]['x_top'] * original_width - crop_w_split/2))
-            p_bot = max(0, min(original_width - crop_w_split, metadata[i]['x_bot'] * original_width - crop_w_split/2))
-            p_foc = max(0, min(original_width - crop_w_focus, ((metadata[i]['x_top'] + metadata[i]['x_bot'])/2) * original_width - crop_w_focus/2))
-            
-            # Use half-open time windows [t_s, t_e) so exactly one segment is active.
-            # `between()` is inclusive on both ends and can cause one-frame overlaps,
-            # producing a sudden x-position spike (visual glitch) at segment boundaries.
-            gate = f"gte(t,{t_s:.3f})*lt(t,{t_e:.3f})"
-            x_top_expr.append(f"{p_top}*{gate}")
-            x_bot_expr.append(f"{p_bot}*{gate}")
-            x_focus_expr.append(f"{p_foc}*{gate}")
-
-        if metadata:
-            last = metadata[-1]
-            p_top = max(0, min(original_width - crop_w_split, last['x_top'] * original_width - crop_w_split/2))
-            p_bot = max(0, min(original_width - crop_w_split, last['x_bot'] * original_width - crop_w_split/2))
-            p_foc = max(0, min(original_width - crop_w_focus, ((last['x_top'] + last['x_bot'])/2) * original_width - crop_w_focus/2))
-            x_top_expr.append(f"{p_top}*gte(t,{last['time']:.3f})")
-            x_bot_expr.append(f"{p_bot}*gte(t,{last['time']:.3f})")
-            x_focus_expr.append(f"{p_foc}*gte(t,{last['time']:.3f})")
-        else:
-            # Metadata bisa kosong jika analisis gagal; gunakan center crop agar FFmpeg tetap valid.
-            default_top = max(0, (original_width - crop_w_split) / 2)
-            default_foc = max(0, (original_width - crop_w_focus) / 2)
-            x_top_expr.append(str(default_top))
-            x_bot_expr.append(str(default_top))
-            x_focus_expr.append(str(default_foc))
+        x_top_expr = self._build_ease_expr(metadata, crop_w_split, original_width, 'x_top')
+        x_bot_expr = self._build_ease_expr(metadata, crop_w_split, original_width, 'x_bot')
+        x_focus_expr = self._build_ease_expr(metadata, crop_w_focus, original_width, 'focus')
 
         # 2. Build Layer Nodes (Safe split syntax)
         splits1 = v_std.split()
         v_top_node = splits1[0]
         v_temp = splits1[1]
         
         splits2 = v_temp.split()
         v_bot_node = splits2[0]
         v_foc_node = splits2[1]
 
-        v_top = v_top_node.filter('crop', crop_w_split, 'ih', x=" + ".join(x_top_expr), y=0).filter('scale', 1080, 960, force_original_aspect_ratio='increase').filter('crop', 1080, 960)
-        v_bot = v_bot_node.filter('crop', crop_w_split, 'ih', x=" + ".join(x_bot_expr), y=0).filter('scale', 1080, 960, force_original_aspect_ratio='increase').filter('crop', 1080, 960)
+        v_top = v_top_node.filter('crop', crop_w_split, 'ih', x=x_top_expr, y=0).filter('scale', 1080, 960, force_original_aspect_ratio='increase').filter('crop', 1080, 960)
+        v_bot = v_bot_node.filter('crop', crop_w_split, 'ih', x=x_bot_expr, y=0).filter('scale', 1080, 960, force_original_aspect_ratio='increase').filter('crop', 1080, 960)
         v_split_stack = ffmpeg.filter([v_top, v_bot], 'vstack')
         
         # Focus Layer (Single 9:16)
-        v_focus = v_foc_node.filter('crop', crop_w_focus, 'ih', x=" + ".join(x_focus_expr), y=0).filter('scale', 1080, 1920, force_original_aspect_ratio='increase').filter('crop', 1080, 1920)
+        v_focus = v_foc_node.filter('crop', crop_w_focus, 'ih', x=x_focus_expr, y=0).filter('scale', 1080, 1920, force_original_aspect_ratio='increase').filter('crop', 1080, 1920)
 
         # 3. Dynamic Switcher (Single Overlay Logic)
         # Combine all split segments into one expression to avoid multiple outgoing edges
         split_ranges = []
         if metadata:
             curr_mode = metadata[0]['layout_mode']
             start_t = metadata[0]['time']
             for m in metadata:
                 if m['layout_mode'] != curr_mode:
                     if curr_mode == 'split':
                         split_ranges.append(f"gte(t,{start_t:.3f})*lt(t,{m['time']:.3f})")
                     curr_mode = m['layout_mode']
                     start_t = m['time']
             if curr_mode == 'split':
                 split_ranges.append(f"gte(t,{start_t:.3f})")
 
         video = v_focus
         if split_ranges:
             combined_enable = "+".join(split_ranges)
             video = ffmpeg.filter([video, v_split_stack], 'overlay', enable=combined_enable)
 
         if ass_path and os.path.exists(ass_path):
             video = video.filter('ass', os.path.abspath(ass_path))
             
         video = video.filter('drawtext', text='KILASAN VIDEO', fontcolor='white', alpha=0.5, fontsize=40, x='(w-text_w)/2', y='(h-text_h)/2 + 200')
 
EOF
)