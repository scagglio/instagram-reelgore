"""Render carousel slides with Pillow. 1080x1350, Reel Gore look: ink, blood red, bone."""
from __future__ import annotations

import io
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps


def hex2rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


class Renderer:
    def __init__(self, cfg: dict, fetch_image):
        s = cfg["slides"]
        self.W, self.H = s["width"], s["height"]
        p = s["palette"]
        self.blood, self.bone, self.ink, self.rust = (hex2rgb(p[k]) for k in ("blood", "bone", "ink", "rust"))
        heads = s["fonts"]["headline"]
        heads = [heads] if isinstance(heads, str) else heads
        self.head_path = next((h for h in heads if Path(h).exists()), heads[-1])
        self.condensed = "Bebas" in self.head_path
        self.body_path = s["fonts"]["body"]
        self.bold_path = s["fonts"].get("body_bold", self.body_path)
        self.handle = cfg["account"]["handle"]
        self.name = cfg["account"]["name"].upper()
        self.fetch = fetch_image  # callable(path) -> bytes | None
        self._cache: dict[str, Image.Image] = {}

    # ---------- fonts ----------
    def head(self, size):
        # Non-condensed fallback fonts are much wider than Bebas; scale them down.
        return ImageFont.truetype(self.head_path, size if self.condensed else int(size * 0.72))

    def body(self, size, bold=False):
        return ImageFont.truetype(self.bold_path if bold else self.body_path, size)

    # ---------- images ----------
    def img(self, path: str | None) -> Image.Image | None:
        if not path:
            return None
        if path not in self._cache:
            data = self.fetch(path)
            if not data:
                return None
            self._cache[path] = Image.open(io.BytesIO(data)).convert("RGB")
        return self._cache[path].copy()

    def background(self, path, darken=0.55, blur=0):
        im = self.img(path)
        if im is None:
            im = Image.new("RGB", (self.W, self.H), self.ink)
        im = ImageOps.fit(im, (self.W, self.H), Image.LANCZOS)
        if blur:
            im = im.filter(ImageFilter.GaussianBlur(blur))
        # duotone-ish tint toward ink/blood for a consistent grindhouse look
        gray = ImageOps.grayscale(im)
        tinted = ImageOps.colorize(gray, black=self.ink, white=self.bone, mid=tuple(int(c * .8) for c in self.blood))
        im = Image.blend(im, tinted, 0.45)
        im = Image.blend(im, Image.new("RGB", im.size, self.ink), darken * 0.5)
        return self._gradient(im)

    def _gradient(self, im, start=0.35):
        grad = Image.new("L", (1, self.H))
        for y in range(self.H):
            t = max(0, (y / self.H - start) / (1 - start))
            grad.putpixel((0, y), int(255 * min(1, t * 1.25)))
        grad = grad.resize((self.W, self.H))
        return Image.composite(Image.new("RGB", im.size, self.ink), im, grad)

    def grain(self, im, amount=14):
        rng = random.Random(42)
        noise = Image.effect_noise((self.W // 2, self.H // 2), amount).resize((self.W, self.H)).convert("RGB")
        return Image.blend(im, noise, 0.06)

    # ---------- text helpers ----------
    @staticmethod
    def wrap(draw, text, font, max_w):
        words, lines, line = text.split(), [], ""
        for w in words:
            test = f"{line} {w}".strip()
            if draw.textlength(test, font=font) <= max_w:
                line = test
            else:
                if line:
                    lines.append(line)
                line = w
        if line:
            lines.append(line)
        return lines

    def fit_headline(self, draw, text, max_w, max_lines, start=170, min_size=70):
        size = start
        while size > min_size:
            f = self.head(size)
            lines = self.wrap(draw, text.upper(), f, max_w)
            if len(lines) <= max_lines:
                return f, lines
            size -= 6
        f = self.head(min_size)
        return f, self.wrap(draw, text.upper(), f, max_w)

    def chrome(self, im, idx, total):
        d = ImageDraw.Draw(im)
        f = self.head(44)
        d.rectangle([60, 60, 60 + d.textlength(self.name, font=f) + 36, 118], fill=self.blood)
        d.text((78, 64), self.name, font=f, fill=self.bone)
        cnt = f"{idx}/{total}"
        fc = self.body(26, bold=True)
        d.text((self.W - 60 - d.textlength(cnt, font=fc), 76), cnt, font=fc, fill=self.bone)
        fh = self.body(24)
        d.text((60, self.H - 70), self.handle, font=fh, fill=(*self.bone,))
        if idx < total and getattr(self, "swipe", True):
            arrow = "SWIPE  →"
            d.text((self.W - 60 - d.textlength(arrow, font=fh), self.H - 70), arrow, font=fh, fill=self.bone)
        return im

    def kicker(self, d, x, y, text):
        f = self.body(28, bold=True)
        w = d.textlength(text.upper(), font=f)
        d.rectangle([x, y, x + w + 32, y + 50], fill=self.blood)
        d.text((x + 16, y + 8), text.upper(), font=f, fill=self.bone)
        return y + 50

    def paragraph(self, d, x, y, text, size=40, max_w=None, color=None, spacing=1.35):
        f = self.body(size)
        max_w = max_w or self.W - 2 * x
        for line in self.wrap(d, text, f, max_w):
            d.text((x, y), line, font=f, fill=color or self.bone)
            y += int(size * spacing)
        return y

    def skull(self, d, cx, cy, r, filled=True):
        col = self.blood if filled else (70, 60, 60)
        d.ellipse([cx - r, cy - r, cx + r, cy + int(r * .8)], fill=col)
        d.rounded_rectangle([cx - r * .55, cy + r * .4, cx + r * .55, cy + r * 1.15], radius=int(r * .15), fill=col)
        eye = r * .3
        for ex in (cx - r * .4, cx + r * .4):
            d.ellipse([ex - eye, cy - eye * .6, ex + eye, cy + eye * 1.2], fill=self.ink)
        d.polygon([(cx, cy + r * .35), (cx - r * .12, cy + r * .6), (cx + r * .12, cy + r * .6)], fill=self.ink)
        for tx in (-.3, 0, .3):
            d.line([cx + r * tx, cy + r * .85, cx + r * tx, cy + r * 1.15], fill=self.ink, width=max(2, int(r * .07)))

    # ---------- slide types ----------
    def cover(self, movie, headline, subhead, total):
        bg = movie["backdrops"][0] if movie["backdrops"] else movie["poster"]
        im = self.background(bg, darken=0.35)
        d = ImageDraw.Draw(im)
        f, lines = self.fit_headline(d, headline, self.W - 120, 4)
        lh = int(f.size * 0.95)
        y = self.H - 200 - lh * len(lines) - 90
        for i, line in enumerate(lines):
            d.text((60, y), line, font=f, fill=self.blood if i == len(lines) - 1 else self.bone)
            y += lh
        self.paragraph(d, 60, y + 30, subhead, size=38)
        return self.grain(self.chrome(im, 1, total))

    def movie_slide(self, movie, sl, idx, total):
        im = self.background(movie["backdrops"][0] if movie["backdrops"] else movie["poster"], darken=0.8, blur=18)
        d = ImageDraw.Draw(im)
        poster = self.img(movie["poster"])
        y = 160
        if poster:
            ph = 640
            pw = int(poster.width * ph / poster.height)
            poster = poster.resize((pw, ph), Image.LANCZOS)
            shadow = Image.new("RGBA", (pw + 60, ph + 60), (0, 0, 0, 0))
            ImageDraw.Draw(shadow).rectangle([30, 30, pw + 30, ph + 30], fill=(0, 0, 0, 200))
            shadow = shadow.filter(ImageFilter.GaussianBlur(18))
            px = (self.W - pw) // 2
            im.paste(shadow, (px - 30, y - 10), shadow)
            im.paste(poster, (px, y))
            d.rectangle([px - 4, y - 4, px + pw + 4, y + ph + 4], outline=self.blood, width=4)
            im.paste(poster, (px, y))
            y += ph + 40
        y = self.kicker(d, 60, y, sl.get("kicker", "")) + 20
        f, lines = self.fit_headline(d, sl.get("title", movie["title"]), self.W - 120, 2, start=96, min_size=60)
        for line in lines:
            d.text((60, y), line, font=f, fill=self.bone)
            y += int(f.size * .95)
        self.paragraph(d, 60, y + 22, sl.get("body", ""), size=32)
        return self.grain(self.chrome(im, idx, total))

    def text_slide(self, movie, sl, idx, total):
        bds = movie["backdrops"] or [movie["poster"]]
        im = self.background(bds[idx % len(bds)], darken=0.45)
        d = ImageDraw.Draw(im)
        y = int(self.H * 0.50)
        y = self.kicker(d, 60, y, sl.get("kicker", "")) + 24
        f, lines = self.fit_headline(d, sl.get("title", ""), self.W - 120, 2, start=110, min_size=64)
        for line in lines:
            d.text((60, y), line, font=f, fill=self.bone)
            y += int(f.size * .95)
        self.paragraph(d, 60, y + 26, sl.get("body", ""), size=38)
        return self.grain(self.chrome(im, idx, total))

    def verdict_slide(self, movie, sl, idx, total):
        im = self.background(movie["poster"] or (movie["backdrops"] or [None])[0], darken=0.9, blur=24)
        d = ImageDraw.Draw(im)
        y = 260
        y = self.kicker(d, 60, y, sl.get("kicker") or "THE VERDICT") + 40
        f, lines = self.fit_headline(d, sl.get("title") or movie["title"], self.W - 120, 2, start=120)
        for line in lines:
            d.text((60, y), line, font=f, fill=self.bone)
            y += int(f.size * .95)
        y += 60
        r = 70
        n = sl.get("skulls", 0) or 0
        x0 = (self.W - (5 * r * 2 + 4 * 40)) // 2 + r
        for i in range(5):
            self.skull(d, x0 + i * (2 * r + 40), y + r, r, filled=i < n)
        y += 2 * r + 120
        self.paragraph(d, 60, y, sl.get("body", ""), size=40)
        return self.grain(self.chrome(im, idx, total))

    def cta_slide(self, movie, sl, idx, total):
        im = Image.new("RGB", (self.W, self.H), self.ink)
        d = ImageDraw.Draw(im)
        # blood drip bar
        d.rectangle([0, 0, self.W, 140], fill=self.blood)
        rng = random.Random(idx)
        x = 0
        while x < self.W:
            w = rng.randint(30, 70)
            h = rng.randint(20, 160)
            d.rounded_rectangle([x, 120, x + w, 140 + h], radius=w // 2, fill=self.blood)
            x += w + rng.randint(10, 60)
        y = 420
        f, lines = self.fit_headline(d, sl.get("title") or "YOUR TURN", self.W - 120, 3, start=150)
        for line in lines:
            d.text((60, y), line, font=f, fill=self.bone)
            y += int(f.size * .95)
        y = self.paragraph(d, 60, y + 20, sl.get("body", ""), size=42) + 60
        fh = self.head(64)
        d.text((60, y), f"FOLLOW {self.handle.upper()}", font=fh, fill=self.blood)
        self.skull(d, self.W - 160, self.H - 260, 70)
        return self.grain(self.chrome(im, idx, total))

    def render_all(self, plan: dict, copy: dict, out_dir: Path, swipe: bool = True) -> list[Path]:
        self.swipe = swipe
        out_dir.mkdir(parents=True, exist_ok=True)
        slides = copy["slides"]
        total = len(slides) + 1
        lead = plan["movies"][0]
        images = [self.cover(lead, copy["headline"], copy.get("subhead", ""), total)]
        fn = {"movie": self.movie_slide, "text": self.text_slide, "verdict": self.verdict_slide, "cta": self.cta_slide}
        for i, sl in enumerate(slides, start=2):
            m = plan["movies"][sl["movie_index"]]
            images.append(fn.get(sl.get("type"), self.text_slide)(m, sl, i, total))
        paths = []
        for i, im in enumerate(images, start=1):
            p = out_dir / f"slide_{i:02d}.jpg"
            im.save(p, "JPEG", quality=92, optimize=True)
            paths.append(p)
        return paths
