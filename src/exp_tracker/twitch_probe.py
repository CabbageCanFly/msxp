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
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from PIL import Image

from .models import Region
from .recognition import recognize
from .twitch_auth import AppTokens,AuthError

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_STREAM_PAGES = 3
STREAM_STATUS_BATCH = 25


def thumbnail_url(template: str, width: int, height: int) -> str:
    url = template.replace("{width}", str(width)).replace("{height}", str(height))
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "static-cdn.jtvnw.net" or parsed.port not in (None, 443):
        raise ValueError("Unexpected Twitch thumbnail host; refusing download")
    return url


def helix(endpoint: str, params: dict, client_id: str, token: str, *, timeout=15) -> dict:
    request = Request("https://api.twitch.tv/helix/" + endpoint + "?" + urlencode(params,doseq=True),
                      headers={"Client-Id": client_id, "Authorization": "Bearer " + token})
    with urlopen(request, timeout=timeout) as response:
        payload=response.read(262145)
        if len(payload)>262144:raise ValueError('Helix response exceeds byte limit')
        return json.loads(payload)


class StreamAvailability:
    """Opt-in, process-local Get Streams cache; never evidence of capture health."""
    def __init__(self, *, enabled=False, fetch=None, clock=time.monotonic,auth=None):
        self.enabled=enabled;self.fetch=fetch or helix;self.clock=clock
        self.auth=auth or AppTokens(clock=clock)
        self.lock=threading.Lock();self.next_check=0;self.results={}

    def snapshot(self,channels,*,now=None):
        channels=tuple(sorted(set(channels)))
        if any(not re.fullmatch(r'[a-z0-9_]{1,25}',c) for c in channels):
            raise ValueError('Valid configured Twitch logins required')
        now=now or datetime.now(timezone.utc)
        with self.lock:
            if self.clock()>=self.next_check:
                reason=None;live=set();completed=set();delay=60
                if not self.enabled:reason='not_enabled'
                elif channels:
                    try:
                        client,token=self.auth.get()
                        reauthenticated=False
                        for offset in range(0,len(channels),STREAM_STATUS_BATCH):
                            batch=channels[offset:offset+STREAM_STATUS_BATCH]
                            params=dict(user_login=list(batch),first=100);seen=set()
                            for _ in range(MAX_STREAM_PAGES):
                                try:response=self.fetch('streams',params.copy(),client,token,timeout=3)
                                except HTTPError as error:
                                    if error.code!=401 or reauthenticated:raise
                                    reauthenticated=True
                                    client,token=self.auth.get(rejected_token=token)
                                    response=self.fetch('streams',params.copy(),client,token,timeout=3)
                                data=response['data']
                                if not isinstance(data,list) or len(data)>STREAM_STATUS_BATCH:
                                    raise ValueError('Invalid stream status response')
                                page=set()
                                for row in data:
                                    if row.get('user_login') not in batch or row.get('type')!='live':
                                        raise ValueError('Unexpected stream status response')
                                    page.add(row['user_login'])
                                live.update(page)
                                if all(c in live for c in batch):break
                                cursor=response.get('pagination',{}).get('cursor','')
                                if not isinstance(cursor,str) or len(cursor)>2048:
                                    raise ValueError('Invalid pagination cursor')
                                if not cursor:break
                                if cursor in seen:
                                    reason='pagination_repeated_cursor';break
                                seen.add(cursor);params['after']=cursor
                            else:reason='pagination_limit'
                            if reason:break
                            completed.update(batch)
                    except AuthError as error:
                        reason=error.reason;delay=max(60,error.retry_after)
                    except HTTPError as error:
                        reason='credentials_rejected' if error.code==401 else 'rate_limited' if error.code==429 else 'api_error'
                        if error.code==401:self.auth.reject(token);delay=300
                        if error.code==429:
                            try:delay=max(60,min(900,int(error.headers.get('Retry-After','60'))))
                            except (TypeError,ValueError):pass
                    except (OSError,ValueError,TypeError,KeyError,AttributeError,URLError):reason='api_unavailable'
                self.results={c:dict(status='live' if c in live else 'offline' if c in completed else 'unknown' if reason else 'offline',
                    reason=None if c in live or c in completed else reason,checked_at=now.isoformat(),source='twitch_helix_get_streams',
                    valid_until=datetime.fromtimestamp(now.timestamp()+(60 if c in live or c in completed else delay),timezone.utc).isoformat(),
                    last_known_status=(self.results.get(c,{}).get('last_known_status') if self.results.get(c,{}).get('status')=='unknown'
                        else self.results.get(c,{}).get('status')) if reason and c not in live and c not in completed else None) for c in channels}
                self.next_check=self.clock()+delay
            result={c:dict(self.results.get(c,dict(status='unknown',reason='awaiting_batch',checked_at=None,
                valid_until=None,source='twitch_helix_get_streams'))) for c in channels}
            for status in result.values():
                if status['status'] in ('live','offline') and now>datetime.fromisoformat(status['valid_until']):
                    status.update(last_known_status=status['status'],status='unknown',reason='stale_check')
            return result


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
    parser.add_argument("channel", nargs='+', help="Twitch login; no URL (one or more with --status-only)")
    parser.add_argument('--status-only',action='store_true',help='Read-only live/offline verification with automatic app authentication; no capture or thumbnails')
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--config", type=Path, help="Optional normalized ROIs for OCR and HUD hashes")
    args = parser.parse_args(argv)
    if len(args.channel)>25 or any(not re.fullmatch(r"[A-Za-z0-9_]{1,25}", channel) for channel in args.channel):
        parser.error("Use a Twitch login, not a URL")
    if args.status_only:
        statuses=StreamAvailability(enabled=True).snapshot([c.lower() for c in args.channel])
        print(json.dumps(dict(channels=statuses)))
        return 1 if any(s['status']=='unknown' for s in statuses.values()) else 0
    if len(args.channel)!=1:parser.error('Thumbnail experiment accepts one channel')
    args.channel=args.channel[0]
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
