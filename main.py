import json
import requests
import time
import os

from datetime import datetime, timezone
from requests import HTTPError
from typing import List, Optional

from models.omni_search_response import OmniSearchResponse, GameContent

session = requests.Session()

###############################################################
# CONFIG
###############################################################

webhook_url = "https://discord.com/api/webhooks/1459198828870766676/2UxmTnhk5YARjQ6VghUBrYI7nVbmTGesXswkbt6m02fPGeklXnN8YVZx3gGVGwtrlqjX"

minimum_player_count = 600
maximum_player_count = 10000

MIN_CREATION_DATE = datetime(2025, 1, 1, tzinfo=timezone.utc)

keywords_file = "data/keywords.json"
already_scraped_file = "data/already_scraped.json"
already_sent_invites_file = "data/already_sent_invites.json"

roblox_cookie = "_|WARNING:-DO-NOT-SHARE-THIS.--Sharing-this-will-allow-someone-to-log-in-as-you-and-to-steal-your-ROBUX-and-items.|_CAEaAhADIhwKBGR1aWQSFDEzMTU2MDE4OTAwOTc0MjU5ODcyKAM.QsvhQMIzxtjcMVllueKhiIiaGtezp7o1S99cCMtAPisSZZhcqcMjJCGgWUyoZGRiwz0bkiCepwJB2MoQQxpvRh4_uo_kCJUTPmV5u7psMlAexoaHjc56zJIGOxPyj27M5dZ9RC_V5v1hd682Jkk0obHEdFzweWO5oxioFCV5A7HZ5LywilVGV1PB_R10vl0EY7GxYKwBch2HVK5xTdWOp99LKmmqQzvG5Emh-7OThbWQ53885078nZSW9RH8l0QW4R_5y6exUdY7vj5GUiftmfIYbQKgW4phq1g1Zs-f-D2qfujVZGb6Ba24_b3B0n7CnaXpYH9bUK17HTWBXwjPmxiRDgE0wzkoVYUmYOhIskRnPZNrRxWqbG-tbSPUeXtzc7OBF887PI8PpoUxAUOaCsHJbIVy2bMd1d2oVOkVPV7HfEDhWBrwhAL6uu8UZowEnKCzUzVEaG8vbc6QonfSlu3UeUW5Rn8zUxU6yNTi29yXiDVqf6y_7xraQcQdowreWFpfDMZk6aYxvacry15rAAo0zslPvboGsoUCamZy1-HxX-9IDX08gDQjKDhjcwtkr-wwKrE1hb3KgWTSQ9EKyuAyh7f1b6xTbuIhx7ZdI4HXdDEhb8tD3keAB8cqwT3aSfnH6po_v4CWD64c0cpTZElyEksnPP2cbk66pW_dze3pN_HEU0dQKOFaEXT7c3fqJVIMtfg4FHqMes5QhKvz8E4j49TPhVekalh7A5ydZAIFwb5XZ4idPNLWrZpT2XaOGoCNsn3ogsMg0-1X1sFpgojEpUs"

roblox_headers = {
    "Cookie": ".ROBLOSECURITY=" + roblox_cookie,
    "User-Agent": "Roblox/WinInet",
    "Requester": "Client"
}

###############################################################
# BACKOFF
###############################################################

def with_backoff(func, max_retries: int = 15, *args, **kwargs):
    attempt = 0
    while True:
        try:
            return func(*args, **kwargs)
        except requests.RequestException as e:
            attempt += 1
            print(f"Request error: {e}. Attempt {attempt}/{max_retries}")
            if attempt >= max_retries:
                raise
            time.sleep(2 ** attempt)

###############################################################
# ROBLOX API
###############################################################

class RobloxAPI:
    @staticmethod
    def get_discord_invite(game_id: int) -> HTTPError | str | None:
        def request():
            r = session.get(
                f"https://games.roblox.com/v1/games/{game_id}/social-links/list",
                headers=roblox_headers
            )
            r.raise_for_status()
            data = r.json()
            return next(
                (l.get("url") for l in data.get("data", []) if l.get("type") == "Discord"),
                None
            )
        return with_backoff(request)

    @staticmethod
    def omni_search(keyword: str, page_token: Optional[str] = None) -> List[GameContent]:
        results = []
        max_pages = 3
        page_count = 0

        def request():
            params = {
                "searchQuery": keyword,
                "pageToken": page_token,
                "sessionId": "SNC2",
                "pageType": "All"
            }
            r = session.get(
                "https://apis.roblox.com/search-api/omni-search",
                params=params,
                headers=roblox_headers
            )

            if r.status_code == 429:
                retry_after = r.json().get("retry_after", 60)
                time.sleep(retry_after)
                return request()

            r.raise_for_status()
            return OmniSearchResponse.parse_obj(r.json())

        while True:
            data = with_backoff(request)

            results.extend(
                content
                for result in data.searchResults
                for content in result.contents
                if minimum_player_count <= content.playerCount <= maximum_player_count
            )

            if not data.nextPageToken or page_count >= max_pages:
                break

            page_token = data.nextPageToken
            page_count += 1

        return results

    @staticmethod
    def get_universe_creation_date(universe_id: int) -> Optional[datetime]:
        def request():
            r = session.get(
                "https://games.roblox.com/v1/games",
                params={"universeIds": universe_id},
                headers=roblox_headers
            )
            r.raise_for_status()
            games = r.json().get("data", [])
            if not games:
                return None
            created = games[0].get("created")
            if not created:
                return None
            return datetime.fromisoformat(created.replace("Z", "+00:00"))
        return with_backoff(request)

###############################################################
# DISCORD
###############################################################

class DiscordAPI:
    @staticmethod
    def post_webhook(webhook_url: str, message: str):
        while True:
            try:
                r = session.post(webhook_url, json={"content": message})
                if r.status_code == 429:
                    time.sleep(r.json().get("retry_after", 60))
                    continue
                r.raise_for_status()
                break
            except requests.RequestException as e:
                print(f"[DiscordWebhook] {e}")
                time.sleep(3)

###############################################################
# STORAGE
###############################################################

def load_json_set(path: str) -> set:
    if os.path.exists(path):
        with open(path, "r") as f:
            return set(json.load(f))
    return set()

def save_json_set(path: str, data: set):
    with open(path, "w") as f:
        json.dump(list(data), f, indent=4)

###############################################################
# MAIN
###############################################################

def main():
    keywords = json.load(open(keywords_file))["keywords"]

    already_scraped = load_json_set(already_scraped_file)
    already_sent = load_json_set(already_sent_invites_file)

    for keyword in keywords:
        print(f"[Scraper] Searching: {keyword}")
        contents = RobloxAPI.omni_search(keyword)

        for content in contents:
            if content.universeId in already_scraped:
                continue

            created_at = RobloxAPI.get_universe_creation_date(content.universeId)

            if not created_at or created_at < MIN_CREATION_DATE:
                already_scraped.add(content.universeId)
                save_json_set(already_scraped_file, already_scraped)
                continue

            print(
                f"[Scraper] {content.rootPlaceId} "
                f"(created {created_at.date()})"
            )

            discord_url = RobloxAPI.get_discord_invite(content.universeId)

            if discord_url and discord_url not in already_sent:
                DiscordAPI.post_webhook(
                    webhook_url,
                    f"URL: https://www.roblox.com/games/{content.rootPlaceId}/--\n"
                    f"Active Players: **{content.playerCount}**\n"
                    f"Created: **{created_at.date()}**\n"
                    f"Discord: {discord_url}"
                )

                already_sent.add(discord_url)
                save_json_set(already_sent_invites_file, already_sent)

            already_scraped.add(content.universeId)
            save_json_set(already_scraped_file, already_scraped)

if __name__ == "__main__":
    main()
