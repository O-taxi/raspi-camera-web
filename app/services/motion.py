"""Bounded, dependency-free translation estimation for low-resolution luma frames."""

from __future__ import annotations

from dataclasses import dataclass
from math import floor

MAX_CAMERA_SHIFT = 3


def smooth_luma(frame: bytes, index: int, width: int) -> int:
    """Average a 2x2 patch; callers keep the patch within the image."""
    return (frame[index] + frame[index + 1]
            + frame[index + width] + frame[index + width + 1]) // 4


@dataclass(frozen=True)
class FrameShift:
    # Positive values mean that image content moved right/down in the current frame.
    x: float = 0.0
    y: float = 0.0
    support: float = 0.0


class ShiftedLuma:
    """A 2x2 box average with optional half-pixel translation of the reference."""

    def __init__(self, width: int, shift_x: float, shift_y: float) -> None:
        self.width = width
        self.left = floor(-shift_x)
        self.top = floor(-shift_y)
        self.half_x = -shift_x != self.left
        self.half_y = -shift_y != self.top
        self.right = self.left + 1 + self.half_x
        self.bottom = self.top + 1 + self.half_y
        self.offset = self.top * width + self.left

    def sample(self, frame: bytes, index: int) -> int:
        index += self.offset
        width = self.width
        if not self.half_x and not self.half_y:
            return smooth_luma(frame, index, width)
        if self.half_x and not self.half_y:
            return (frame[index] + 2 * frame[index + 1] + frame[index + 2]
                    + frame[index + width] + 2 * frame[index + width + 1]
                    + frame[index + width + 2]) // 8
        if self.half_y and not self.half_x:
            return (frame[index] + frame[index + 1]
                    + 2 * frame[index + width] + 2 * frame[index + width + 1]
                    + frame[index + 2 * width] + frame[index + 2 * width + 1]) // 8
        return (frame[index] + 2 * frame[index + 1] + frame[index + 2]
                + 2 * frame[index + width] + 4 * frame[index + width + 1]
                + 2 * frame[index + width + 2] + frame[index + 2 * width]
                + 2 * frame[index + 2 * width + 1] + frame[index + 2 * width + 2]) // 16


def estimate_frame_shift(current: bytes, previous: bytes, width: int) -> FrameShift:
    """Search at most 96 probes, 49 integer offsets and 8 half-pixel refinements.

    A local object cannot justify alignment: improvement must span at least six
    of the twelve image regions. Poor matches leave detection unchanged.
    """
    height = len(current) // width
    margin = MAX_CAMERA_SHIFT + 2
    if width < 32 or height < 24:
        return FrameShift()
    probes = []
    initial_differences = []
    for row in range(8):
        y = margin + (2 * row + 1) * (height - 2 * margin) // 16
        for column in range(12):
            x = margin + (2 * column + 1) * (width - 2 * margin) // 24
            index = y * width + x
            value = smooth_luma(current, index, width)
            reference = smooth_luma(previous, index, width)
            region = (y * 3 // height) * 4 + x * 4 // width
            probes.append((index, value, reference, region))
            initial_differences.append(value - reference)
    brightness = sorted(initial_differences)[len(probes) // 2]
    baseline = sum(min(abs(difference - brightness), 32) for difference in initial_differences)
    if baseline < len(probes) * 2:
        return FrameShift()

    def score(dx: float, dy: float) -> int:
        sampler = ShiftedLuma(width, dx, dy)
        return sum(
            min(abs(value - sampler.sample(previous, index) - brightness), 32)
            for index, value, _, _ in probes
        )

    best_x, best_y, best_score = 0.0, 0.0, baseline
    for dy in range(-MAX_CAMERA_SHIFT, MAX_CAMERA_SHIFT + 1):
        for dx in range(-MAX_CAMERA_SHIFT, MAX_CAMERA_SHIFT + 1):
            if dx == 0 and dy == 0:
                continue
            candidate_score = score(dx, dy)
            if candidate_score < best_score or (
                candidate_score == best_score and dx * dx + dy * dy < best_x**2 + best_y**2
            ):
                best_x, best_y, best_score = float(dx), float(dy), candidate_score
    integer_x, integer_y = best_x, best_y
    for dy in (-0.5, 0.0, 0.5):
        for dx in (-0.5, 0.0, 0.5):
            if dx == 0 and dy == 0:
                continue
            x, y = integer_x + dx, integer_y + dy
            if abs(x) > MAX_CAMERA_SHIFT or abs(y) > MAX_CAMERA_SHIFT:
                continue
            candidate_score = score(x, y)
            if candidate_score < best_score or (
                candidate_score == best_score and x * x + y * y < best_x**2 + best_y**2
            ):
                best_x, best_y, best_score = x, y, candidate_score
    # Require a substantial, distributed improvement over the stationary model.
    if (best_x == 0 and best_y == 0) or best_score > baseline * 0.7:
        return FrameShift()
    before = [0] * 12
    after = [0] * 12
    counts = [0] * 12
    sampler = ShiftedLuma(width, best_x, best_y)
    for index, value, reference, region in probes:
        before[region] += min(abs(value - reference - brightness), 32)
        after[region] += min(abs(value - sampler.sample(previous, index) - brightness), 32)
        counts[region] += 1
    supported = sum(
        counts[region] > 0
        and before[region] - after[region] >= counts[region]
        and after[region] <= before[region] * 0.75
        for region in range(12)
    )
    if supported < 6:
        return FrameShift()
    return FrameShift(best_x, best_y, supported / 12)
