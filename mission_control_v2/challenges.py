"""Challenge definitions for Mission Control."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Difficulty(Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


@dataclass
class Target:
    entity_id: str
    target_state: str


@dataclass
class PreSetup:
    domain: str
    service: str
    entity_id: str


@dataclass
class Challenge:
    name: str
    announcement: str
    hint: str
    success_message: str  # {time} placeholder
    targets: list[Target]
    difficulty: Difficulty
    success_speaker: str
    room: str
    pre_setup: list[PreSetup] = field(default_factory=list)
    multi_target: bool = False
    funny_announcements: list[str] = field(default_factory=list)
    floor: str = ""

