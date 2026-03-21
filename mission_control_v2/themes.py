"""Theme definitions for Mission Control."""
import random
from dataclasses import dataclass, field


@dataclass
class VoiceSettings:
    """Per-voice ElevenLabs tuning parameters."""
    stability: float = 0.5
    similarity_boost: float = 0.6
    style: float = 0.65
    use_speaker_boost: bool = True
    speed: float = 1.0  # ElevenLabs supports 0.25-4.0


MISSION_CONTROL_PREFIXES = [
    "New orders from the top...",
    "Agents, your next objective...",
    "Intel confirms a new target...",
    "Listen up, agents...",
    "We have a developing situation...",
]

BLUEY_PREFIXES = [
    "Ooh! Ooh! This one, this one!",
    "Ok this one's a bit tricky. Bingo, are you listening?",
    "Ready? This one's important, so listen up!",
    "Dad! ... Dad! Ok, next one!",
    "You'll never guess what we have to do next!",
]

SNOOP_PREFIXES = [
    "Snoop here. We've got a new case...",
    "Sniffy just caught a whiff of something...",
    "New case just came in, detectives...",
    "Snoop here. The plot thickens...",
    "A new clue has appeared...",
    "Sniffy's ears just perked up...",
]


@dataclass
class Theme:
    name: str
    slug: str
    announcer_voice: str
    celebration_voice: str
    intro_texts: list[str]
    outro_texts: list[str]  # {total_time} and {rounds} placeholders
    announcement_prefixes: list[str] = field(default_factory=list)
    success_prefixes: list[str] = field(default_factory=list)
    hint_prefixes: list[str] = field(default_factory=list)
    timeout_phrases: list[str] = field(default_factory=list)
    intro_music_prompt: str = ""
    intro_music_variations: list[str] = field(default_factory=list)
    announcer_voice_settings: VoiceSettings = field(default_factory=VoiceSettings)
    celebration_voice_settings: VoiceSettings = field(default_factory=VoiceSettings)
    intro_scene_prompt: str = ""
    outro_scene_prompt: str = ""
    transition_prompt: str = ""
    mission_scene_template: str = ""  # use {room} placeholder

    def wrap_announcement(self, text: str) -> str:
        if self.announcement_prefixes:
            prefix = random.choice(self.announcement_prefixes)
            return f"{prefix} {text}"
        return text

    def wrap_success(self, text: str) -> str:
        if self.success_prefixes:
            prefix = random.choice(self.success_prefixes)
            return f"{prefix} {text}"
        return text

    def wrap_hint(self, text: str) -> str:
        if self.hint_prefixes:
            prefix = random.choice(self.hint_prefixes)
            return f"{prefix} {text}"
        return text

    def pick_timeout(self) -> str:
        if self.timeout_phrases:
            return random.choice(self.timeout_phrases)
        return "Time's up. Moving on..."

    def pick_intro(self) -> str:
        return random.choice(self.intro_texts)

    def pick_outro(self) -> str:
        return random.choice(self.outro_texts)


class MissionControlTheme(Theme):
    def __init__(self):
        super().__init__(
            name="Mission Control",
            slug="mission_control",
            announcer_voice="onwK4e9ZLuTAKqWW03F9",  # Daniel
            celebration_voice="onwK4e9ZLuTAKqWW03F9",  # Daniel
            announcement_prefixes=list(MISSION_CONTROL_PREFIXES),
            success_prefixes=[
                "Consider it handled.",
                "Excellent work, team.",
                "Target acquired. Outstanding.",
                "Mission Control is impressed.",
                "Objective neutralized. Stand by for the next.",
            ],
            hint_prefixes=[
                "Mission Control has a tip for you...",
                "Intel just came in...",
                "Agents, here's a clue...",
                "Headquarters has some advice...",
                "Pay attention, agents. A hint from the top...",
            ],
            timeout_phrases=[
                "Time's up, agents. That mission is a bust. Regroup and move on.",
                "Mission failed. Don't worry, agents. There are more assignments ahead.",
                "We've lost that one, team. Shake it off. Next mission incoming.",
            ],
            intro_music_prompt="Instrumental upbeat spy mission music for kids, fast tempo, stealthy surf rock guitar with light orchestral brass, bongo drums, comical secret agent briefing, immediate energetic start, family-friendly action",
            intro_music_variations=[
                "with a driving spy bassline",
                "adding a retro synth melody",
                "with energetic bongo rolls",
                "featuring a punchy horn section",
                "with rhythmic electronic tension",
            ],
            intro_scene_prompt="Cinematic spy headquarters briefing room, agents silhouetted against a giant holographic world map, blue and cyan neon lighting, high-tech screens everywhere, dramatic atmosphere, no text, digital art, 16:9",
            outro_scene_prompt="Triumphant secret agent team celebration, fireworks and confetti against night sky, golden trophy, cinematic lighting, digital art, no text, 16:9",
            transition_prompt="Spy headquarters corridor with blue laser grid security system, moody lighting, cinematic perspective, digital art, no text, 16:9",
            mission_scene_template="Secret agent mission scene in a {room}, dramatic blue lighting, spy thriller atmosphere, kid-friendly, cinematic digital art, no text, 16:9",
            intro_texts=[
                "Attention all agents. Mission Control here. Your mission, should you choose to accept it, begins now. Stand by for your first assignment.",
                "This is Mission Control. We have a situation that requires your immediate attention. Agents, prepare for deployment. Your assignments are incoming.",
                "Good evening, agents. Mission Control has received intelligence of a critical operation. You have been selected. Prepare yourselves. Here we go.",
                "All agents report. This is not a drill. Mission Control is going live. Get ready for your first mission.",
            ],
            outro_texts=[
                "Mission complete. All agents performed brilliantly. Total time... {total_time} seconds across {rounds} missions. You are officially the best team Mission Control has ever worked with.",
                "That's a wrap, agents. {total_time} seconds, {rounds} missions, zero failures. Well... maybe a few stumbles, but Mission Control isn't judging. Much.",
                "Mission Control is impressed. {rounds} missions completed in {total_time} seconds. Your security clearance has been upgraded to... legendary.",
                "All objectives achieved. {total_time} seconds across {rounds} missions. That was top secret, world class spy work. Mission Control out.",
            ],
        )


class BlueyTheme(Theme):
    def __init__(self):
        super().__init__(
            name="Bluey",
            slug="bluey",
            announcer_voice="b8gbDO0ybjX1VA89pBdX",  # Ruby Roo (Bluey)
            celebration_voice="hk6wpUusj7FFV03U5LvR",  # Bruce (Dad/Bandit)
            announcer_voice_settings=VoiceSettings(
                stability=0.33, similarity_boost=0.68, style=0.81, speed=1.07,
            ),  # Bouncy young Aussie cartoon puppy energy
            celebration_voice_settings=VoiceSettings(
                stability=0.45, similarity_boost=0.75, style=0.65, speed=1.0,
            ),  # Warm dad energy, conversational not announcer-y
            announcement_prefixes=list(BLUEY_PREFIXES),
            success_prefixes=[
                "Wackadoo! Nice one, kids!",
                "Hooray! That was a good one!",
                "That was brilliant, mate!",
                "Ooh, good job, squirts!",
                "Beauty! Well done, kids!",
            ],
            hint_prefixes=[
                "Bingo says she knows this one!",
                "Ooh! Ooh! I know, I know! Here's a clue!",
                "Dad would say, just have a look around!",
                "Wait, wait, I'm thinking. Ok, try this!",
                "Mum! ... Mum, can we have a hint? ... She says,",
            ],
            timeout_phrases=[
                "Aww! We didn't get that one. That's ok, that's ok, let's try the next one!",
                "Oh no! Don't worry Bingo, we'll get the next one for sure!",
                "We missed that one. But that's ok because we never, ever give up! Right Bingo?",
                "Dad! We ran out of time! ... It's fine, it's fine. Next one, next one!",
            ],
            intro_music_prompt="Instrumental acoustic kids TV theme, joyful and energetic, cheerful ukulele and bouncy marimba, bright indie pop folk, sunny playground vibe, fast tempo, playful and bouncy",
            intro_music_variations=[
                "with joyful whistling",
                "featuring a playful melodica solo",
                "with energetic rhythmic handclaps",
                "adding an upbeat tambourine groove",
                "with a cheerful glockenspiel melody",
            ],
            intro_scene_prompt="Bluey and Bingo playing in a colorful Australian backyard with a treehouse, cartoon blue heeler puppies, warm sunny day, Bluey TV show style animation, kookaburras and wombats, no text, 16:9",
            outro_scene_prompt="Bluey and Bingo celebrating with balloons and streamers in the backyard, cartoon blue heeler puppies jumping for joy, golden afternoon light, Bluey TV show style, no text, 16:9",
            transition_prompt="Bluey and Bingo running along a cartoon backyard path, colorful flowers and butterflies, warm sunshine, Bluey TV show style animation, no text, 16:9",
            mission_scene_template="Bluey and Bingo on a mission in a cartoon {room}, blue heeler puppies exploring, bright colors, Bluey TV show style animation, warm and cheerful, no text, 16:9",
            intro_texts=[
                "Dad! ... Dad! Watch this. We're playing Mission Control. Ok everyone, get ready, this is going to be amazing!",
                "Bingo! Bingo, come here! We're doing Mission Control! You be the lookout and I'll read the missions. Ready? Let's go!",
                "Mum said we could play one more game before bed. So obviously we picked Mission Control! This is going to be the best one yet!",
                "This episode of Bluey is called, Mission Control! We have a super important mission and we need everyone's help. Ready? Here we go!",
            ],
            outro_texts=[
                "Well done, kids. {total_time} seconds, across {rounds} missions. That was honestly pretty impressive. Mum! Did you see what they just did?!",
                "Right! {rounds} missions in {total_time} seconds. I reckon that's a new family record! Who wants ice cream?!",
                "You absolute legends! {total_time} seconds for {rounds} missions! I think we might be the best Mission Controllers in all of Brisbane. Maybe even the world!",
                "That's it, kids. {rounds} missions, {total_time} seconds. I'm not crying, I've just got something in my eye. Alright, who's up for another round?!",
            ],
        )


class SnoopAndSniffyTheme(Theme):
    def __init__(self):
        super().__init__(
            name="Snoop and Sniffy",
            slug="snoop_and_sniffy",
            announcer_voice="JBFqnCBsd6RMkjVDRZzb",  # George
            celebration_voice="ThT5KcBeYPX3keUQqHPh",  # Dorothy
            announcement_prefixes=list(SNOOP_PREFIXES),
            success_prefixes=[
                "Case cracked.",
                "Another mystery solved.",
                "Elementary, detectives.",
                "Sniffy is doing a happy dance.",
                "The evidence doesn't lie. Well done, detectives.",
            ],
            hint_prefixes=[
                "Sniffy sniffed out a clue...",
                "Snoop has a lead...",
                "The evidence suggests...",
                "A clue from headquarters...",
                "Sniffy's nose is twitching... that means...",
            ],
            timeout_phrases=[
                "That case has gone cold. But don't worry, detectives. There are more mysteries to solve.",
                "Time's up on that one. Even Sniffy couldn't crack it. Let's move on to the next case.",
                "The trail went cold. Shake it off, detectives. Snoop and Sniffy have another case for you.",
            ],
            intro_music_prompt="Instrumental playful detective music, cartoon mystery investigation, tiptoeing pizzicato strings and sneaky comical woodwinds, curious lighthearted suspense, steady plodding rhythm, immediate progression",
            intro_music_variations=[
                "with a sneaky walking bassline",
                "adding a mysterious xylophone riff",
                "with comical tip-toeing percussion",
                "featuring a muffled jazz trumpet",
                "starting very quiet then building curiosity",
            ],
            intro_scene_prompt="Cozy detective office with magnifying glass, old maps pinned to wall, warm lamplight, mysterious shadows, children's mystery book illustration style, no text, 16:9",
            outro_scene_prompt="Detectives celebrating a solved case, confetti and gold stars, warm cozy lamplight, happy ending, children's mystery illustration, no text, 16:9",
            transition_prompt="Mysterious footprints trail along a foggy path, detective hat and magnifying glass, warm amber tones, children's illustration, no text, 16:9",
            mission_scene_template="Detective investigation scene in a {room}, magnifying glass, warm amber lamplight, mysterious clues, children's mystery illustration, no text, 16:9",
            intro_texts=[
                "Snoop here, and Sniffy's right beside me. We've got a big case to crack. Detectives, are you ready? The game is afoot...",
                "The name's Snoop. My partner Sniffy just picked up a scent. Detectives, we need your help. Let's sniff this out...",
                "Snoop and Sniffy, reporting for duty. We've got a case file thicker than Sniffy's favorite bone. Ready, detectives? Let's crack it...",
                "Sniffy's tail is wagging. That means trouble. Big trouble. Detectives, grab your magnifying glasses. The case begins now... elementary...",
            ],
            outro_texts=[
                "Case closed. Snoop and Sniffy couldn't have done it without you. {total_time} seconds across {rounds} cases. You're the best detectives in the whole neighborhood.",
                "Every case cracked. {rounds} mysteries solved in {total_time} seconds. Sniffy's doing a victory lap around the garden. You've earned your detective badges today.",
                "That's {rounds} cases in {total_time} seconds. Snoop is speechless. Actually... Snoop is never speechless, but this is close. Outstanding detective work.",
                "All {rounds} cases solved. {total_time} seconds. Sniffy wants to give everyone a big lick on the face. I told him that's not professional... He doesn't care.",
            ],
        )


ALL_THEMES = {
    "mission_control": MissionControlTheme(),
    "bluey": BlueyTheme(),
    "snoop_and_sniffy": SnoopAndSniffyTheme(),
}
