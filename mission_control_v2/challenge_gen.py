"""LLM-powered challenge generator for Mission Control via OpenRouter."""
import json
import logging

import aiohttp

logger = logging.getLogger("mission_control.challenge_gen")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "anthropic/claude-sonnet-4"

CHALLENGE_PROMPT = """You are generating smart home challenges for a kids' game called Mission Control.

Given these Home Assistant entities and speakers, create fun challenges that kids can complete by physically interacting with devices in the house.

ENTITIES:
{entities_json}

SPEAKERS:
{speakers_json}

HUB_SPEAKER: {hub_speaker}

Generate challenges as a JSON array. Each challenge must have:
- name: short descriptive name (e.g. "Kitchen Island Lights")
- announcement: what to tell the kids (spoken aloud via TTS, 1-2 sentences)
- hint: a helpful hint given after 30 seconds if they haven't completed it
- success_message: celebration message (use {{time}} placeholder for completion time, e.g. "Done in {{time}} seconds!")
- targets: array of objects with "entity_id" and "target_state" — what must change to complete
- difficulty: "easy" (same floor as hub/simple), "medium" (different floor or outside), "hard" (multi-target or tricky)
- room: which room/area this challenge is in
- success_speaker: the speaker closest to the challenge's room/area
- pre_setup: array of objects with "domain", "service", "entity_id" — for lights/switches/fans, set them to the opposite state before the challenge starts. For sensors/doors/motion, use empty array []
- multi_target: true if targets has more than one item, false otherwise
- funny_announcements: array of 2 humorous alternative announcements that say the same thing but funnier (keep them short, 1-2 sentences max)

RULES:
- Only use entity_ids from the provided ENTITIES list
- Only use speaker entity_ids from the provided SPEAKERS list
- For "turn on" challenges, pre_setup should turn the entity off first: {{"domain": "<domain>", "service": "turn_off", "entity_id": "<entity_id>"}}
- For "turn off" challenges, pre_setup should turn the entity on first: {{"domain": "<domain>", "service": "turn_on", "entity_id": "<entity_id>"}}
- The domain in pre_setup should match the entity's domain (light, switch, fan, etc.)
- For binary_sensors (doors, motion, occupancy), no pre_setup needed — use empty array []
- binary_sensors with "motion" or "occupancy" in the name → target_state should be "on"
- Door/window contact sensors → target_state "on" means open, "off" means closed
- Create a mix of difficulties: ~40% easy, ~35% medium, ~25% hard
- Hard challenges should combine 2 targets from the same area or nearby areas
- Make announcements fun, playful, and kid-friendly
- Assign success_speaker to the speaker in or closest to the challenge's area
- If no speaker is near the challenge area, use the hub_speaker
- Generate 15-20 challenges covering a good variety of entities and rooms
- Keep all text fields concise to stay within output limits
{existing_section}
Return ONLY a valid JSON array, no markdown fences, no explanation. Ensure the JSON is complete and properly closed."""


class ChallengeGenerator:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        self.api_key = api_key
        self.model = model

    async def _call_llm(self, messages: list[dict], max_tokens: int = 16384) -> tuple[str, str]:
        """Call OpenRouter API. Returns (text, finish_reason)."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/dcnoren/mission-control",
            "X-Title": "Mission Control",
        }
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": messages,
        }

        timeout = aiohttp.ClientTimeout(total=120)
        async with aiohttp.ClientSession() as session:
            async with session.post(OPENROUTER_URL, headers=headers, json=payload,
                                    timeout=timeout) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error(f"OpenRouter API error {resp.status}: {body[:300]}")
                    raise RuntimeError(f"OpenRouter API error {resp.status}: {body[:200]}")

                data = await resp.json()
                choice = data["choices"][0]
                text = choice["message"]["content"].strip()
                finish_reason = choice.get("finish_reason", "stop")
                model_used = data.get("model", self.model)
                logger.info(f"OpenRouter response via {model_used}: {len(text)} chars, finish_reason={finish_reason}")
                return text, finish_reason

    @staticmethod
    def _parse_json_response(text: str, finish_reason: str) -> any:
        """Parse JSON from LLM response, handling truncation and markdown fencing."""
        if finish_reason == "length":
            logger.warning("Response was truncated (hit max_tokens)")
            text = ChallengeGenerator._salvage_truncated_json(text)

        # Strip markdown fencing
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[: text.rfind("```")]
            text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            logger.error(f"Response tail: ...{text[-300:]}")
            raise ValueError(f"LLM returned invalid JSON: {e}")

    async def suggest(
        self,
        entities: list[dict],
        speakers: list[dict],
        hub_speaker: str,
        user_prompt: str = "",
        floors: list[dict] | None = None,
        existing_challenges: list[dict] | None = None,
    ) -> list[dict]:
        """Send entities to LLM, return suggested challenges."""
        # Build existing challenges section
        if existing_challenges:
            existing_lines = json.dumps(existing_challenges, indent=2)
            existing_section = (
                f"EXISTING CHALLENGES (already in the database):\n{existing_lines}\n\n"
                "IMPORTANT: Do NOT generate challenges that duplicate an existing one "
                "(same entity with the same target state, e.g. turning on the same light). "
                "You MAY combine an already-used entity with other entities to create new multi-target challenges "
                "(e.g. if 'Kitchen Pendant' on exists, you could create 'Kitchen Blackout' that turns off pendant AND island lights together). "
                "Focus on entities and combinations not yet covered.\n"
            )
        else:
            existing_section = ""

        # Compact entities for LLM: remove redundant fields, use minimal JSON
        compact_entities = []
        for e in entities:
            ce = {"id": e["entity_id"], "name": e.get("friendly_name", ""), "area": e.get("area", "")}
            # Include state only for binary_sensors (door open/closed matters for challenge design)
            if e.get("domain") == "binary_sensor":
                ce["state"] = e.get("state", "")
            compact_entities.append(ce)

        compact_speakers = [
            {"id": s["entity_id"], "name": s.get("friendly_name", ""), "area": s.get("area", "")}
            for s in speakers
        ]

        prompt = CHALLENGE_PROMPT.format(
            entities_json=json.dumps(compact_entities),
            speakers_json=json.dumps(compact_speakers),
            hub_speaker=hub_speaker,
            existing_section=existing_section,
        )

        # Insert floor information before the "Return ONLY" line
        return_line = "Return ONLY a valid JSON array"
        floor_section = ""
        if floors:
            floor_lines = "\n".join(
                f"- {f['name']}: areas [{', '.join(f.get('areas', []))}]"
                for f in floors
            )
            floor_section = (
                f"FLOORS:\n{floor_lines}\n\n"
                "Each challenge must include a \"floor\" field matching one of the floor names above, "
                "based on which floor the challenge's room/area belongs to.\n\n"
            )
        else:
            floor_section = (
                "Each challenge must include a \"floor\" field set to \"\" (empty string) "
                "since no floors are configured.\n\n"
            )

        parts = prompt.rsplit(return_line, 1)
        prompt = parts[0] + floor_section

        if user_prompt.strip():
            prompt += f"USER INSTRUCTIONS:\n{user_prompt.strip()}\n\n"

        prompt += return_line + parts[1]

        logger.info(
            f"Requesting challenge suggestions for {len(entities)} entities, "
            f"{len(speakers)} speakers via {self.model}"
        )

        text, finish_reason = await self._call_llm(
            [{"role": "user", "content": prompt}],
            max_tokens=16384,
        )

        suggestions = self._parse_json_response(text, finish_reason)

        if not isinstance(suggestions, list):
            raise ValueError("LLM response is not a JSON array")

        logger.info(f"Got {len(suggestions)} challenge suggestions")
        return suggestions

    async def rethink(
        self,
        challenge: dict,
        feedback: str,
        entities: list[dict],
        speakers: list[dict],
        hub_speaker: str,
    ) -> dict:
        """Re-think a single challenge based on user feedback."""
        prompt = f"""You previously generated this smart home challenge for a kids' game:

{json.dumps(challenge, indent=2)}

The user wants you to revise it with this feedback:
"{feedback}"

Available entities: {json.dumps(entities, indent=2)}
Available speakers: {json.dumps(speakers, indent=2)}
Hub speaker: {hub_speaker}

Return ONLY a single valid JSON object (not an array) with the revised challenge. Keep the same schema:
name, announcement, hint, success_message (with {{time}} placeholder), targets (array of {{entity_id, target_state}}), difficulty (easy/medium/hard), room, success_speaker, pre_setup (array of {{domain, service, entity_id}} — empty for sensors/doors), multi_target (bool), funny_announcements (array of 2 short alternatives).

Only use entity_ids from the provided entities list. No markdown fences."""

        logger.info(f"Re-thinking challenge '{challenge.get('name')}' with feedback: {feedback}")

        text, finish_reason = await self._call_llm(
            [{"role": "user", "content": prompt}],
            max_tokens=2048,
        )

        revised = self._parse_json_response(text, finish_reason)

        if isinstance(revised, list):
            revised = revised[0] if revised else {}

        logger.info(f"Re-thought challenge: '{revised.get('name')}'")
        return revised

    async def regenerate_field(self, challenge: dict, field: str) -> str | list[str]:
        """Regenerate a single text field of a challenge."""
        field_instructions = {
            "announcement": "Write a new announcement for this challenge. This is spoken aloud to kids via TTS. Keep it 1-2 sentences, fun, playful, and clear about what they need to do. Return ONLY the announcement text, no quotes or JSON.",
            "hint": "Write a new hint for this challenge. This is spoken after 30 seconds if kids haven't completed it yet. Keep it short, helpful, and encouraging. Return ONLY the hint text, no quotes or JSON.",
            "success_message": "Write a new success/celebration message for this challenge. Use {time} as a placeholder for completion time. Keep it 1 sentence, excited and celebratory. Return ONLY the message text, no quotes or JSON.",
            "funny_announcements": 'Write 2 funny alternative announcements for this challenge. Same info as the original but humorous. Keep each 1-2 sentences. Return ONLY a JSON array of 2 strings, e.g. ["first funny version", "second funny version"].',
        }

        if field not in field_instructions:
            raise ValueError(f"Cannot regenerate field: {field}")

        prompt = f"""Challenge: {challenge.get('name', '')}
Room: {challenge.get('room', '')}
Original announcement: {challenge.get('announcement', '')}
Targets: {json.dumps(challenge.get('targets', []))}

{field_instructions[field]}"""

        logger.info(f"Regenerating '{field}' for challenge '{challenge.get('name')}'")

        text, finish_reason = await self._call_llm(
            [{"role": "user", "content": prompt}],
            max_tokens=512,
        )

        text = text.strip().strip('"')

        if field == "funny_announcements":
            return self._parse_json_response(text, finish_reason)

        return text

    @staticmethod
    def _salvage_truncated_json(text: str) -> str:
        """Try to recover valid JSON from a truncated array response."""
        last_complete = text.rfind("},")
        if last_complete == -1:
            last_complete = text.rfind("}")

        if last_complete == -1:
            return text

        salvaged = text[: last_complete + 1].rstrip(",").rstrip() + "\n]"
        logger.info(f"Salvaged truncated JSON: kept {last_complete + 1} of {len(text)} chars")
        return salvaged
