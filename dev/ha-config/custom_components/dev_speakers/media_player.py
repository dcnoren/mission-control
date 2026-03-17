"""Fake media_player entities for dev/testing."""
import voluptuous as vol

from homeassistant.components.media_player import (
    PLATFORM_SCHEMA,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.const import CONF_NAME
import homeassistant.helpers.config_validation as cv

CONF_SPEAKERS = "speakers"
CONF_UNIQUE_ID = "unique_id"

SPEAKER_SCHEMA = vol.Schema({
    vol.Required(CONF_NAME): cv.string,
    vol.Required(CONF_UNIQUE_ID): cv.string,
})

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_SPEAKERS): vol.All(cv.ensure_list, [SPEAKER_SCHEMA]),
})


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up fake speaker entities."""
    entities = []
    for speaker in config[CONF_SPEAKERS]:
        entities.append(DevSpeaker(speaker[CONF_NAME], speaker[CONF_UNIQUE_ID]))
    async_add_entities(entities, True)


class DevSpeaker(MediaPlayerEntity):
    """A fake media player that accepts play_media/volume_set/stop calls."""

    _attr_supported_features = (
        MediaPlayerEntityFeature.PLAY_MEDIA
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.STOP
    )

    def __init__(self, name: str, unique_id: str) -> None:
        self._attr_name = name
        self._attr_unique_id = unique_id
        self._attr_state = MediaPlayerState.IDLE
        self._attr_volume_level = 0.5

    async def async_play_media(self, media_type, media_id, **kwargs):
        self._attr_state = MediaPlayerState.PLAYING
        self.async_write_ha_state()

    async def async_set_volume_level(self, volume):
        self._attr_volume_level = volume
        self.async_write_ha_state()

    async def async_media_stop(self):
        self._attr_state = MediaPlayerState.IDLE
        self.async_write_ha_state()
