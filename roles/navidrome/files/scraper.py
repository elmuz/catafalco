import argparse
import logging
import os
import sys
import urllib.parse
from argparse import Namespace
from functools import partial
from pathlib import Path
from typing import Dict

import requests


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter("%(levelname)s: %(message)s")
console_handler.setFormatter(console_formatter)
logger.addHandler(console_handler)


def get_json_response_from_api_generic(
    navidrome_url,
    endpoint,
    base_params: Dict[str, str],
    custom_params: Dict[str, str] | None = None,
):
    """
    Constructs the full Subsonic API URL with common parameters and authentication.
    """
    full_params = {**base_params, **(custom_params if custom_params else {})}
    query_string = urllib.parse.urlencode(full_params)
    url = f"{navidrome_url}/rest/{endpoint}.view?{query_string}"
    response = requests.get(url, timeout=5)  # Add a timeout for robustness
    response.raise_for_status()  # Raises an HTTPError for bad responses (4xx or 5xx)
    return response.json()["subsonic-response"]


def run(args: Namespace) -> None:
    navidrome_url = args.url.rstrip("/")
    base_params = {
        "u": args.username,
        "t": args.hashed_password,
        "s": args.salt,
        "v": "1.16.1",
        "c": "ReplayGainChecker",
        "f": "json",
    }

    get_json_response_from_api = partial(
        get_json_response_from_api_generic, navidrome_url, base_params=base_params
    )

    offset = 0
    page_size = 100
    missing_replaygain_albums = set()

    while True:
        albums_data = get_json_response_from_api(
            "getAlbumList2",
            custom_params={
                "type": "newest",
                "size": str(page_size),
                "offset": str(offset),
            },
        )
        if not albums_data["albumList2"]["album"]:
            # No albums returned in this page, we've reached the end
            break

        for album in albums_data["albumList2"]["album"]:
            if int(album["songCount"]) == 0:
                logger.warning(f"Album '{album['id']}' has 0 tracks: unexpected!")
                continue

            album_data = get_json_response_from_api(
                "getAlbum", custom_params={"id": album["id"]}
            )
            try:
                album_path = f"{album_data['album']['artist']}/{album_data['album']['name']} ({album_data['album']['year']})"
            except KeyError:
                logger.warning(
                    f"Missing metadata for {album_data['album']['artist']}/{album_data['album']['name']}"
                )
                continue

            has_replaygain_attributes = True
            for song in album_data["album"]["song"]:
                if song.get("replayGain") is None:
                    logger.info(
                        f"{song['artist']}/{song['album']} does not have 'replayGain' attribute"
                    )
                    missing_replaygain_albums.add(album_path)
                    break
                # FIXME: There's a bug, when "trackGain" or "albumGain" is 0.0, then it is not returned.
                # FIXME: Sometimes tracks do not have attributes (e.g. "pure silence")
                for gain_info in ["trackPeak", "albumPeak", "trackGain", "albumGain"]:
                    if song["replayGain"].get(gain_info) is None:
                        logger.info(
                            f"{song['artist']}/{song['album']} does not have 'replayGain' sub-attribute {gain_info}."
                        )
                        logger.debug(f"{song}")
                        missing_replaygain_albums.add(album_path)
                        has_replaygain_attributes = False
                        break
                if not has_replaygain_attributes:
                    break

        offset += page_size

        if len(albums_data["albumList2"]["album"]) < page_size:
            # If the number of albums returned is less than the page size,
            # it means we've reached the end of the list.
            break

    with args.report_file.open("w") as f:
        f.write("\n".join(missing_replaygain_albums))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        "Navidrome ReplayGain Metadata Checker",
        description="This script will scan your Navidrome library for songs missing ReplayGain info.",
    )
    parser.add_argument("url", type=str)
    parser.add_argument("-u", "--username", type=str, required=True)
    parser.add_argument("-t", "--hashed-password", type=str, required=True)
    parser.add_argument("-s", "--salt", type=str, required=True)
    parser.add_argument(
        "-r", "--report-file", type=Path, default=Path.cwd() / "report.txt"
    )
    parser.add_argument("-l", "--log-file", type=Path, default=Path.cwd() / "error.log")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    if args.report_file.exists():
        os.remove(args.report_file)
    if args.log_file.exists():
        os.remove(args.log_file)
    file_handler = logging.FileHandler(args.log_file)
    file_handler.setLevel(logging.DEBUG if args.verbose else logging.WARNING)
    file_formatter = logging.Formatter("%(asctime)s - %(levelname)s: %(message)s")
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    run(args)
