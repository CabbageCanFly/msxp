"""Load optional browser authentication without putting credentials in process arguments."""

import re
import sys
from tempfile import NamedTemporaryFile, TemporaryDirectory

from .twitch_auth import AuthError, credentials


def playback_token():
    try:
        value = credentials(keys=('TWITCH_PLAYBACK_TOKEN',))['TWITCH_PLAYBACK_TOKEN']
    except AuthError as error:
        raise ValueError(error.reason) from None
    if value and not re.fullmatch(r'[A-Za-z0-9]+', value):
        raise ValueError('TWITCH_PLAYBACK_TOKEN must contain only the bare alphanumeric browser token')
    return value


def main():
    from streamlink_cli.main import main as streamlink_main

    token = playback_token()
    if not token:
        return streamlink_main()
    # Close before Streamlink reopens it on Windows; both directory and file are private.
    with TemporaryDirectory(prefix='msxp-streamlink-') as directory:
        with NamedTemporaryFile(mode='w', encoding='utf-8', dir=directory, delete=False) as config:
            config.write('twitch-api-header=Authorization=OAuth ' + token + '\n')
        original = sys.argv
        try:
            sys.argv = [original[0], '@' + config.name, *original[1:]]
            return streamlink_main()
        finally:
            sys.argv = original


if __name__ == '__main__':
    main()
