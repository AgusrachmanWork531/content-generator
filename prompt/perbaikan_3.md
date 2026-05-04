Berikut prompt yang bisa langsung kamu pakai untuk “memerintah” AI agent / dev system kamu memperbaiki VAD pipeline—sudah disusun dengan konteks masalah yang kamu alami (silero-vad-lite + error 512):

---

# 🎯 PROMPT PERBAIKAN VAD PIPELINE (LEVEL PRO)

````md
You are a senior audio AI engineer specializing in real-time video clipping systems (similar to Opus Clip).

Your task is to refactor and FIX a Voice Activity Detection (VAD) pipeline that is currently failing with error:

"Data length must be equal to the window size (512)"

## 🔍 ROOT PROBLEM
The system uses `silero-vad-lite`, but incorrectly feeds the model with full audio arrays instead of fixed-size frames (512 samples @ 16kHz). The model expects streaming-style frame input.

---

## 🎯 OBJECTIVES

1. Fix the VAD pipeline to comply with silero-vad-lite requirements
2. Ensure stable and accurate speech detection
3. Optimize for clipper engine usage (hook detection, highlight extraction)
4. Prevent runtime crashes and edge-case failures

---

## 🔧 REQUIRED FIXES

### 1. Enforce Correct Audio Format
- Sample rate MUST be 16kHz
- Mono channel only
- Float32 normalized [-1, 1]

---

### 2. Replace Full-Audio Inference with Streaming Frame Processing

Refactor from:
```python
model.get_speech_timestamps(audio)
````

To:

* Slice audio into FIXED frames:

  * window_size = 512
  * step = 512 (no overlap for now)

* Process like:

```python
for i in range(0, len(audio), 512):
    chunk = audio[i:i+512]

    if len(chunk) < 512:
        pad with zeros

    prob = model(chunk)
```

---

### 3. Build Speech Timeline from Probabilities

* Convert probabilities → binary mask
* Threshold = 0.5 (configurable)
* Generate speech segments using:

  * start when speech begins
  * end when speech ends

---

### 4. Add Temporal Smoothing (CRITICAL for clipper quality)

Implement:

* Minimum speech duration: 200ms
* Merge silence gaps < 300ms
* Remove micro-noise segments

---

### 5. Output Format

Return:

```json
[
  { "start": <seconds>, "end": <seconds> }
]
```

---

### 6. Stability & Edge Case Handling

* Handle empty audio
* Handle very short clips (<512 samples)
* Avoid crash on model failure
* Log errors clearly

---

### 7. Performance Optimization

* Avoid loading full audio into memory for long videos
* Prepare pipeline for future streaming (chunk-by-chunk processing)
* Avoid unnecessary padding of entire signal

---

## 🚀 OPTIONAL (HIGHLY RECOMMENDED)

Add scoring layer for clipper intelligence:

* Speech density score
* Turn-taking detection
* Silence contrast scoring

This will later be used for:
→ Hook detection
→ Viral moment extraction

---

## 🧠 DESIGN PRINCIPLES

* Streaming-first architecture
* Deterministic frame processing
* Low latency ready
* Modular (plug into clipper engine)

---

## 📦 DELIVERABLE

Produce:

1. Refactored VAD function
2. Clean modular code
3. Comments explaining each stage
4. Optimized for production use in clipper engine

---

Think like you are building the VAD core of a viral video clipping AI system competing with Opus Clip.

````

---

## 🔥 Bonus (biar agent kamu makin “pinter”)
Kalau mau sekalian loncat level, tambahin ini di akhir prompt:

```md
Additionally, suggest improvements to align VAD output with subtitle timing and scene detection for maximum hook accuracy.
````

---

## 🧩 Kenapa prompt ini powerful

Ini bukan cuma “fix error 512”, tapi:

* Ngubah arsitektur → dari batch ke streaming
* Siap dipakai buat:

  * highlight detection
  * auto clip selection
  * subtitle sync

---

Kalau kamu lanjutkan pipeline ini, next bottleneck biasanya:
👉 **subtitle timing + scene cut mismatch**

Kalau mau, gue bisa bantu bikin:

* prompt khusus untuk **hook scoring engine**
* atau nyatuin VAD + subtitle + visual cut jadi “viral detector” 😏
