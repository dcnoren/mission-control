"""Apple TV manager for Mission Control — thin wrapper around pyatv.

Includes a monkey-patch for pyatv's RTSP local_ip to work from Docker
(see https://github.com/postlund/pyatv/issues/2559).
"""
import asyncio
import json
import logging
from typing import Optional
from urllib.parse import urlparse

import pyatv
from pyatv.const import Protocol
from pyatv.interface import AppleTV as AppleTVDevice

logger = logging.getLogger("mission_control.appletv")


def patch_rtsp_local_ip(host_ip: str):
    """Monkey-patch pyatv's HttpConnection so RTSP announces the host IP
    instead of the Docker-internal IP."""
    from pyatv.support import http as _http

    _original_connection_made = _http.HttpConnection.connection_made

    def _patched_connection_made(self, transport):
        _original_connection_made(self, transport)
        if self._local_ip and self._local_ip != host_ip:
            logger.info(
                f"RTSP IP patch: {self._local_ip} -> {host_ip}"
            )
            self._local_ip = host_ip

    _http.HttpConnection.connection_made = _patched_connection_made
    logger.info(f"Patched pyatv RTSP local_ip to {host_ip}")


class AppleTVManager:
    def __init__(self):
        self.device: Optional[AppleTVDevice] = None
        self._pairing: Optional[pyatv.interface.PairingHandler] = None
        self._pairing_ip: Optional[str] = None
        self._pairing_protocol: Optional[Protocol] = None

    @property
    def connected(self) -> bool:
        return self.device is not None

    async def _discover(self, ip: str, timeout: float = 5.0) -> Optional[pyatv.conf.AppleTV]:
        """Discover an Apple TV by unicast scan. Returns config or None."""
        try:
            devices = await pyatv.scan(
                asyncio.get_event_loop(), timeout=timeout, hosts=[ip]
            )
            if devices:
                logger.info(f"Discovered {devices[0].name} at {ip}")
                for s in devices[0].services:
                    logger.info(f"  {s.protocol}: port={s.port} id={s.identifier}")
                return devices[0]
        except Exception as e:
            logger.error(f"Unicast scan failed for {ip}: {e}")
        return None

    async def scan(self, timeout: float = 5.0) -> list[dict]:
        """Discover Apple TV devices on the LAN via mDNS."""
        try:
            devices = await pyatv.scan(asyncio.get_event_loop(), timeout=timeout)
            results = []
            for d in devices:
                results.append({
                    "name": d.name,
                    "ip": str(d.address),
                })
            logger.info(f"Scan found {len(results)} Apple TV devices")
            return results
        except Exception as e:
            logger.error(f"Apple TV scan failed: {e}")
            return []

    async def connect(self, ip: str, credentials: dict | str = "") -> bool:
        """Connect to an Apple TV by IP address.

        credentials: JSON dict mapping protocol names to credential strings,
                     or a legacy single credential string.
        """
        await self.disconnect()
        try:
            config = await self._discover(ip)
            if not config:
                logger.error(f"Could not discover Apple TV at {ip}")
                return False

            # Apply stored credentials to each service
            creds_map = {}
            if isinstance(credentials, str) and credentials:
                try:
                    creds_map = json.loads(credentials)
                except json.JSONDecodeError:
                    creds_map = {"AirPlay": credentials}
            elif isinstance(credentials, dict):
                creds_map = credentials

            for service in config.services:
                proto_name = service.protocol.name
                if proto_name in creds_map:
                    service.credentials = creds_map[proto_name]
                    logger.info(f"Applied credentials for {proto_name}")

            self.device = await pyatv.connect(config, asyncio.get_event_loop())
            logger.info(f"Connected to Apple TV at {ip}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Apple TV at {ip}: {e}")
            self.device = None
            return False

    async def pair(self, ip: str, protocol: Protocol = Protocol.AirPlay) -> bool:
        """Start the pairing flow. Returns True if PIN entry is needed."""
        try:
            config = await self._discover(ip)
            if not config:
                logger.error(f"Could not discover Apple TV at {ip} for pairing")
                return False

            self._pairing_ip = ip
            self._pairing_protocol = protocol
            self._pairing = await pyatv.pair(
                config, protocol, asyncio.get_event_loop()
            )
            await self._pairing.begin()
            logger.info(
                f"Pairing ({protocol.name}) started with Apple TV at {ip}"
            )
            return True
        except Exception as e:
            logger.error(f"Pairing start failed: {e}")
            self._pairing = None
            return False

    async def pair_confirm(self, pin: str) -> Optional[dict]:
        """Finish pairing with the PIN shown on the TV.
        Returns {protocol_name: credentials} dict or None."""
        if not self._pairing:
            logger.error("No pairing in progress")
            return None
        try:
            self._pairing.pin(int(pin))
            await self._pairing.finish()
            if self._pairing.has_paired:
                creds = str(self._pairing.service.credentials)
                proto = self._pairing_protocol.name if self._pairing_protocol else "AirPlay"
                logger.info(f"Pairing successful for {proto}")
                await self._pairing.close()
                self._pairing = None
                return {proto: creds}
            else:
                logger.error("Pairing did not complete")
                await self._pairing.close()
                self._pairing = None
                return None
        except Exception as e:
            logger.error(f"Pairing confirm failed: {e}")
            if self._pairing:
                await self._pairing.close()
            self._pairing = None
            return None

    async def play_url(self, url: str):
        """Play a URL on the Apple TV (video or audio).

        pyatv's play_url blocks until playback ends by polling /playback-info,
        but tvOS 18+ returns 500 on that endpoint. We catch the error and
        return successfully since the content was already sent to the ATV.
        """
        if not self.device:
            raise RuntimeError("Not connected to Apple TV")
        logger.info(f"Playing URL on Apple TV: {url}")
        try:
            await self.device.stream.play_url(url)
        except Exception as e:
            # tvOS 18+ returns 500 on /playback-info but playback still works
            err_str = str(e)
            if "500" in err_str and "playback-info" in err_str.lower():
                logger.info("play_url: ignoring tvOS 18 /playback-info 500 (playback likely started)")
            elif "500" in err_str:
                logger.warning(f"play_url: ignoring server error (playback likely started): {e}")
            else:
                raise

    async def stream_file(self, file_path: str):
        """Stream a local file to Apple TV via RAOP."""
        if not self.device:
            raise RuntimeError("Not connected to Apple TV")
        logger.info(f"Streaming file to Apple TV: {file_path}")
        await self.device.stream.stream_file(file_path)

    async def set_volume(self, level: float):
        """Set Apple TV volume (0.0–1.0 mapped to 0–100)."""
        if not self.device:
            return
        try:
            await self.device.audio.set_volume(level * 100)
        except Exception as e:
            logger.warning(f"Could not set Apple TV volume: {e}")

    async def stop(self):
        """Stop current playback."""
        if not self.device:
            return
        try:
            await self.device.remote_control.stop()
        except Exception as e:
            logger.warning(f"Could not stop Apple TV playback: {e}")

    async def disconnect(self):
        """Cleanly disconnect from Apple TV."""
        if self.device:
            self.device.close()
            self.device = None
            logger.info("Disconnected from Apple TV")
