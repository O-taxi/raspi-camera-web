from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class MotionTuning:
    minimum_record_seconds: int
    record_seconds: int
    maximum_record_seconds: int
    cooldown_seconds: int
    threshold: float

    def validate(self) -> None:
        if not 1 <= self.minimum_record_seconds <= 3600:
            raise ValueError("minimum_record_seconds must be between 1 and 3600")
        if not 1 <= self.record_seconds <= 3600:
            raise ValueError("record_seconds must be between 1 and 3600")
        if not 1 <= self.maximum_record_seconds <= 3600:
            raise ValueError("maximum_record_seconds must be between 1 and 3600")
        if not self.minimum_record_seconds <= self.record_seconds:
            raise ValueError("minimum_record_seconds must not exceed record_seconds")
        if not self.record_seconds <= self.maximum_record_seconds:
            raise ValueError("record_seconds must not exceed maximum_record_seconds")
        if not 1 <= self.cooldown_seconds <= 3600:
            raise ValueError("cooldown_seconds must be between 1 and 3600")
        if not 0 < self.threshold <= 255:
            raise ValueError("threshold must be greater than 0 and at most 255")

    def as_dict(self) -> dict[str, int | float]:
        return asdict(self)


class MotionTuningStore:
    def __init__(self, path: Path, defaults: MotionTuning) -> None:
        self.path = path
        self.defaults = defaults

    def load(self) -> MotionTuning:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Motion settings must be a JSON object")
            values = {
                "minimum_record_seconds": payload.get("minimum_record_seconds"),
                "record_seconds": payload.get("record_seconds"),
                "maximum_record_seconds": payload.get("maximum_record_seconds"),
                "cooldown_seconds": payload.get("cooldown_seconds"),
                "threshold": payload.get("threshold"),
            }
            if any(type(values[key]) is not int for key in (
                "minimum_record_seconds",
                "record_seconds",
                "maximum_record_seconds",
                "cooldown_seconds",
            )):
                raise ValueError("Motion recording times must be integers")
            if type(values["threshold"]) not in (int, float):
                raise ValueError("Motion threshold must be numeric")
            tuning = MotionTuning(**values)
            tuning.validate()
            return tuning
        except FileNotFoundError:
            return self.defaults
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            LOGGER.warning("Unable to read motion settings; using environment defaults: %s", exc)
            return self.defaults

    def save(self, tuning: MotionTuning) -> None:
        tuning.validate()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        try:
            temporary_path.write_text(
                json.dumps(tuning.as_dict(), ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            temporary_path.replace(self.path)
        finally:
            temporary_path.unlink(missing_ok=True)
