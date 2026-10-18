// Night-sky footer. Every dot is one of the 1,590 real curriculum concepts, grouped by subject, drawn as halftone
// clusters; a small original pixel droplet drifts over them. Decorative only: nothing here affects a learner's route.
const DROPLET = [
  '.....o.....',
  '....ooo....',
  '...ooooo...',
  '..ooooooo..',
  '.ooooooooo.',
  '.oowoooooo.',
  'oowoooooooo',
  'oookoookooo',
  'ooooooooooo',
  'ooookkkoooo',
  '.ooooooooo.',
  '..ooooooo..',
  '....ooo....',
];
const COLORS = {o: '#d07a52', w: '#f3ecdc', k: '#24352b'};

export function startNightSky(canvas, footer) {
  const ctx = canvas.getContext('2d');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  let dots = [], w = 0, h = 0, frame = 0, visible = true;

  function layout(nodes) {
    // One cluster per subject, spread across the band; cluster size follows the subject's concept count.
    const subjects = [...new Set(nodes.map(n => n.subject))];
    const golden = Math.PI * (3 - Math.sqrt(5));
    dots = [];
    subjects.forEach((subject, s) => {
      const group = nodes.filter(n => n.subject === subject);
      const cx = 0.08 + (s + 0.5) / subjects.length * 0.8, cy = s % 2 ? 0.4 : 0.66;
      const radius = 0.018 + Math.sqrt(group.length) * 0.0022;
      group.forEach((n, i) => {
        const r = Math.sqrt((i + 0.5) / group.length) * radius;
        dots.push({x: cx + Math.cos(i * golden) * r, y: cy + Math.sin(i * golden) * r * 2.6,
                   size: 0.55 + (1 - r / radius) * 1.25, phase: (i * 0.618) % (Math.PI * 2)});
      });
    });
    // A sparse field of loose stars between the clusters.
    for (let i = 0; i < 160; i++) dots.push({x: (i * 0.6180339) % 1, y: (i * 0.4142135) % 1, size: 0.5, phase: i, loose: true});
  }

  function resize() {
    const dpr = devicePixelRatio || 1;
    w = canvas.clientWidth; h = canvas.clientHeight;
    canvas.width = w * dpr; canvas.height = h * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function draw() {
    if (!visible || !w) return;
    frame++;
    ctx.clearRect(0, 0, w, h);
    for (const d of dots) {
      const twinkle = reduced ? 1 : 0.65 + 0.35 * Math.sin(frame / 60 + d.phase);
      ctx.globalAlpha = (d.loose ? 0.22 : 0.42) * twinkle;
      ctx.fillStyle = '#e9e1cf';
      const x = Math.round(d.x * w), y = Math.round(d.y * h);
      ctx.beginPath();ctx.arc(x, y, d.size, 0, Math.PI * 2);ctx.fill();
    }
    ctx.globalAlpha = 1;
    // The droplet drifts slowly across the middle and bobs.
    const px = 5, sw = DROPLET[0].length * px;
    const t = reduced ? 0 : frame / 900;
    const x = Math.round((0.5 + 0.18 * Math.sin(t)) * w - sw / 2);
    const y = Math.round(h * 0.42 + (reduced ? 0 : Math.sin(frame / 40) * 6));
    DROPLET.forEach((row, r) => [...row].forEach((c, col) => {
      if (c === '.') return;
      ctx.fillStyle = COLORS[c];
      ctx.fillRect(x + col * px, y + r * px, px, px);
    }));
    if (!reduced) requestAnimationFrame(draw);
  }

  new ResizeObserver(() => { resize(); if (reduced) draw(); }).observe(canvas);
  new IntersectionObserver(entries => {
    const was = visible; visible = entries[0].isIntersecting;
    if (visible && !was && !reduced) requestAnimationFrame(draw);
  }).observe(footer);
  fetch('/api/constellation').then(r => r.json()).then(d => { layout(d.nodes); resize(); requestAnimationFrame(draw); })
    .catch(() => { layout([]); resize(); requestAnimationFrame(draw); });
}
