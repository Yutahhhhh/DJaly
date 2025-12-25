import aiohttp
import urllib.parse
import re
from typing import Optional, Dict, Any

def should_skip_track(text: str) -> bool:
    """
    Check if the track is a DJ tool, remix, or edit that should be skipped.
    """
    if not text: return False
    
    # BPM Transition pattern (e.g. 100-124)
    if re.search(r'\d{2,3}-\d{2,3}', text):
        return True

    # DJ Tool / Remix keywords
    # Note: "Mix" is common in "Original Mix", so we might want to be careful.
    # But user requested to skip remixes to avoid timestamp issues.
    keywords = r'transition|intro|outro|clean|dirty|extended|edit|mashup|bootleg'
    if re.search(fr'(?i)\b({keywords})\b', text):
        return True
        
    return False

def clean_search_term(text: str) -> str:
    """
    Remove noise from search terms to improve hit rate.
    e.g. "Song Title (feat. Guest)" -> "Song Title"
    """
    if not text: return ""
    # Remove content inside parentheses and brackets
    text = re.sub(r'[\(\[].*?[\)\]]', '', text)
    # Normalize whitespace
    return " ".join(text.split())

async def fetch_itunes_release_date(artist: str, title: str) -> Optional[str]:
    """
    Fetch release date from iTunes Search API.
    Returns ISO date string (YYYY-MM-DDTHH:MM:SSZ) or None.
    """
    if not artist or not title or artist == "Unknown" or title == "Unknown":
        return None

    # Skip DJ tools / Remixes
    if should_skip_track(title):
        print(f"DEBUG: Skipping DJ tool/Remix: {title}", flush=True)
        return None

    # Try exact match first, then cleaned match
    queries = [
        f"{artist} {title}",
        f"{clean_search_term(artist)} {clean_search_term(title)}"
    ]
    # Remove duplicates and empty queries
    queries = list(dict.fromkeys([q for q in queries if q.strip()]))

    async with aiohttp.ClientSession() as session:
        for query in queries:
            # Skip if query still looks like a DJ tool (contains numbers like 100-123)
            # Already checked by should_skip_track, but keeping as safety net if needed
            # if re.search(r'\d{2,3}-\d{2,3}', query):
            #     print(f"DEBUG: Skipping DJ tool query: '{query}'", flush=True)
            #     continue

            encoded_query = urllib.parse.quote(query)
            url = f"https://itunes.apple.com/search?term={encoded_query}&entity=song&limit=1"

            try:
                print(f"DEBUG: Searching iTunes for: '{query}'", flush=True)
                async with session.get(url) as response:
                    if response.status == 200:
                        # iTunes API returns 'text/javascript' sometimes, so we use content_type=None to force parsing
                        data = await response.json(content_type=None)
                        if data["resultCount"] > 0:
                            result = data["results"][0]
                            print(f"DEBUG: iTunes Match: {result.get('artistName')} - {result.get('trackName')} ({result.get('releaseDate')})", flush=True)
                            return result.get("releaseDate")
                        else:
                            print(f"DEBUG: iTunes No Results for: '{query}'", flush=True)
                    else:
                        print(f"DEBUG: iTunes API Error {response.status} for: '{query}'", flush=True)
            except Exception as e:
                print(f"Error fetching from iTunes (query: {query}): {e}", flush=True)
    
    return None

async def fetch_lrclib_lyrics(
    artist: str, 
    title: str, 
    album: Optional[str] = None, 
    duration: Optional[float] = None
) -> Optional[Dict[str, Any]]:
    """
    Fetch lyrics from LRCLIB API.
    Returns dict with 'plainLyrics', 'syncedLyrics', etc. or None.
    """
    if not artist or not title or artist == "Unknown" or title == "Unknown":
        return None

    # Skip DJ tools / Remixes
    if should_skip_track(title):
        print(f"DEBUG: Skipping DJ tool/Remix (Lyrics): {title}", flush=True)
        return None

    # LRCLIB /get endpoint requires precise match, /search is better for fuzzy
    # But let's try /get first if we have duration, as it's more accurate
    
    params = {
        "artist_name": artist,
        "track_name": title,
    }
    if album and album != "Unknown":
        params["album_name"] = album
    if duration:
        params["duration"] = str(int(duration))

    url = "https://lrclib.net/api/get"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    return await response.json()
                elif response.status == 404:
                    # Fallback to search if strict match fails
                    search_url = "https://lrclib.net/api/search"
                    search_params = {"q": f"{artist} {title}"}
                    async with session.get(search_url, params=search_params) as search_res:
                        if search_res.status == 200:
                            results = await search_res.json()
                            if results and len(results) > 0:
                                # Simple heuristic: pick first result
                                return results[0]
    except Exception as e:
        print(f"Error fetching from LRCLIB: {e}")

    return None
