"""Turn rendered slides into a 9:16 Reel: slow zoom per slide, crossfades, synthesized soundtrack."""
from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from .audio import soundtrack

W, H, FPS = 1080, 1920, 30
XFADE = 0.4  # seconds of dip-through-black between slides


def _ffmpeg() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def slide_durations(copy: dict) -> list[float]:
    """Cover 3s; other slides get time to read their words (3-6.5s)."""
    durs = [3.2]
    for sl in copy["slides"]:
        if sl.get("type") == "watch":
            durs.append(5.0)
            continue
        words = len((sl.get("title", "") + " " + sl.get("body", "") + " " + " ".join(sl.get("points") or [])).split())
        cap = 8.0 if sl.get("type") == "trivia" else 6.5   # two facts need a little longer to read
        durs.append(min(cap, max(3.2, 1.8 + words / 4.0)))
    return durs


def _canvas(slide: Image.Image) -> tuple[Image.Image, tuple[int, int]]:
    """9:16 background: the slide blown up, blurred and darkened. Returns bg and slide position."""
    bg = ImageOps.fit(slide, (W, H), Image.BILINEAR)
    bg = bg.filter(ImageFilter.GaussianBlur(40))
    bg = ImageEnhance.Brightness(bg).enhance(0.35)
    return bg, ((W - slide.width) // 2, (H - slide.height) // 2)


def build_reel(slide_paths: list[Path], copy: dict, out_path: Path, seed: int) -> Path:
    durs = slide_durations(copy)[: len(slide_paths)]
    total = sum(durs) - XFADE * (len(durs) - 1) + 0.8          # small tail on the last slide
    starts, t = [], 0.0
    for d in durs:
        starts.append(t)
        t += d - XFADE
    transitions = starts[1:]

    wav = soundtrack(total, transitions, seed, out_path.with_suffix(".wav"))

    slides = [Image.open(p).convert("RGB") for p in slide_paths]
    canvases = [_canvas(s) for s in slides]

    def frame_for(i: int, local: float) -> Image.Image:
        """Slide i at `local` seconds into its own display time, with a slow push-in."""
        s, (bg, (x, y)) = slides[i], canvases[i]
        span = durs[i] + 0.8
        z = 1.0 + 0.045 * min(1.0, max(0.0, local / span))
        w, h = int(s.width * z), int(s.height * z)
        fg = s.resize((w, h), Image.BILINEAR)
        im = bg.copy()
        im.paste(fg, (x - (w - s.width) // 2, y - (h - s.height) // 2))
        return im

    cmd = [_ffmpeg(), "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-i", str(wav),
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-profile:v", "high",
           "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
           "-shortest", "-movflags", "+faststart", str(out_path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    black = Image.new("RGB", (W, H), (6, 4, 5))
    nframes = int(total * FPS)
    for f in range(nframes):
        now = f / FPS
        i = max(k for k, st in enumerate(starts) if st <= now)
        im = frame_for(i, now - starts[i])
        # crossfade from the previous slide during the first XFADE seconds of this one
        if i > 0 and now - starts[i] < XFADE:
            a = (now - starts[i]) / XFADE
            if a < 0.5:   # previous slide fades to black...
                prev = frame_for(i - 1, now - starts[i - 1])
                im = Image.blend(prev, black, a * 2)
            else:         # ...then the new one fades up from black
                im = Image.blend(black, im, (a - 0.5) * 2)
        proc.stdin.write(im.tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg failed to encode the reel")
    print(f"[video] {total:.1f}s reel, {len(slides)} slides -> {out_path}")
    return out_path
