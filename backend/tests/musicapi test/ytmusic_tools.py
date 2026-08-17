"""YouTube Music tool module utilizing ytmusicapi with unified, flag-driven dispatcher functions 
and full URL construction capabilities for LLM link opening and interaction.
"""

from typing import Dict, Any, List, Optional, Union
from ytmusicapi import YTMusic

# Global client initialization
ytm = YTMusic()

BASE_MUSIC_URL = "https://music.youtube.com"


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
    try:
        if get_details:
            if filter_type in ["songs", "videos"]:
                res = ytm.get_song(query)
                video_details = res.get("videoDetails", {})
                vid_id = video_details.get("videoId", query)
                url = f"{BASE_MUSIC_URL}/watch?v={vid_id}"
                return (
                    f"Title: {video_details.get('title')}\n"
                    f"Author: {video_details.get('author')}\n"
                    f"Duration: {video_details.get('lengthSeconds')}s\n"
                    f"Views: {video_details.get('viewCount')}\n"
                    f"Video ID: {vid_id}\n"
                    f"URL: {url}"
                )
            elif filter_type == "albums":
                album = ytm.get_album(query)
                browse_id = album.get("audioPlaylistId", query)
                url = f"{BASE_MUSIC_URL}/playlist?list={browse_id}"
                tracks = album.get("tracks", [])
                track_summary = "\n".join([
                    f"  - {t.get('title')} ({t.get('duration', 'N/A')}) | Link: {BASE_MUSIC_URL}/watch?v={t.get('videoId')}" 
                    for t in tracks[:10] if t.get('videoId')
                ])
                return (
                    f"Album: {album.get('title')}\n"
                    f"Artist: {', '.join([a['name'] for a in album.get('artists', [])])}\n"
                    f"Year: {album.get('year')}\n"
                    f"Track Count: {album.get('trackCount')}\n"
                    f"URL: {url}\n"
                    f"Tracks:\n{track_summary}"
                )
            elif filter_type == "artists":
                artist = ytm.get_artist(query)
                url = f"{BASE_MUSIC_URL}/channel/{query}"
                top_songs = artist.get("songs", {}).get("results", [])
                song_summary = "\n".join([
                    f"  - {s.get('title')} | Link: {BASE_MUSIC_URL}/watch?v={s.get('videoId')}" 
                    for s in top_songs[:5] if s.get('videoId')
                ])
                return (
                    f"Artist: {artist.get('name')}\n"
                    f"Subscribers: {artist.get('subscribers')}\n"
                    f"Description: {artist.get('description', 'N/A')[:200]}...\n"
                    f"URL: {url}\n"
                    f"Top Songs:\n{song_summary}"
                )
            elif filter_type == "playlists":
                playlist = ytm.get_playlist(query, limit=10)
                url = f"{BASE_MUSIC_URL}/playlist?list={query}"
                tracks = playlist.get("tracks", [])
                track_summary = "\n".join([
                    f"  - {t.get('title')} by {', '.join([a['name'] for a in t.get('artists', [])])} | Link: {BASE_MUSIC_URL}/watch?v={t.get('videoId')}" 
                    for t in tracks[:10] if t.get('videoId')
                ])
                return (
                    f"Playlist: {playlist.get('title')}\n"
                    f"Author: {playlist.get('author', {}).get('name')}\n"
                    f"Track Count: {playlist.get('trackCount')}\n"
                    f"URL: {url}\n"
                    f"Tracks:\n{track_summary}"
                )
            else:
                return f"Error: Invalid filter_type '{filter_type}' for detail lookup."

        else:
            # Perform search query
            results = ytm.search(query=query, filter=filter_type, limit=limit)
            if not results:
                return f"No YouTube Music results found for: '{query}'."

            formatted = []
            for i, item in enumerate(results, 1):
                item_type = item.get("resultType", filter_type)
                item_id = item.get("videoId") or item.get("browseId") or item.get("playlistId", "")
                title = item.get("title") or item.get("artist") or item.get("name", "Unknown")
                
                artists = item.get("artists", [])
                artist_str = ", ".join([a["name"] for a in artists]) if artists else "N/A"
                
                # Construct direct URL based on result type
                if item_type in ["song", "video"]:
                    url = f"{BASE_MUSIC_URL}/watch?v={item_id}"
                elif item_type == "album":
                    url = f"{BASE_MUSIC_URL}/playlist?list={item.get('playlistId', item_id)}"
                elif item_type == "artist":
                    url = f"{BASE_MUSIC_URL}/channel/{item_id}"
                elif item_type == "playlist":
                    url = f"{BASE_MUSIC_URL}/playlist?list={item_id}"
                else:
                    url = "N/A"
                
                formatted.append(
                    f"[{i}] Type: {item_type}\n"
                    f"    Title/Name: {title}\n"
                    f"    Artist/Creator: {artist_str}\n"
                    f"    ID: {item_id}\n"
                    f"    URL: {url}"
                )
            return "\n\n".join(formatted)

    except Exception as e:
        return f"Error in ytm_search_and_get: {str(e)}"


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
    try:
        if target == "home":
            home = ytm.get_home(limit=3)
            sections = []
            for shelf in home:
                title = shelf.get("title", "Section")
                contents = [c.get("title", "Item") for c in shelf.get("contents", [])[:3]]
                sections.append(f"• {title}: {', '.join(contents)}")
            return "YouTube Music Home Feed Context:\n" + "\n".join(sections)

        elif target == "charts":
            charts = ytm.get_charts(country="US")
            top_songs = []
            for s in charts.get("songs", {}).get("items", [])[:5]:
                vid = s.get('videoId')
                link_str = f" | Link: {BASE_MUSIC_URL}/watch?v={vid}" if vid else ""
                top_songs.append(f"{s.get('title')} - {', '.join([a['name'] for a in s.get('artists', [])])}{link_str}")
            
            return "Top Trending Songs (US Charts):\n" + "\n".join([f"{i+1}. {song}" for i, song in enumerate(top_songs)])

        elif target == "related":
            if not entity_id:
                return "Error: entity_id (videoId) is required when target='related'."
            
            watch_playlist = ytm.get_watch_playlist(videoId=entity_id, limit=5)
            tracks = watch_playlist.get("tracks", [])
            formatted = []
            for t in tracks[1:]:  # Skip target track
                vid = t.get('videoId')
                url = f"{BASE_MUSIC_URL}/watch?v={vid}" if vid else "N/A"
                formatted.append(f"• {t.get('title')} by {', '.join([a['name'] for a in t.get('artists', [])])}\n  ID: {vid} | URL: {url}")
                
            return f"Related Recommendations for Video ID '{entity_id}':\n" + "\n".join(formatted)

        elif target == "lyrics":
            if not entity_id:
                return "Error: entity_id is required when target='lyrics'."
            
            lyrics_id = entity_id
            track_url = ""
            if len(entity_id) == 11:
                track_url = f"Track URL: {BASE_MUSIC_URL}/watch?v={entity_id}\n"
                watch_playlist = ytm.get_watch_playlist(videoId=entity_id)
                lyrics_id = watch_playlist.get("lyrics")
                if not lyrics_id:
                    return f"No lyrics available for Video ID '{entity_id}'."

            lyrics_data = ytm.get_lyrics(lyrics_id)
            return f"{track_url}Lyrics:\n{lyrics_data.get('lyrics', 'Lyrics unavailable.')}"

        else:
            return f"Error: Unsupported target mode '{target}'."

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