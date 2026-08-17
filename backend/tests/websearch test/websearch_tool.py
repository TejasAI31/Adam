"""Web search tool using the renamed 'ddgs' package, optimized for llama-cpp-python tool calling."""

from ddgs import DDGS


def web_search(query: str, num_results: int = 3) -> str:
    """Performs a web search using the modern 'ddgs' library package.
    
    Args:
        query (str): The search query string.
        num_results (int): Maximum number of search results to return.
        
    Returns:
        str: Formatted string containing titles, URLs, and snippets, or an error description.
    """
    if not isinstance(query, str) or not query.strip():
        return "Error: Search query must be a non-empty string."
    
    try:
        sanitized_query = query.strip()
        sanitized_num = max(1, int(num_results))
    except (ValueError, TypeError):
        sanitized_num = 3

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(sanitized_query, max_results=sanitized_num))
            
        if not results:
            return f"No relevant web search results found for: '{sanitized_query}'."

        formatted_results = []
        for item in results:
            title = item.get("title", "No Title")
            href = item.get("href", "#")
            body = item.get("body", "No description available.")
            formatted_results.append(f"Title: {title}\nURL: {href}\nSnippet: {body}")

        return "\n\n".join(formatted_results)

    except Exception as e:
        return f"Error executing search via ddgs package: {str(e)}"


# JSON Schema for llama-cpp-python / OpenAI-compatible tool calling
WEBSEARCH_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Performs a robust web search to retrieve up-to-date information, facts, or answers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query string."
                    },
                    "num_results": {
                        "type": "integer",
                        "description": "Maximum number of search results to return (default is 3).",
                        "default": 3
                    }
                },
                "required": ["query"]
            }
        }
    }
]

# Mapping dictionary for execution routing in llama-cpp-python
WEBSEARCH_TOOL_MAP = {
    "web_search": web_search
}