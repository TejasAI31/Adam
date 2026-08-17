"""Simple interactive script to test the YouTube Music tools directly from the same directory."""

from ytmusic_tools import (
    ytm_search_and_get,
    ytm_get_browse_context,
    YTMUSIC_TOOL_SCHEMAS,
    YTMUSIC_TOOL_MAP,
)


def main():
    print("=== Adam YouTube Music Tools Test ===")
    print("Loaded Schemas:")
    for schema in YTMUSIC_TOOL_SCHEMAS:
        print(f" - {schema['function']['name']}: {schema['function']['description']}")
    print(f"Loaded Dispatcher Map Keys: {list(YTMUSIC_TOOL_MAP.keys())}\n")

    while True:
        try:
            print("-" * 50)
            print("Select a mode to test:")
            print("1. Search Music (songs, videos, albums, artists, playlists)")
            print("2. Get Entity Details (via Video ID, Album ID, etc.)")
            print("3. Browse Context (Home feed, Charts, Related tracks, Lyrics)")
            print("4. Exit")
            
            choice = input("\nEnter choice (1-4): ").strip()
            if choice == "4" or choice.lower() == "exit":
                print("Exiting YouTube Music test. Goodbye!")
                break

            if choice == "1":
                query = input("Enter search query (e.g., 'Starboy'): ").strip()
                if not query:
                    continue
                filter_type = input("Filter type [songs/videos/albums/artists/playlists] (default: songs): ").strip() or "songs"
                
                print(f"\n[Executing ytm_search_and_get(query='{query}', filter_type='{filter_type}')]...\n")
                result = YTMUSIC_TOOL_MAP["ytm_search_and_get"](
                    query=query, 
                    filter_type=filter_type, 
                    limit=3, 
                    get_details=False
                )
                print("--- Output ---")
                print(result)

            elif choice == "2":
                entity_id = input("Enter entity ID (e.g., video ID 'fHI8X4OXluQ' or album ID): ").strip()
                if not entity_id:
                    continue
                filter_type = input("Entity filter type [songs/videos/albums/artists/playlists] (default: songs): ").strip() or "songs"
                
                print(f"\n[Executing ytm_search_and_get(query='{entity_id}', filter_type='{filter_type}', get_details=True)]...\n")
                result = YTMUSIC_TOOL_MAP["ytm_search_and_get"](
                    query=entity_id, 
                    filter_type=filter_type, 
                    get_details=True
                )
                print("--- Output ---")
                print(result)

            elif choice == "3":
                target = input("Target mode [home/charts/related/lyrics] (default: charts): ").strip() or "charts"
                entity_id = None
                if target in ["related", "lyrics"]:
                    entity_id = input(f"Enter videoId/entity_id required for '{target}': ").strip()

                print(f"\n[Executing ytm_get_browse_context(target='{target}', entity_id='{entity_id}')]...\n")
                result = YTMUSIC_TOOL_MAP["ytm_get_browse_context"](
                    target=target, 
                    entity_id=entity_id
                )
                print("--- Output ---")
                print(result)

            else:
                print("Invalid choice. Please enter a number between 1 and 4.")

        except KeyboardInterrupt:
            print("\nExiting...")
            break
        except Exception as e:
            print(f"\nAn error occurred: {e}\n")


if __name__ == "__main__":
    main()