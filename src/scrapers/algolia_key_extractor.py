"""Utility for extracting Algolia API credentials from portal page source.

Both YC (Work at a Startup) and WTTJ embed their public search-only
Algolia API keys in the page source (JavaScript bundles or __NEXT_DATA__).
This utility helps extract/refresh those keys if they change.

Usage:
    python -m src.scrapers.algolia_key_extractor --portal yc
    python -m src.scrapers.algolia_key_extractor --portal wttj
"""

from __future__ import annotations

import json
import re

import httpx
from loguru import logger


async def extract_algolia_keys(portal: str) -> dict[str, str]:
    """Extract Algolia API credentials from a portal's page source.

    Args:
        portal: "yc" or "wttj"

    Returns:
        Dict with keys: app_id, api_key, index_name (if found)
    """
    urls = {
        "yc": "https://www.workatastartup.com/companies",
        "wttj": "https://www.welcometothejungle.com/en/jobs",
    }

    url = urls.get(portal)
    if not url:
        logger.error(f"Unknown portal: {portal}")
        return {}

    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
    ) as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch {url}: {e}")
            return {}

    text = response.text
    result: dict[str, str] = {}

    # Search for Algolia credentials in various formats

    # Pattern 1: JS variables
    app_id_match = re.search(r'(?:algoliaAppId|ALGOLIA_APP_ID|applicationId|appId)["\s:=]+["\']([A-Z0-9]+)["\']', text)
    api_key_match = re.search(r'(?:algoliaApiKey|ALGOLIA_API_KEY|searchApiKey|apiKey)["\s:=]+["\']([a-zA-Z0-9]+)["\']', text)
    index_match = re.search(r'(?:algoliaIndex|ALGOLIA_INDEX|indexName)["\s:=]+["\']([a-zA-Z0-9_]+)["\']', text)

    if app_id_match:
        result["app_id"] = app_id_match.group(1)
    if api_key_match:
        result["api_key"] = api_key_match.group(1)
    if index_match:
        result["index_name"] = index_match.group(1)

    # Pattern 2: __NEXT_DATA__
    if not result:
        next_data_match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', text, re.DOTALL)
        if next_data_match:
            try:
                data = json.loads(next_data_match.group(1))
                # Search recursively for Algolia keys
                result = _find_algolia_keys_recursive(data)
            except json.JSONDecodeError:
                pass

    # Pattern 3: Inline config objects
    if not result.get("app_id"):
        for match in re.finditer(r'\{[^}]*algolia[^}]*\}', text, re.IGNORECASE):
            try:
                obj = json.loads(match.group(0))
                if "appId" in obj or "applicationId" in obj:
                    result["app_id"] = obj.get("appId", obj.get("applicationId", ""))
                    result["api_key"] = obj.get("apiKey", obj.get("searchApiKey", ""))
                    result["index_name"] = obj.get("indexName", "")
                    break
            except json.JSONDecodeError:
                continue

    if result:
        logger.info(f"Found Algolia keys for {portal}: app_id={result.get('app_id', 'N/A')}")
    else:
        logger.warning(f"Could not find Algolia keys for {portal}")

    return result


def _find_algolia_keys_recursive(data, depth: int = 0) -> dict[str, str]:
    """Recursively search nested data for Algolia API keys."""
    if depth > 8:
        return {}

    result: dict[str, str] = {}

    if isinstance(data, dict):
        # Check for direct keys
        for key in ("appId", "applicationId", "algoliaAppId"):
            if key in data:
                result["app_id"] = str(data[key])
        for key in ("apiKey", "searchApiKey", "algoliaApiKey"):
            if key in data:
                result["api_key"] = str(data[key])
        for key in ("indexName", "algoliaIndex"):
            if key in data:
                result["index_name"] = str(data[key])

        if result.get("app_id"):
            return result

        # Recurse into values
        for value in data.values():
            if isinstance(value, (dict, list)):
                found = _find_algolia_keys_recursive(value, depth + 1)
                if found.get("app_id"):
                    return found

    elif isinstance(data, list):
        for item in data[:20]:
            if isinstance(item, (dict, list)):
                found = _find_algolia_keys_recursive(item, depth + 1)
                if found.get("app_id"):
                    return found

    return result


if __name__ == "__main__":
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(description="Extract Algolia API keys from portal pages")
    parser.add_argument("--portal", required=True, choices=["yc", "wttj"], help="Portal to extract keys from")
    args = parser.parse_args()

    keys = asyncio.run(extract_algolia_keys(args.portal))
    if keys:
        print(f"App ID:     {keys.get('app_id', 'N/A')}")
        print(f"API Key:    {keys.get('api_key', 'N/A')}")
        print(f"Index Name: {keys.get('index_name', 'N/A')}")
    else:
        print("No Algolia keys found.")
