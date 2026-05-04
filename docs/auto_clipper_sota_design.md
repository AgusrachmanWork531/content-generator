# Auto Clipper SOTA Design (Opus-Clip-Class)

## 1) Rekomendasi Algoritma Terbaik

### Intelligent Splitting
- **Audio front-end**: `librosa` RMS + peak envelope + spectral flux untuk deteksi momen intens.
- **VAD**: Silero VAD / WebRTC VAD untuk segment speech vs non-speech.
- **Transcript semantics**: ASR timestamped words (Whisper large-v3-turbo) -> sentence embedding (`bge-m3` / `e5-large`) -> semantic shift pakai cosine distance.
- **Visual events**:
  - Shot boundary: histogram diff + edge change ratio + PySceneDetect style adaptive detector.
  - Motion spike: dense optical flow magnitude (Farneback) + variance burst.
- **Change-point core**:
  - Offline high-quality: **ruptures PELT** + kernel CPD untuk timeline importance.
  - Streaming/low-latency: **Bayesian Online Change Point Detection (BOCPD)**.
- **Reason**: Kombinasi ini robust pada podcast, talking-head, dan multi-scene short-form karena tidak bergantung satu sinyal.

### Smart Object Focus (Auto Reframe)
- **Primary detector stack**:
  1. Face detector (RetinaFace/MediaPipe) sebagai prioritas.
  2. Person detector (YOLOv8/11 or RT-DETR) fallback.
  3. Active speaker score via sync audio-energy + mouth motion (lip ROI flow).
- **Tracker**:
  - Multi-object tracking: **ByteTrack/DeepSORT**.
  - Motion model: **Kalman Filter (constant velocity)**.
  - Short-term correction: Lucas-Kanade optical flow points di area wajah.
- **Camera path optimizer**:
  - Dead-zone + max pan speed.
  - EMA + jerk-limited easing (ease-in-out cubic).
  - Lookahead 5–15 frame untuk mengurangi lag.
- **Reason**: Struktur detector+tracker+path optimizer lebih stabil dari detector-only per-frame, dan minim jitter.

## 2) End-to-End Pipeline

1. **Input Ingestion**
   - Decode video/audio (ffmpeg), ambil fps, resolution, timebase.
2. **Feature Extraction (parallel)**
   - Audio: RMS, peak, spectral flux, VAD timeline.
   - Text: ASR + punctuation restore + keyword/intent/emotion cues.
   - Visual: shot change, optical-flow magnitude, face/person bboxes.
3. **Temporal Alignment**
   - Seluruh feature diresample ke grid 10 fps (100 ms per step).
4. **Importance Scoring**
   - `score(t)=wa*audio + ws*speech + wn*nlp + wv*visual + wc*context_shift`.
   - Normalize via robust z-score + sigmoid clipping.
5. **Change-Point & Split Proposal**
   - Jalankan CPD pada score dan semantic embedding drift.
   - Propose split jika peak prominence > threshold atau context shift kuat.
6. **Clip Assembler**
   - Constraint 15–60 detik, min gap antar split, hindari orphan segment.
   - Rule Hook-Context-Payoff dengan skor per sub-window.
7. **Auto Reframe Engine**
   - Pilih subject utama per frame (face/speaker weighted).
   - Tracking + smoothing + lookahead + adaptive zoom.
   - Render crop 9:16 (atau 1:1/4:5) dengan ffmpeg filtergraph.
8. **Post-QC**
   - Reject clip jika subtitle density terlalu rendah, blur/motion ekstrem, atau payoff score rendah.
9. **Output**
   - JSON EDL + clips final + metadata score explainability.

## 3) Parameter Optimal (Baseline Production)

### Splitting
- Timeline step: `0.1s`
- Clip min/max duration: `15s / 60s`
- Min split distance: `8s`
- CPD penalty (PELT): `beta=8..14` (naikkan jika over-split)
- Semantic shift threshold: cosine distance `>0.22`
- Peak prominence score threshold: `0.62`
- Weights default:
  - `wa(audio)=0.22`
  - `ws(vad/speech turn)=0.18`
  - `wn(nlp importance)=0.30`
  - `wv(visual motion/shot)=0.20`
  - `wc(context shift)=0.10`

### Reframing
- Detector conf threshold: face `0.45`, person `0.35`
- Track retention: `max_age=20` frame, `min_hits=3`
- EMA alpha posisi: `0.18` (static) -> `0.30` (dynamic)
- Max pan per frame: `1.5%` width
- Dead-zone: pusat ±`8%` width, ±`10%` height
- Lookahead: `8` frame (30fps) / `5` frame (24fps)
- Zoom range: `1.0x`–`1.22x`
- Zoom-in trigger: emotion/audio percentile `>75` + face stable `>=12` frame

## 4) Pseudocode Teknis

```python
# ---------- SPLITTING ----------
def build_importance_timeline(video):
    audio = extract_audio_features(video)  # rms, peak, flux
    vad = run_vad(video)
    asr = transcribe_with_timestamps(video)
    text_feat = nlp_importance(asr)        # keywords, novelty, sentiment arousal
    vis = visual_features(video)           # shot_cut_prob, flow_mag

    T = align_to_grid([audio, vad, text_feat, vis], step=0.1)
    semantic_drift = cosine_drift(T["sentence_embedding"])

    score = (
        0.22*z(audio["intensity"]) +
        0.18*z(vad["speech_turn"]) +
        0.30*z(text_feat["importance"]) +
        0.20*z(vis["activity"]) +
        0.10*z(semantic_drift)
    )
    score = sigmoid_clip(score)
    return T, score


def propose_splits(T, score):
    cpd_points = pelt_change_points(score, beta=10)
    peaks = find_prominent_peaks(score, thr=0.62)
    sem_shift = np.where(T["semantic_drift"] > 0.22)[0]

    candidates = union_nearby(cpd_points, peaks, sem_shift, tol_steps=8)
    candidates = enforce_min_distance(candidates, min_sec=8, step=0.1)

    clips = assemble_clips(
        candidates,
        min_len=15,
        max_len=60,
        objective="hook_context_payoff"
    )
    return clips

# ---------- AUTO REFRAME ----------
def auto_reframe(frames, audio_energy):
    tracks = init_tracker()  # ByteTrack/DeepSORT + Kalman
    cam_state = init_camera_state()

    for t, frame in enumerate(frames):
        det_faces = detect_faces(frame)
        det_objs = detect_persons(frame)
        detections = fuse_and_rank(det_faces, det_objs, audio_energy[t])

        tracks.update(detections)
        subject = select_primary_subject(tracks, strategy="speaker_or_motion")

        target_box = expand_with_padding(subject.box, pad=0.22)
        predicted_box = lookahead_predict(subject, k=8)
        target_box = blend(target_box, predicted_box, w=0.35)

        crop = compute_9x16_crop(target_box, anchor="rule_of_thirds")
        crop = apply_deadzone(crop, cam_state, dz=(0.08, 0.10))
        crop = limit_velocity(crop, cam_state, max_pan=0.015)
        crop = ease_in_out_update(crop, cam_state)

        zoom = adaptive_zoom(audio_energy[t], subject.stability)
        crop = apply_zoom(crop, zoom)

        write_crop(crop)
        cam_state = update_state(crop)

    return render_ffmpeg_from_crop_path()
```

## 5) FFmpeg Integration Pattern

- Gunakan mode 2-pass:
  1. Python menghasilkan `crop_path.json` (x,y,w,h per frame/step).
  2. FFmpeg menjalankan `sendcmd`/`zmq` dynamic crop, lalu encode H.264.
- Untuk subtitle-safe area, enforce margin bawah (mis. 12% tinggi frame) agar teks tidak menutup wajah.

## 6) Heuristic Production Anti-Failure

- **Anti over-splitting**: naikkan CPD penalty jika jumlah clips > target rate (mis. >1 clip/90 detik).
- **Anti jitter**: freeze camera jika confidence drop <0.35 selama <=0.5 detik.
- **No jump switch** (multi-object): dwell time min 1.2 detik sebelum pindah anchor.
- **Context guard**: jangan mulai clip di tengah kata (snap ke batas sentence + VAD edge).
- **Payoff guard**: penalti clip yang ending-nya low-energy tanpa conclusion cue.

## 7) Trade-off Analysis

- **Akurasi vs Performa**
  - ASR besar + embedding besar -> akurat tapi lambat.
  - Solusi: mode HQ (offline) vs mode Fast (real-time approximate).
- **Smoothness vs Responsiveness**
  - EMA alpha kecil -> cinematic smooth, tapi lambat mengikuti gerak cepat.
  - EMA alpha adaptif berdasarkan motion percentile adalah kompromi terbaik.
- **Stabilitas vs Variasi framing**
  - Dead-zone besar -> stabil tapi "kaku".
  - Dead-zone adaptif scene-aware memberi rasa natural.

## 8) Benchmark vs Tools Populer

### Opus Clip (umum)
- Kuat di hook detection berbasis transcript + virality heuristics.
- Sering kurang konsisten pada reframing multi-speaker cepat.

### Adobe Premiere Auto Reframe
- Bagus untuk single-subject tracking timeline editing.
- Kurang kuat pada pemilihan momen viral berbasis semantik lintas modal.

### Improvement agar unggul
1. **Unified multimodal score explainability** (debuggable per frame).
2. **Speaker-aware attention switching** (audio-visual sinkron) untuk podcast multi host.
3. **Hook-Context-Payoff objective** sebagai optimizer, bukan sekadar cut detector.
4. **Adaptive zoom by emotion** untuk storytelling yang terasa "editorial".

## 9) Suggested Deployment Modes

- **Fast mode (near real-time)**:
  - YOLO-n + WebRTC VAD + small embedding.
- **Quality mode (batch/prod)**:
  - RT-DETR/YOLOx + Silero VAD + Whisper large + PELT CPD + detailed smoothing.

Mode switch ini penting supaya biaya GPU tetap terkendali tanpa mengorbankan kualitas final untuk konten prioritas tinggi.
