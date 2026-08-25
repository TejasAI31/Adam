"""YouTube Music tool module utilizing ytmusicapi with unified, flag-driven dispatcher functions 
and full URL construction capabilities for LLM link opening and interaction.
"""

from typing import Dict, Any, List, Optional, Union
from ytmusicapi import YTMusic

# Global client initialization
ytm = YTMusic()

BASE_MUSIC_URL = "https://music.youtube.com"


FILTER_MAP = {
    "song": "songs",
    "songs": "songs",
    "track": "songs",
    "tracks": "songs",
    "music": "songs",
    "video": "videos",
    "videos": "videos",
    "album": "albums",
    "albums": "albums",
    "artist": "artists",
    "artists": "artists",
    "playlist": "playlists",
    "playlists": "playlists",
}

def _get_ytm_client():
    global ytm
    if ytm is None:
        try:
            ytm = YTMusic()
        except Exception as e:
            print(f"[YTMusic Client Init Error]: {e}")
    return ytm


def ytm_search_and_get(
    query: str,
    filter_type: str = "songs",
    limit: int = 5,
    get_details: bool = False
) -> str:
    """Search YouTube Music or resolve a specific entity ID depending on the get_details flag.
    Returns direct URLs for all entities.
    
    Args:
        query: Search string OR an explicit entity ID (Video/Song ID, Album ID, Playlist ID, or Artist ID).
        filter_type: Target domain. Choices: 'songs', 'videos', 'albums', 'artists', 'playlists'.
        limit: Number of results to return if performing a search (default 5).
        get_details: If True, treats 'query' as a specific ID and fetches full metadata/tracklist.
                    If False, performs a keyword search.
    """
    client = _get_ytm_client()
    if client is None:
        return "Error: YouTube Music client is currently unavailable."

    # Normalize filter_type to valid plural name
    normalized_filter = FILTER_MAP.get(str(filter_type).strip().lower(), "songs")
    query_str = str(query).strip()

    try:
        if get_details:
            # Check if query looks like a search query rather than a pure ID
            looks_like_id = len(query_str) in [11, 12] or query_str.startswith(("MPREb_", "VL", "PL", "UC", "OLAK5uy_"))
            
            if not looks_like_id:
                # User/model passed search text with get_details=True: fallback to search
                return _do_search(client, query_str, normalized_filter, limit)

            if normalized_filter in ["songs", "videos"]:
                res = client.get_song(query_str)
                video_details = res.get("videoDetails", {}) if isinstance(res, dict) else {}
                vid_id = video_details.get("videoId", query_str)
                if not video_details.get("title"):
                    # Video unavailable or lookup failed, fallback to search
                    return _do_search(client, query_str, normalized_filter, limit)
                url = f"{BASE_MUSIC_URL}/watch?v={vid_id}"
                return (
                    f"Title: {video_details.get('title')}\n"
                    f"Author: {video_details.get('author')}\n"
                    f"Duration: {video_details.get('lengthSeconds')}s\n"
                    f"Video ID: {vid_id}\n"
                    f"URL: {url}"
                )
            elif normalized_filter == "albums":
                try:
                    album = client.get_album(query_str)
                    browse_id = album.get("audioPlaylistId", query_str)
                    url = f"{BASE_MUSIC_URL}/playlist?list={browse_id}"
                    tracks = album.get("tracks", [])
                    track_summary = "\n".join([
                        f"  - {t.get('title')} ({t.get('duration', 'N/A')}) | Link: {BASE_MUSIC_URL}/watch?v={t.get('videoId')}" 
                        for t in tracks[:min(limit, 10)] if t.get('videoId')
                    ])
                    return (
                        f"Album: {album.get('title')}\n"
                        f"Artist: {', '.join([a['name'] for a in album.get('artists', [])])}\n"
                        f"Year: {album.get('year')}\n"
                        f"Track Count: {album.get('trackCount')}\n"
                        f"URL: {url}\n"
                        f"Tracks:\n{track_summary}"
                    )
                except Exception:
                    return _do_search(client, query_str, normalized_filter, limit)
            elif normalized_filter == "artists":
                try:
                    artist = client.get_artist(query_str)
                    url = f"{BASE_MUSIC_URL}/channel/{query_str}"
                    top_songs = artist.get("songs", {}).get("results", [])
                    song_summary = "\n".join([
                        f"  - {s.get('title')} | Link: {BASE_MUSIC_URL}/watch?v={s.get('videoId')}" 
                        for s in top_songs[:min(limit, 5)] if s.get('videoId')
                    ])
                    return (
                        f"Artist: {artist.get('name')}\n"
                        f"Subscribers: {artist.get('subscribers')}\n"
                        f"URL: {url}\n"
                        f"Top Songs:\n{song_summary}"
                    )
                except Exception:
                    return _do_search(client, query_str, normalized_filter, limit)
            elif normalized_filter == "playlists":
                try:
                    playlist = client.get_playlist(query_str, limit=limit)
                    url = f"{BASE_MUSIC_URL}/playlist?list={query_str}"
                    tracks = playlist.get("tracks", [])
                    track_summary = "\n".join([
                        f"  - {t.get('title')} by {', '.join([a['name'] for a in t.get('artists', [])])} | Link: {BASE_MUSIC_URL}/watch?v={t.get('videoId')}" 
                        for t in tracks[:min(limit, 10)] if t.get('videoId')
                    ])
                    return (
                        f"Playlist: {playlist.get('title')}\n"
                        f"Author: {playlist.get('author', {}).get('name') if isinstance(playlist.get('author'), dict) else 'Unknown'}\n"
                        f"Track Count: {playlist.get('trackCount')}\n"
                        f"URL: {url}\n"
                        f"Tracks:\n{track_summary}"
                    )
                except Exception:
                    return _do_search(client, query_str, normalized_filter, limit)
            else:
                return _do_search(client, query_str, normalized_filter, limit)
        else:
            return _do_search(client, query_str, normalized_filter, limit)

    except Exception as e:
        return f"Error in ytm_search_and_get: {str(e)}"


def _do_search(client: YTMusic, query: str, filter_type: str, limit: int = 5) -> str:
    try:
        results = client.search(query=query, filter=filter_type, limit=limit)
    except Exception:
        # Fallback to general search with no filter
        try:
            results = client.search(query=query, limit=limit)
        except Exception as e:
            return f"Error searching YouTube Music for '{query}': {e}"

    if not results:
        return f"No YouTube Music results found for: '{query}'."

    # Enforce limit slice
    actual_limit = max(1, min(int(limit), 10))
    sliced_results = results[:actual_limit]

    formatted = []
    for i, item in enumerate(sliced_results, 1):
        item_type = item.get("resultType", filter_type)
        item_id = item.get("videoId") or item.get("browseId") or item.get("playlistId", "")
        title = item.get("title") or item.get("artist") or item.get("name", "Unknown")
        
        artists = item.get("artists", [])
        artist_str = ", ".join([a["name"] for a in artists]) if artists else "N/A"
        
        # Construct direct URL based on result type
        if item_type in ["song", "video"] or item.get("videoId"):
            vid = item.get("videoId") or item_id
            url = f"{BASE_MUSIC_URL}/watch?v={vid}"
        elif item_type == "album":
            url = f"{BASE_MUSIC_URL}/playlist?list={item.get('playlistId', item_id)}"
        elif item_type == "artist":
            url = f"{BASE_MUSIC_URL}/channel/{item_id}"
        elif item_type == "playlist":
            url = f"{BASE_MUSIC_URL}/playlist?list={item_id}"
        else:
            url = f"{BASE_MUSIC_URL}/watch?v={item_id}" if item_id else "N/A"
        
        formatted.append(
            f"[{i}] {title} by {artist_str}\n"
            f"    Type: {item_type} | ID: {item_id}\n"
            f"    URL: {url}"
        )
    return "\n\n".join(formatted)


def ytm_get_browse_context(
    target: str = "home",
    entity_id: Optional[str] = None
) -> str:
    """Browse interactive sections, charts, related tracks, or lyrics on YouTube Music.
    Returns direct URLs for all tracks and recommendations.
    
    Args:
        target: The browsing target ('home', 'charts', 'related', 'lyrics').
        entity_id: Required if target='related' (videoId) or target='lyrics' (videoId/browseId).
    """
    client = _get_ytm_client()
    if client is None:
        return "Error: YouTube Music client is currently unavailable."

    target_clean = str(target).strip().lower()

    try:
        if target_clean in ["home", "feed", "browse"]:
            home = client.get_home(limit=3)
            sections = []
            for shelf in home:
                title = shelf.get("title", "Section")
                contents = [c.get("title", "Item") for c in shelf.get("contents", [])[:3] if isinstance(c, dict)]
                if contents:
                    sections.append(f"• {title}: {', '.join(contents)}")
            return "YouTube Music Home Feed Context:\n" + "\n".join(sections)

        elif target_clean in ["charts", "trending", "top"]:
            charts = client.get_charts(country="US")
            top_songs = []
            for s in charts.get("songs", {}).get("items", [])[:5]:
                vid = s.get('videoId')
                link_str = f" | Link: {BASE_MUSIC_URL}/watch?v={vid}" if vid else ""
                top_songs.append(f"{s.get('title')} - {', '.join([a['name'] for a in s.get('artists', [])])}{link_str}")
            
            return "Top Trending Songs (US Charts):\n" + "\n".join([f"{i+1}. {song}" for i, song in enumerate(top_songs)])

        elif target_clean in ["related", "similar"]:
            if not entity_id:
                return "Error: entity_id (videoId) is required when target='related'."
            
            watch_playlist = client.get_watch_playlist(videoId=entity_id, limit=5)
            tracks = watch_playlist.get("tracks", [])
            formatted = []
            for t in tracks[1:]:  # Skip target track
                vid = t.get('videoId')
                url = f"{BASE_MUSIC_URL}/watch?v={vid}" if vid else "N/A"
                formatted.append(f"• {t.get('title')} by {', '.join([a['name'] for a in t.get('artists', [])])}\n  ID: {vid} | URL: {url}")
                
            return f"Related Recommendations for Video ID '{entity_id}':\n" + "\n".join(formatted)

        elif target_clean in ["lyrics", "words"]:
            if not entity_id:
                return "Error: entity_id is required when target='lyrics'."
            
            lyrics_id = entity_id
            track_url = ""
            if len(entity_id) == 11:
                track_url = f"Track URL: {BASE_MUSIC_URL}/watch?v={entity_id}\n"
                watch_playlist = client.get_watch_playlist(videoId=entity_id)
                lyrics_id = watch_playlist.get("lyrics")
                if not lyrics_id:
                    return f"No lyrics available for Video ID '{entity_id}'."

            lyrics_data = client.get_lyrics(lyrics_id)
            return f"{track_url}Lyrics:\n{lyrics_data.get('lyrics', 'Lyrics unavailable.')}"

        else:
            # Fallback search if an arbitrary search term was passed as target
            return _do_search(client, target, "songs", 5)

    except Exception as e:
        return f"Error in ytm_get_browse_context: {str(e)}"


# Minimal-overhead JSON Schemas with explicit URL capability noted
YTMUSIC_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "ytm_search_and_get",
            "description": "Search YouTube Music or get full metadata, tracklists, and direct executable URLs for songs, albums, artists, or playlists.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search keywords OR explicit YouTube Music ID if get_details is true."
                    },
                    "filter_type": {
                        "type": "string",
                        "enum": ["songs", "videos", "albums", "artists", "playlists"],
                        "default": "songs",
                        "description": "Category to filter search results or describe the ID target."
                    },
                    "limit": {
                        "type": "integer",
                        "default": 5,
                        "description": "Maximum search results to return."
                    },
                    "get_details": {
                        "type": "boolean",
                        "default": False,
                        "description": "Flag switch: Set to False (default) to search. Set to True to fetch full metadata and direct links using an explicit ID."
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "ytm_get_browse_context",
            "description": "Fetches recommendations, trending charts, related tracks with links, or song lyrics.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "enum": ["home", "charts", "related", "lyrics"],
                        "default": "home",
                        "description": "Browsing mode: 'home' for feed, 'charts' for trending, 'related' for recommendations with links, 'lyrics' for track lyrics."
                    },
                    "entity_id": {
                        "type": "string",
                        "description": "Required for 'related' or 'lyrics' modes. The videoId or browseId."
                    }
                },
                "required": ["target"]
            }
        }
    }
]

# Function mapping for execution dispatching
YTMUSIC_TOOL_MAP = {
    "ytm_search_and_get": ytm_search_and_get,
    "ytm_get_browse_context": ytm_get_browse_context
}