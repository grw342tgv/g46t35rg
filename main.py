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

roblox_cookie = "_|WARNING:-DO-NOT-SHARE-THIS.--Sharing-this-will-allow-someone-to-log-in-as-you-and-to-steal-your-ROBUX-and-items.|_CAEaAhADIhwKBGR1aWQSFDEzMTU2MDE4OTAwOTc0MjU5ODcyKAM.aXQEYwSwwkc6v_oCes7UJTVT28WW9Gi8bcDfE2u51vibHNA9aoAzULDsPm-pgDmguqab4gvBi8qIWYrIz2vo2NH_FxBpIpRMFJzkREF2NwB8UJ1zb6nqMyy9FavfjjMwzCTmMqYEoCRBuqFH9LdbgEJXCG7QDNpeoGWJBET8sb7DVmwR0kX1zjH48W1mciJLLa34qAOELIFLBeBjC1o1guk4-byvfiQbgGkFlAaexF0TIN0nvgTfhe3n-ZID7aC1ljfGgBHJ79NCs3gkW1baGpduN__MtEL0uoS5kqT-XsBcID7oyNenmkkGm-o75ZOTOKNiQhKR5UHKpFOWpqs3JOl7E9drILO-uNGk1ZD5jYeaXhZMvFf5fIoC6XWK6MDpTcX-AmBeeDCLNw0GMVJKZ5btAnDnNjKIP6XGfQSzzPKokVtCZd4ASWbzBjrXX1rvsnWCeZ5LrLCyrB6KdIPE8WxrDhlcBLvH7j5NPxRAx7eoOj2W-vyy4FdGrpiynWO7SHFkjgjrf6goix-X3fuZKma9fh8GGlaeedR6rBBtQ7yCUUxJCwcAJ6XOtiAxfH6y5hj0jPI9ddvMEbRj383t6VYdnAy1G8NbVubiWaB4TdmNlKcbqptdu2UU2U3voBnyNhr4jCs6lDMLkdyxbnhOug-h7tGaxIkMncqSJsf3iwA4kuQiGPgpfndWP5QJf5J91yimhCqbsTAZbvt6i0f-grX7rk6D90vy0woJ6TNspzSIkut97O_RsHRN4BzWivqCSxxGPxeQsApAKHevb-k3kQBA8_I"

roblox_headers = {
    "Cookie": ".ROBLOSECURITY=" + roblox_cookie,
    "User-Agent": "Roblox/WinInet",
    "Requester": "Client",
    "Accept": "application/json"
}

###############################################################
# CSRF (REQUIRED FOR SOCIAL LINKS)
###############################################################

def refresh_csrf_token():
    r = session.post("https://auth.roblox.com/v2/logout", headers=roblox_headers)
    token = r.headers.get("x-csrf-token")
    if token:
        roblox_headers["X-CSRF-TOKEN"] = token

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
# DATETIME NORMALIZER (LINUX SAFE)
###############################################################

def parse_roblox_datetime(value: str) -> datetime:
    value = value.replace("Z", "+00:00")
    if "." in value:
        base, rest = value.split(".", 1)
        frac, tz = rest.split("+", 1)
        frac = frac.ljust(6, "0")[:6]
        return datetime.fromisoformat(f"{base}.{frac}+{tz}")
    return datetime.fromisoformat(value)

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
            if r.status_code == 401:
                refresh_csrf_token()
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
                time.sleep(r.json().get("retry_after", 60))
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
            return parse_roblox_datetime(created)
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
        with open(path, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def save_json_set(path: str, data: set):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(list(data), f, indent=4)

###############################################################
# MAIN
###############################################################

def load_keywords(path: str) -> list[str]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)["keywords"]

def main():
    refresh_csrf_token()

    keywords = load_keywords(keywords_file)
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

            print(f"[Scraper] {content.rootPlaceId} (created {created_at.date()})")

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
