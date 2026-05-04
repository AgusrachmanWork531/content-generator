import os
import logging

logger = logging.getLogger(__name__)

class SubtitleService:
    def __init__(self):
        # Default settings for Vertical Clip Generator
        self.font_family = "Inter Black" 
        self.font_size = 55
        self.margin_v = 480 
        self.primary_color = "&H00FFFFFF&" # Putih
        self.stroke_color = "&H00000000&" # Hitam
        self.stroke_width = 4 
        self.shadow = 3 
        self.highlight_color = "&H000AD6FF&" # Kuning/Emas

    async def process_subtitles(self, input_path: str, output_path: str):
        """
        High-level entry point: Transcribe -> Generate ASS -> Burn with FFmpeg.
        Shared by both clipper and compilation if needed.
        """
        from app.services.transcriber import transcriber_service
        import asyncio
        import subprocess

        logger.info(f"Processing subtitles for: {input_path}")
        segments = await transcriber_service.transcribe(input_path)
        if not segments:
            logger.warning("No speech detected. Copying input to output.")
            import shutil
            shutil.copy(input_path, output_path)
            return

        ass_path = input_path.replace(".mp4", ".ass")
        # For compilation, we assume landscape (1920x1080)
        # 25% from bottom for 1080p is ~270px
        self.generate_compilation_ass(segments, ass_path)

        # Burn subtitles
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-vf", f"ass={ass_path}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "copy",
            output_path
        ]
        
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        await proc.communicate()
        if os.path.exists(ass_path): os.remove(ass_path)

    def generate_ass(self, segments: list, output_path: str, start_time: float = 0, end_time: float = 0):
        """Standard method for Vertical Clips. Supports filtering and both formats."""
        header = self._get_ass_header(self.font_family, self.font_size, self.margin_v)
        all_words = []
        
        for seg in segments:
            s_start = seg.get('start', 0)
            # Filter: Only process segments within the crop range (with 2s padding)
            if end_time > 0:
                if s_start < (start_time - 2) or s_start > (end_time + 2):
                    continue

            # 1. Handle Whisper-style word-level timestamps
            if 'words' in seg:
                all_words.extend(seg['words'])
            # 2. Handle YouTube-style segment-level timestamps
            elif 'text' in seg and 'start' in seg:
                # Mock a 'words' list from the sentence to reuse the high-end renderer
                sentence_text = seg['text']
                words_in_sentence = sentence_text.split()
                if not words_in_sentence: continue
                
                # Distribute segment duration across words evenly
                duration = seg.get('duration', 1.5)
                time_per_word = duration / len(words_in_sentence)
                
                # Normalize time to start from 0 for the cropped video
                for i, w in enumerate(words_in_sentence):
                    w_start = s_start + (i * time_per_word) - start_time
                    w_end = w_start + time_per_word
                    all_words.append({
                        'word': w,
                        'start': w_start,
                        'end': w_end
                    })
        
        if not all_words:
            return

        dialogue_lines = self._refine_pro(all_words)
        self._write_ass(output_path, header, dialogue_lines)

    def generate_compilation_ass(self, segments: list, output_path: str):
        """Specialized method for Landscape Compilations."""
        # Adjusted size to 36 and MarginV to 270 (25% from bottom) for smaller subtitles.
        header = self._get_ass_header("Inter Black", 36, 270, is_landscape=True)
        all_words = []
        for seg in segments:
            if 'words' in seg:
                all_words.extend(seg['words'])
        
        if not all_words:
            return

        dialogue_lines = self._refine_pro(all_words)
        self._write_ass(output_path, header, dialogue_lines)

    def _refine_pro(self, words: list) -> list:
        # 1. Semantic Chunking (Max 6-8 words, pause > 400ms, emphasis/punctuation)
        chunks = []
        current_chunk = []
        
        for word in words:
            word_text = word['word'].strip()
            
            # Check for splitting conditions if we already have words
            if current_chunk:
                pause_duration = word['start'] - current_chunk[-1]['end']
                
                has_long_pause = pause_duration > 0.4
                has_punctuation = any(char in current_chunk[-1]['word'] for char in ['.', '!', '?'])
                max_words_reached = len(current_chunk) >= 5
                
                if has_long_pause or has_punctuation or max_words_reached:
                    chunks.append(current_chunk)
                    current_chunk = []
                    
            current_chunk.append(word)
        if current_chunk: chunks.append(current_chunk)
            
        # 2. Boundary Calculation: Precision Timing & Constraints
        dialogue_lines = []
        segments = []
        
        for i, phrase in enumerate(chunks):
            # Timing precision: start = first word - 80ms, end = last word + 120ms
            target_start = phrase[0]['start'] - 0.08
            target_end = phrase[-1]['end'] + 0.12
            
            # Anti-Overlap / Strict Bound Enforcement
            if i > 0:
                prev_end = segments[i-1]['end']
                if target_start < prev_end:
                    target_start = prev_end + 0.01
            
            # Duration limits: Min 800ms, Max 4000ms
            duration = target_end - target_start
            if duration < 0.8:
                target_end = target_start + 0.8
            elif duration > 4.0:
                target_end = target_start + 4.0
                
            # Prevent overlap with the *next* segment
            if i < len(chunks) - 1:
                next_raw_start = chunks[i+1][0]['start'] - 0.08
                if target_end > next_raw_start:
                    target_end = next_raw_start - 0.01

            segments.append({
                'phrase': phrase,
                'start': target_start,
                'end': target_end,
                'layer': i % 2 
            })

        for seg in segments:
            dialogue_lines.append(self._format_phrase_line(
                seg['phrase'], 
                seg['start'], 
                seg['end'], 
                seg['layer']
            ))
        return dialogue_lines

    def _format_phrase_line(self, phrase: list, start_val: float, end_val: float, layer: int) -> str:
        # Strict rounding
        start_val = round(start_val, 2)
        end_val = round(end_val, 2)
        start_time = self._format_timestamp(start_val)
        end_time = self._format_timestamp(end_val)
        
        is_hook = start_val < 4.0
        fsc_base = 105 if is_hook else 100
        fsc_pop = 135 if is_hook else 115
        c_base = "&H00FFFFFF&" 
        c_gold = "&H0000FFFF&"  # Vibrant Gold
        c_blue = "&H00FFCC00&"  # Cyan-Blue
        
        full_text = ""
        anchor_time = start_val
        mid_point = len(phrase) // 2 if len(phrase) > 3 else -1
        
        for i, word in enumerate(phrase):
            w_text = word['word'].strip().upper()
            t_start = int(max(0, (word['start'] - anchor_time) * 1000))
            t_end = int(max(t_start + 100, (word['end'] - anchor_time) * 1000))

            clean_w = "".join(filter(str.isalnum, w_text))
            is_keyword = len(clean_w) >= 5 or is_hook or clean_w.isupper()
            w_pop_color = c_gold if is_keyword else c_blue

            tag = (f"{{\\c{c_base}\\fscx{fsc_base}\\fscy{fsc_base}"
                   f"\\t({t_start},{t_start+60},\\c{w_pop_color}\\fscx{fsc_pop}\\fscy{fsc_pop})"
                   f"\\t({t_end},{t_end+60},\\c{c_base}\\fscx{fsc_base}\\fscy{fsc_base})}}")
            
            if i == mid_point and mid_point > 0:
                full_text += f"{tag}{w_text}\\N"
            else:
                full_text += f"{tag}{w_text} "

        clean_full_text = full_text.strip().replace(' \\N', '\\N')
        cinematic_text = f"{{\\fad(100,50)}}{clean_full_text}"
        return f"Dialogue: {layer},{start_time},{end_time},Default,,0,0,0,,{cinematic_text}"

    def _format_timestamp(self, seconds: float) -> str:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds - int(seconds)) * 100)
        return f"{hours:02}:{minutes:02}:{secs:02}.{millis:02}"

    def _write_ass(self, output_path: str, header: str, lines: list):
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(header)
            f.write("\n".join(lines))
            f.write("\n")

    def _get_ass_header(self, font: str, size: int, margin: int, is_landscape: bool = False) -> str:
        res_x = 1920 if is_landscape else 1080
        res_y = 1080 if is_landscape else 1920
        return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {res_x}
PlayResY: {res_y}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{size},{self.primary_color},&H00000000,{self.stroke_color},&H80000000,1,0,0,0,100,100,0,0,1,2,2,2,50,50,{margin},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

subtitle_service = SubtitleService()