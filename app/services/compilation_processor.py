import os
import uuid
import logging
import asyncio
import subprocess
import random
import shlex
from typing import List, Dict, Any
from app.services.youtube import download_youtube_clip, crop_video
from app.services.transcriber import transcriber_service
from app.services.subtitle import subtitle_service
from app.services.opening_narrator import TRANSITION_MODELS
from app.core.config import settings

logger = logging.getLogger(__name__)

class CompilationProcessor:
    def __init__(self):
        self.tmp_dir = settings.TMP_DIR
        os.makedirs(self.tmp_dir, exist_ok=True)
        # Jalur font yang lebih aman (Escape spasi untuk FFmpeg filter)
        self.font_path = "/System/Library/Fonts/Supplemental/Arial Black.ttf".replace(" ", "\\ ")

    async def _get_video_duration(self, video_path: str) -> float:
        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                video_path
            ]
            proc = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, _ = await proc.communicate()
            return float(stdout.decode().strip())
        except Exception as e:
            logger.error(f"Failed to get duration for {video_path}: {e}")
            return 0.0

    async def merge_videos(self, video_paths: List[str], output_path: str, use_transitions: bool = False):
        if not video_paths:
            raise ValueError("No video paths provided for merging.")

        target_w, target_h, target_fps = 1920, 1080, 30
        inputs = []
        for path in video_paths:
            inputs.extend(["-i", path])

        filter_chains = []
        
        # 1. Base Scaling
        for i in range(len(video_paths)):
            v_label = f"v{i}raw"
            a_label = f"a{i}raw"
            
            # Base chain
            v_filter = f"[{i}:v]scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={target_fps}"
            
            filter_chains.append(f"{v_filter}[{v_label}]")
            filter_chains.append(f"[{i}:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[{a_label}]")

        # 2. Transitions or Simple Concat
        if not use_transitions or len(video_paths) < 2:
            concat_v_inputs = "".join([f"[v{i}raw]" for i in range(len(video_paths))])
            concat_a_inputs = "".join([f"[a{i}raw]" for i in range(len(video_paths))])
            filter_chains.append(f"{concat_v_inputs}concat=n={len(video_paths)}:v=1:a=0[v_merged]")
            filter_chains.append(f"{concat_a_inputs}concat=n={len(video_paths)}:v=0:a=1[a_merged]")
            current_v = "v_merged"
            current_a = "a_merged"
        else:
            durations = [await self._get_video_duration(p) for p in video_paths]
            prev_v, prev_a = "v0raw", "a0raw"
            cumulative_dur = durations[0]
            sfx_paths = []

            for i in range(1, len(video_paths)):
                m_name, xfade_type, xfade_dur, sfx_filter, sfx_vol = random.choice(TRANSITION_MODELS)
                offset = max(0, cumulative_dur - xfade_dur)
                
                v_out, a_out = f"v_xfade_{i}", f"a_xfade_{i}"
                filter_chains.append(f"[{prev_v}][v{i}raw]xfade=transition={xfade_type}:duration={xfade_dur}:offset={offset}[{v_out}]")
                filter_chains.append(f"[{prev_a}][a{i}raw]acrossfade=d={xfade_dur}[{a_out}_pre]")
                
                # Async SFX Generation
                uid = uuid.uuid4().hex[:8]
                sfx_p = os.path.join(self.tmp_dir, f"trans_sfx_{i}_{uid}.mp3")
                sfx_paths.append(sfx_p)
                sfx_cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", sfx_filter, "-ar", "44100", "-c:a", "libmp3lame", sfx_p]
                sfx_proc = await asyncio.create_subprocess_exec(*sfx_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                await sfx_proc.wait()

                inputs.extend(["-i", sfx_p])
                sfx_idx = inputs.count("-i") - 1
                filter_chains.append(f"[{sfx_idx}:a]adelay={int(offset*1000)}|{int(offset*1000)},aresample=44100[sfx{i}]")
                filter_chains.append(f"[{a_out}_pre][sfx{i}]amix=inputs=2:weights=1 {sfx_vol}:normalize=0[{a_out}]")
                
                prev_v, prev_a = v_out, a_out
                cumulative_dur += durations[i] - xfade_dur
            
            current_v, current_a = prev_v, prev_a



        # Final Assembly
        full_filter = ";".join(filter_chains)
        cmd = ["ffmpeg", "-y"] + inputs + [
            "-filter_complex", full_filter,
            "-map", f"[{current_v}]",
            "-map", f"[{current_a}]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-b:a", "192k",
            output_path
        ]

        logger.info(f"Executing FFmpeg with {len(inputs)//2} inputs...")
        try:
            process = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            _, stderr = await process.communicate()

            if process.returncode != 0:
                raise Exception(f"FFmpeg failed: {stderr.decode()[-500:]}")
        finally:
            if 'sfx_paths' in locals():
                for p in sfx_paths:
                    if os.path.exists(p):
                        try:
                            os.remove(p)
                        except Exception:
                            pass

    async def apply_overlays(self, input_path: str, output_path: str, watermark: bool = False, logo: bool = False):
        if not watermark and not logo:
            os.rename(input_path, output_path)
            return

        inputs = ["-i", input_path]
        filter_chains = []
        current_v = "0:v"

        if logo:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            logo_path = next((os.path.join(base_dir, "assets", f"logo.{ext}") for ext in ["png", "jpg", "jpeg"] if os.path.exists(os.path.join(base_dir, "assets", f"logo.{ext}"))), None)
            
            if logo_path:
                logo_idx = inputs.count("-i")
                inputs.extend(["-loop", "1", "-i", logo_path])
                v_logo = f"v_logo_{uuid.uuid4().hex[:4]}"
                filter_chains.append(f"[{logo_idx}:v]scale=140:-1[{logo_idx}_scaled]")
                # Adjusted x margin to 96px (5% of 1920px) to comply with Action Safe Zone standards.
                filter_chains.append(f"[{current_v}][{logo_idx}_scaled]overlay=x=main_w-overlay_w-96:y=60:shortest=1[{v_logo}]")
                current_v = v_logo

        if watermark:
            v_wm = f"v_wm_{uuid.uuid4().hex[:4]}"
            # Repositioned to top-right below the logo (y=210 for tighter gap), significantly reduced scale (fontsize=40),
            # and lowered opacity to 18% for a non-intrusive look. Horizontal margin aligned to 96px.
            filter_chains.append(
                f"[{current_v}]drawtext=text='KILASAN VIDEO':fontcolor=white@0.18:fontsize=40:"
                f"x=w-text_w-96:y=210:fontfile='{self.font_path}'[{v_wm}]"
            )
            current_v = v_wm

        cmd = ["ffmpeg", "-y"] + inputs
        
        if filter_chains:
            full_filter = ";".join(filter_chains)
            cmd.extend(["-filter_complex", full_filter, "-map", f"[{current_v}]", "-map", "0:a"])
        else:
            cmd.extend(["-c", "copy"])

        cmd.extend(["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "copy", output_path])
        
        logger.info(f"Applying overlays (watermark={watermark}, logo={logo})...")
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise Exception(f"Overlay FFmpeg failed: {stderr.decode()[-500:]}")

    async def apply_title_overlay(self, input_path: str, output_path: str, title: str):
        """Fungsi independen untuk menambahkan teks judul (Final Title) di pojok kiri atas."""
        if not title:
            os.rename(input_path, output_path)
            return
            
        import textwrap
        
        # Batasi panjang maksimal 50% dari layar (sekitar 45 karakter per baris untuk font size 36)
        # Paksa ke UPPERCASE sesuai permintaan user
        wrapped_title = textwrap.fill(title.upper(), width=45)
        
        # Write title to a temporary text file to completely bypass FFmpeg's character escaping hell
        title_txt_path = os.path.join(self.tmp_dir, f"title_text_{uuid.uuid4().hex[:8]}.txt")
        with open(title_txt_path, "w", encoding="utf-8") as f:
            f.write(wrapped_title)
            
        safe_txt_path = title_txt_path.replace("\\", "/").replace(":", "\\:")
        
        # Konfigurasi: 5% safe-zone margin (x=96, y=60).
        # Font Arial Black tebal (24), warna solid putih dengan border hitam tebal,
        # lebih kecil dari sebelumnya untuk tampilan yang lebih rapi.
        v_title = f"v_title_{uuid.uuid4().hex[:4]}"
        filter_complex = (
            f"[0:v]drawtext=textfile='{safe_txt_path}':fontcolor=white:fontsize=24:x=96:y=60:"
            f"fontfile='{self.font_path}':borderw=3:bordercolor=black:line_spacing=-2[{v_title}]"
        )
        
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-filter_complex", filter_complex,
            "-map", f"[{v_title}]", "-map", "0:a",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "copy",
            output_path
        ]
        
        try:
            logger.info(f"Applying independent title overlay: {title}")
            proc = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise Exception(f"Title Overlay FFmpeg failed: {stderr.decode()[-500:]}")
        finally:
            if os.path.exists(title_txt_path):
                try:
                    os.remove(title_txt_path)
                except:
                    pass

    async def process_compilation(self, compilation_id: str, clips: List[Dict[str, Any]]) -> str:
        """
        Main entry point for processing a compilation.
        Flow: Download/Trim Clips (Parallel) -> Merge -> Subtitle Merged Video.
        """
        intermediate_files = set()
        
        # 1. Deduplicate clips based on URL + Start + End to prevent redundant processing
        unique_clips = []
        seen_signatures = set()
        for clip in clips:
            url = clip.get('url', '')
            start = clip.get('start_time', '') or '0'
            end = clip.get('end_time', '') or '0'
            sig = f"{url}_{start}_{end}"
            if sig not in seen_signatures:
                seen_signatures.add(sig)
                unique_clips.append(clip)
            else:
                logger.info(f"Skipping exactly duplicated clip: {sig}")
        
        clips = unique_clips

        if not clips:
            raise ValueError(f"No valid clips found for compilation {compilation_id}")

        download_locks = {}

        try:
            async def process_clip(clip):
                url = clip['url']
                start_time = clip.get('start_time', "0")
                end_time = clip.get('end_time')
                final_title = clip.get('final_title', '')

                # 2. Prevent concurrent downloads of the same URL using asyncio.Lock
                if url not in download_locks:
                    download_locks[url] = asyncio.Lock()
                
                async with download_locks[url]:
                    filename = await asyncio.to_thread(download_youtube_clip, url)
                
                full_video_path = os.path.join(self.tmp_dir, filename)
                intermediate_files.add(full_video_path)

                working_path = full_video_path
                if start_time or end_time:
                    trim_id = str(uuid.uuid4())[:8]
                    trimmed_filename = f"trim_{trim_id}.mp4"
                    trimmed_path = os.path.join(self.tmp_dir, trimmed_filename)
                    await asyncio.to_thread(crop_video, full_video_path, trimmed_path, start_time, end_time)
                    intermediate_files.add(trimmed_path)
                    working_path = trimmed_path

                if final_title:
                    title_id = str(uuid.uuid4())[:8]
                    title_filename = f"title_{title_id}.mp4"
                    title_path = os.path.join(self.tmp_dir, title_filename)
                    await self.apply_title_overlay(working_path, title_path, final_title)
                    intermediate_files.add(title_path)
                    working_path = title_path

                return working_path

            # 1. Process clips in parallel (Download & Trim only)
            tasks = [process_clip(clip) for clip in clips]
            processed_paths = await asyncio.gather(*tasks)

            # 2. Merge all clips into one intermediate video
            merge_id = uuid.uuid4().hex[:8]
            merged_filename = f"merged_{compilation_id}_{merge_id}.mp4"
            merged_path = os.path.join(self.tmp_dir, merged_filename)
            intermediate_files.add(merged_path)
            
            # Respect the transitions configuration from Google Sheets (Column P)
            use_transitions = clips[0].get('transitions', False) if clips else False
            await self.merge_videos(processed_paths, merged_path, use_transitions=use_transitions)
            
            # 2.5 Apply Configurable Overlays
            overlay_id = uuid.uuid4().hex[:8]
            overlay_path = os.path.join(self.tmp_dir, f"overlay_{compilation_id}_{overlay_id}.mp4")
            
            # Configs can be driven by clips metadata (defaulting to True for demonstration of flexibility)
            apply_watermark = clips[0].get('apply_watermark', True) if clips else True
            apply_logo = clips[0].get('apply_logo', True) if clips else True
            
            if apply_watermark or apply_logo:
                await self.apply_overlays(merged_path, overlay_path, apply_watermark, apply_logo)
                intermediate_files.add(overlay_path)
                merged_path = overlay_path
            # 3. Generate Subtitles for the ENTIRE merged video
            final_filename = f"compilation_{compilation_id}_{merge_id}.mp4"
            final_path = os.path.join(self.tmp_dir, final_filename)
            
            logger.info(f"Generating subtitles for the entire compilation: {compilation_id}")
            try:
                segments = await transcriber_service.transcribe(merged_path)
                logger.info(f"Transcribed {len(segments) if segments else 0} segments for merged video.")
                if segments:
                    ass_path = os.path.join(self.tmp_dir, f"sub_merged_{merge_id}.ass")
                    subtitle_service.generate_compilation_ass(segments, ass_path)
                    intermediate_files.add(ass_path)
                    
                    # Burn subtitles into the merged video
                    abs_ass_path = os.path.abspath(ass_path).replace(":", "\\:")
                    sub_cmd = [
                        "ffmpeg", "-y", "-i", merged_path,
                        "-vf", f"ass={abs_ass_path}",
                        "-c:v", "libx264", "-preset", "superfast", "-crf", "18",
                        "-c:a", "copy",
                        final_path
                    ]
                    logger.info(f"Burning final subtitles: {' '.join(sub_cmd)}")
                    result = await asyncio.to_thread(subprocess.run, sub_cmd, capture_output=True, text=True)
                    
                    if result.returncode == 0 and os.path.exists(final_path):
                        logger.info(f"Compilation with subtitles complete: {final_path}")
                        return final_filename
                    else:
                        logger.error(f"Failed to burn final subtitles: {result.stderr}")
                else:
                    logger.warning("No speech detected in merged video. Using merged video as final.")
            except Exception as e:
                logger.error(f"Subtitle processing error for compilation {compilation_id}: {e}")

            # Fallback: if subtitles fail, use the merged video as final
            if not os.path.exists(final_path):
                os.rename(merged_path, final_path)
            
            # 4. Upload to YouTube if requested
            if clips and clips[0].get('upload'):
                from app.services.youtube_upload import upload_short
                try:
                    metadata = {
                        "title": clips[0].get('yt_title', f"Compilation {compilation_id}"),
                        "description": clips[0].get('yt_description', ""),
                        "tags": clips[0].get('yt_tags', ""),
                        "privacy": "public"
                    }
                    logger.info(f"Uploading compilation {compilation_id} to YouTube...")
                    upload_result = await asyncio.to_thread(upload_short, final_path, metadata)
                    logger.info(f"YouTube Upload successful for {compilation_id}: {upload_result.get('upload_url')}")
                except Exception as e:
                    logger.error(f"YouTube Upload failed for {compilation_id}: {e}")

            return final_filename

        finally:
            for path in intermediate_files:
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except Exception as e:
                        logger.warning(f"Failed to cleanup intermediate file {path}: {e}")

compilation_processor = CompilationProcessor()