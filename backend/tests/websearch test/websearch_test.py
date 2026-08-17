"""Simple interactive script to test the web search tool directly from the same directory."""

from websearch_tool import web_search, WEBSEARCH_TOOL_SCHEMAS, WEBSEARCH_TOOL_MAP

def main():
    print("=== Adam Web Search Tool Test ===")
    print(f"Loaded Schema: {WEBSEARCH_TOOL_SCHEMAS[0]['function']['name']}")
    print(f"Loaded Map Keys: {list(WEBSEARCH_TOOL_MAP.keys())}\n")
    
    while True:
        try:
            query = input("Enter search query (or type 'exit' to quit): ").strip()
            if not query or query.lower() == 'exit':
                print("Exiting search test. Goodbye!")
                break
            
            print(f"\nSearching for: '{query}'...\n")
            
            # Execute via the tool map using the dispatcher pattern
            result = WEBSEARCH_TOOL_MAP["web_search"](query=query, num_results=10)
            
            print("--- Search Results ---")
            print(result)
            print("-" * 40 + "\n")
            
        except KeyboardInterrupt:
            print("\nExiting...")
            break
        except Exception as e:
            print(f"An error occurred: {e}\n")

if __name__ == "__main__":
    main()