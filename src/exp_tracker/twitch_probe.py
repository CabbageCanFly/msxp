"""Official Helix thumbnail experiment. No full images are written to disk."""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from PIL import Image

from .models import Region
from .recognition import recognize

MAX_IMAGE_BYTES = 8 * 1024 * 1024


def thumbnail_url(template: str, width: int, height: int) -> str:
    url = template.replace("{width}", str(width)).replace("{height}", str(height))
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "static-cdn.jtvnw.net" or parsed.port not in (None, 443):
        raise ValueError("Unexpected Twitch thumbnail host; refusing download")
    return url


def helix(endpoint: str, params: dict, client_id: str, token: str) -> dict:
    request = Request("https://api.twitch.tv/helix/" + endpoint + "?" + urlencode(params),
                      headers={"Client-Id": client_id, "Authorization": "Bearer " + token})
    with urlopen(request, timeout=15) as response:
        return json.load(response)


def inspect_thumbnail(payload: bytes, regions: dict[str, Region] | None = None) -> dict:
    with Image.open(BytesIO(payload)) as source:
        if source.width * source.height > 4096 * 4096:
            raise ValueError("Thumbnail exceeds pixel limit")
        image = source.convert("RGB")
    result = {"image_size": list(image.size), "download_bytes": len(payload),
              "sha256": hashlib.sha256(payload).hexdigest()}
    if regions:
        result["hud_sha256"] = {name: hashlib.sha256(image.crop(roi.pixels(*image.size)).tobytes()).hexdigest()
                                for name, roi in regions.items()}
        result["recognition"] = asdict(recognize(image, regions=regions))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("channel", help="Twitch login; no URL")
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--config", type=Path, help="Optional normalized ROIs for OCR and HUD hashes")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9_]{1,25}", args.channel):
        parser.error("Use a Twitch login, not a URL")
    if not 1 <= args.count <= 120 or args.interval < 30 or not (8 <= args.width <= 4096 and 8 <= args.height <= 4096):
        parser.error("count: 1..120; interval: >=30 seconds; dimensions: 8..4096")
    client_id, token = os.environ.get("TWITCH_CLIENT_ID"), os.environ.get("TWITCH_ACCESS_TOKEN")
    if not client_id or not token:
        print(json.dumps({"status": "error", "reason": "Set TWITCH_CLIENT_ID and TWITCH_ACCESS_TOKEN locally"}), file=sys.stderr)
        return 1
    try:
        regions = None
        if args.config:
            config = json.loads(args.config.read_text(encoding="utf-8"))
            if not isinstance(config, dict) or set(config) != {"level", "exp"}:
                raise ValueError("Configure both level and exp ROIs")
            regions = {key: Region(*coords) for key, coords in config.items()}
        users = helix("users", {"login": args.channel}, client_id, token)["data"]
        if not users:
            print(json.dumps({"status": "unknown_channel"}))
            return 2
        previous_hash = None
        for index in range(args.count):
            started = time.monotonic()
            data = helix("streams", {"user_id": users[0]["id"]}, client_id, token)["data"]
            result = {"received_at": datetime.now(timezone.utc).isoformat(), "frame_captured_at": None}
            if not data:
                result["status"] = "offline"
            else:
                url = thumbnail_url(data[0]["thumbnail_url"], args.width, args.height)
                # Cache busting cannot force Twitch to capture a fresh frame.
                url += ("&" if "?" in url else "?") + urlencode({"probe": time.time_ns()})
                with urlopen(url, timeout=15) as response:
                    payload = response.read(MAX_IMAGE_BYTES + 1)
                    if len(payload) > MAX_IMAGE_BYTES:
                        raise ValueError("Thumbnail exceeds byte limit")
                    result["cdn_headers"] = {key: response.headers.get(key) for key in ("Age", "ETag", "Last-Modified")}
                result.update(inspect_thumbnail(payload, regions))
                result.update(status="live", changed_since_previous=None if previous_hash is None else result["sha256"] != previous_hash)
                previous_hash = result["sha256"]
            result["elapsed_seconds"] = round(time.monotonic() - started, 3)
            print(json.dumps(result), flush=True)
            if index + 1 < args.count:
                time.sleep(max(0, args.interval - (time.monotonic() - started)))
        return 0
    except HTTPError as error:
        # Do not dump request headers, URLs or response bodies containing user data.
        print(json.dumps({"status": "http_error", "code": error.code,
                          "rate_limit_reset": error.headers.get("Ratelimit-Reset"),
                          "retry_after": error.headers.get("Retry-After")}), file=sys.stderr)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, URLError):
        print(json.dumps({"status": "error", "reason": "Request, image, configuration or OCR failed; credentials omitted"}), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
