import asyncio
import re
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from app.main import APP_DIR, create_app
from tests.test_routes import asgi_request

# Use a real browser: plain JS objects do not reproduce SVG attribute reflection.
BROWSER = shutil.which("google-chrome") or shutil.which("chromium")
SETUP = """
const sampleAnalysis = {
  at: '2026-09-25T12:17:54Z', width: 640, height: 360, tile_size: 32,
  reason: 'motion', brightness_shift: 0, raw_changed_ratio: 0.053,
  camera_shift_x: 0, camera_shift_y: 0, camera_shift_support: 0,
  largest_tile_changed_ratio: 0.313, threshold: 12, min_changed_ratio: 0.1,
  consecutive_frames: 2, required_frames: 2,
  tiles: [{x: 320, y: 160, changed_ratio: 0.313, confirmed: true},
          {x: 352, y: 160, changed_ratio: 0.125, confirmed: false}],
};
const sampleStatus = {enabled: true, state: 'recording', stream_state: 'streaming',
  error: null, analysis: sampleAnalysis, last_recording_trigger: sampleAnalysis};
window.fetch = async (url) => ({ok: true,
  json: async () => url === '/api/motion' ? sampleStatus : []});
"""
CHECKS = """
window.addEventListener('load', async () => {
  const check = (condition, message) => { if (!condition) throw Error(message); };
  try {
    await loadMotionStatus();
    const panel = document.querySelector('#motion-diagnostics');
    const overlay = document.querySelector('#motion-overlay');
    const text = document.querySelector('#motion-analysis-status');
    check(getComputedStyle(overlay).display === 'none', 'closed panel must hide overlay');
    panel.open = true;
    panel.dispatchEvent(new Event('toggle'));
    check(text.textContent.includes('動きを検知'), 'analysis text must update');
    check(getComputedStyle(overlay).display !== 'none', 'open panel must show overlay');
    const rectangles = overlay.querySelectorAll('rect');
    check(rectangles.length === 2, 'both candidate and confirmed tiles must render');
    check(rectangles[0].getBoundingClientRect().width > 0, 'tile must have visible size');
    check(getComputedStyle(rectangles[0]).stroke === 'rgb(255, 64, 64)', 'confirmed red');
    check(getComputedStyle(rectangles[1]).stroke === 'rgb(255, 213, 79)', 'candidate yellow');
    const image = document.querySelector('#live-stream');
    const bounds = image.getBoundingClientRect();
    const scale = Math.min((bounds.width - 2) / 640, (bounds.height - 2) / 360);
    const expectedLeft = bounds.left + (bounds.width - 640 * scale) / 2 + 320 * scale;
    check(Math.abs(rectangles[0].getBoundingClientRect().left - expectedLeft) < 2,
          'overlay must align with letterboxed image');
    document.querySelector('#motion-analysis-source').value = 'trigger';
    document.querySelector('#motion-analysis-source').dispatchEvent(new Event('change'));
    check(overlay.querySelectorAll('rect').length === 2, 'recording trigger must render');
    panel.open = false;
    panel.dispatchEvent(new Event('toggle'));
    check(getComputedStyle(overlay).display === 'none', 'closing panel must hide overlay');
    panel.open = true;
    panel.dispatchEvent(new Event('toggle'));
    check(getComputedStyle(overlay).display !== 'none', 'reopening must show overlay');
    document.querySelector('#motion-analysis-source').value = 'current';
    renderMotionStatus({...sampleStatus, analysis: {...sampleAnalysis,
      reason: 'camera_motion', camera_shift_x: 1.5, camera_shift_y: -0.5,
      camera_shift_support: 0.75, tiles: []}});
    check(text.textContent.includes('カメラの揺れを補正'), 'camera motion reason must display');
    check(text.textContent.includes('横1.5px・縦-0.5px'), 'estimated displacement must display');
    check(overlay.querySelectorAll('rect').length === 0, 'camera-only motion must clear tiles');
    document.body.dataset.testResult = 'passed';
  } catch (error) {
    document.body.dataset.testResult = error.message;
  }
});
"""


@pytest.mark.skipif(BROWSER is None, reason="Chrome/Chromium is required for real SVG rendering")
@pytest.mark.parametrize("window_size", ["1400,1000", "390,844"])
@pytest.mark.asyncio
async def test_motion_overlay_is_visible_in_browser(
    settings, tmp_path: Path, window_size: str
) -> None:
    application = create_app(replace(
        settings, camera_backend="picamera2", video_dir=tmp_path / "videos"
    ))
    response = await asgi_request(application, "GET", "/")
    html = response.content.decode()
    css = (APP_DIR / "static/css/style.css").read_text()
    script = (APP_DIR / "static/js/app.js").read_text()
    html = re.sub(r'<link rel="stylesheet"[^>]+>', lambda _: f"<style>{css}</style>", html)
    html = re.sub(
        r'<script src="[^"]+" defer></script>',
        lambda _: f"<script>{SETUP}\n{script}\n{CHECKS}</script>", html,
    )
    html = html.replace('src="/stream.mjpg"',
                        'src="data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' '
                        'width=\'640\' height=\'360\'%3E%3C/svg%3E"')
    page = tmp_path / "overlay.html"
    page.write_text(html)
    result = await asyncio.to_thread(
        subprocess.run,
        [BROWSER, "--headless", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
         "--disable-background-networking", "--no-first-run", "--no-default-browser-check",
         f"--user-data-dir={tmp_path / 'browser'}", f"--window-size={window_size}",
         "--virtual-time-budget=1000", "--dump-dom", page.as_uri()],
        capture_output=True, text=True, timeout=30, check=True,
    )
    outcome = re.search(r'data-test-result="([^"]+)"', result.stdout)
    assert outcome is not None, result.stderr
    assert outcome.group(1) == "passed", outcome.group(1)
