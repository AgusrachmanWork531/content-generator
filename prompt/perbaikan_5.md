# Plan Adjustment: Split-Frame Optimal Configuration
# Analisa hasil render reframe_4d0bb8b4.mp4 — 2026-05-04

## Root Cause Diagnosa (dari screenshot)

| Bug | Sumber | Dampak |
|-----|--------|--------|
| Panel atas menampilkan badan/sofa, bukan wajah | `tbox = face_box or person_box` — jika person di kiri tidak punya `face_box`, crop mengambil `person_box` yang mencakup torso/kaki | Framing tidak memusat ke wajah |
| `tcy = center Y person_box` | Pada subjek yang hanya terlihat dari pinggang ke bawah, center Y justru di area perut/pinggang | Subjek keluar frame atas |
| `sc_h = height // 2` fix (tidak adaptif) | Panel selalu split 50% meski aspect wajah membutuhkan porsi berbeda | Komposisi terlihat kaku |
| `sc_w = sc_h * (out_w / half_h)` | Rasio sc_w dihitung dari panel height, bukan dari target crop width yang konsisten | Distorsi proporsi antar panel |
| Tidak ada Y-anchor khusus per panel | Wajah tidak selalu di 1/3 atas panel; bisa berada di tengah atau bawah | Komposisi tidak natural |

---

## Adjustment Plan (5 Tahapan)

### Tahap 1 — Face-First Box Selection (Priority Fix)

**Problem**: Banyak subjek tidak punya `face_box` saat terdeteksi dari samping/jauh.

**Fix**:
- Tambah logika fallback bertingkat:
  1. Gunakan `face_box` jika ada.
  2. Jika tidak ada, perkirakan area wajah dari **1/4 teratas person_box** (head region estimasi).
  3. Fallback ke `person_box` center hanya jika estimasi gagal.

```python
def _best_face_target(det: Dict) -> List[int]:
    if det["face_box"]:
        return det["face_box"]
    pb = det["person_box"]
    # Estimate head region: top 25% of person box
    head_h = (pb[3] - pb[1]) * 0.25
    return [pb[0], pb[1], pb[2], int(pb[1] + head_h)]
```

---

### Tahap 2 — Face Y-Anchor 25% per Panel (Composition Fix)

**Problem**: Wajah di panel bisa jatuh di posisi sembarang.

**Fix**: Setiap panel harus menempatkan wajah di **25% dari atas panel**, bukan di center.

```python
# Y anchor: face should appear at 25% from top of panel
face_top = tcy - (sc_h * 0.25)
sy1 = max(0, min(height - sc_h, int(face_top)))
```

---

### Tahap 3 — Adaptive Panel Height (Proportional Fix)

**Problem**: `half_h = out_h // 2` fix, tidak mempertimbangkan proporsi tubuh vs. wajah.

**Fix**: Ukuran panel tetap 50/50 untuk saat ini, tapi tambahkan **1px separator** antar panel untuk visual clarity, dan pertimbangkan kelak adaptive ratio 60/40 untuk speaker aktif.

```python
SEPARATOR_PX = 4  # pixel separator hitam antar panel
panel_1_h = (out_h - SEPARATOR_PX) // 2
panel_2_h = out_h - SEPARATOR_PX - panel_1_h
separator = np.zeros((SEPARATOR_PX, out_w, 3), dtype=np.uint8)
output_frame = np.vstack([panel_top, separator, panel_bottom])
```

---

### Tahap 4 — Consistent Crop Width per Panel (Aspect Fix)

**Problem**: `sc_w = sc_h * (out_w / half_h)` — rasio ini benar secara matematis tapi sc_h yang fix membuat sc_w tidak proporsional terhadap sumber.

**Fix**: Hitung sc_w dari **ASPECT_RATIO global** seperti TRACK mode:

```python
# Panel crop = same aspect ratio as output (9:16)
# out_w / out_h_panel = sc_w / sc_h  → sc_w = sc_h * (out_w / panel_h)
panel_h = panel_1_h  # atau panel_2_h
sc_h = int(height * 0.55)  # ambil 55% dari frame height agar ada zoom alami
sc_w = int(sc_h * (out_w / panel_h))
sc_w = min(sc_w, width)
sc_h = min(sc_h, height)
```

---

### Tahap 5 — Hysteresis Guard (Stability Fix)

**Problem**: Scene bisa flip dari TRACK → SPLIT → LETTERBOX dalam 1 detik → visual jarring.

**Fix**: Tambahkan **minimum hold counter** di `ClipperEngine`:

```python
# In ClipperEngine.__init__:
self._last_strategy = "LETTERBOX"
self._strategy_hold_frames = 0
STRATEGY_MIN_HOLD = 30  # ~1 detik di 30fps

# In render loop sebelum apply strategy:
if scene["strategy"] != self._last_strategy:
    if self._strategy_hold_frames < STRATEGY_MIN_HOLD:
        scene = {"strategy": self._last_strategy, "target_box": self._last_target}
    else:
        self._last_strategy = scene["strategy"]
        self._last_strategy_hold = 0
        self._last_target = scene["target_box"]
self._strategy_hold_frames += 1
```

---

## Summary: Konfigurasi Optimal Split-Frame

| Parameter | Nilai Lama | Nilai Optimal Baru |
|-----------|-----------|-------------------|
| Face target selection | `face_box or person_box` | `face_box` → head-region estimasi → `person_box` |
| Panel Y-anchor | center Y subjek | 25% dari atas panel |
| sc_h per panel | `height // 2` (fix) | `height * 0.55` (adaptive zoom) |
| sc_w per panel | `sc_h * (out_w / half_h)` | `sc_h * (out_w / panel_h)` (konsisten) |
| Panel separator | tidak ada | 4px separator hitam |
| Strategy hysteresis | tidak ada | hold minimum 30 frame |
| SPLIT trigger | jika n ≥ 2 dan terlalu lebar | jika n == 2 **dan kedua punya estimasi wajah** |

---

## Urutan Eksekusi Fix

1. `_best_face_target()` helper function → tackle root cause segera.
2. Y-anchor 25% per panel → composition natural.
3. sc_h 55% + separator → visual polish.
4. Hysteresis di render loop → stabilitas.

File: `app/services/clipper_engine.py`
