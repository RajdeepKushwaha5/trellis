"""Encode an animated gallery of existing browser-check captures, without inventing UI states.
Development-only dependency: Pillow. Run from the project root after installing Pillow.
"""
from pathlib import Path
from PIL import Image

folder = Path(__file__).resolve().parent / 'screens'
names = ['tutor-feedback.png', 'tutor-lesson.png', 'tutor-graph-queries.png', 'tutor-field-notes.png']
frames = []
for name in names:
    with Image.open(folder / name) as source:
        # Keep the original screenshot, including its policy-mode labels, at a readable width.
        scale = 1000 / source.width
        image = source.convert('RGB').resize((1000, round(source.height * scale)), Image.Resampling.LANCZOS)
        frames.append(image)
height = max(frame.height for frame in frames)
canvases = []
for frame in frames:
    canvas = Image.new('RGB', (1000, height), '#f7f5eb')
    canvas.paste(frame, (0, 0))
    canvases.append(canvas.quantize(colors=192))
canvases[0].save(folder / 'tutor-walkthrough.gif', save_all=True, append_images=canvases[1:],
                 duration=[3500, 4500, 3500, 3500], loop=0, disposal=2, optimize=True)
print(folder / 'tutor-walkthrough.gif')
