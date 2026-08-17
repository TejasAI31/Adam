"""Browser opening tool module utilizing Python's built-in `webbrowser` library.
Provides multi-link opening, URL validation, and cross-platform default browser dispatch.
"""

import re
import webbrowser
from typing import List, Union

# Regex pattern for validating HTTPS/HTTP URLs
URL_PATTERN = re.compile(
    r"^(https?://)"  # Requires http:// or https://
    r"([a-zA-Z0-9.\-]+)"  # Domain name
    r"(:\d+)?"  # Optional port
    r"(/.*)?$"  # Optional path
)


def open_browser_urls(
    urls: Union[str, List[str]],
    new_window: bool = False
) -> str:
    """Opens one or a list of web links in the system's default web browser.
    
    Args:
        urls: A single URL string OR a list of URL strings to open.
        new_window: If True, attempts to open the links in a new browser window. 
                    If False (default), opens in new tabs when possible.
                    
    Returns:
        str: Status report summarizing opened URLs and any invalid inputs.
    """
    # Normalize input to a list of strings
    if isinstance(urls, str):
        # Handle comma-separated strings if passed by LLM
        url_list = [u.strip() for u in urls.split(",") if u.strip()]
    elif isinstance(urls, list):
        url_list = [str(u).strip() for u in urls if str(u).strip()]
    else:
        return "Error: Invalid input format. Expected a URL string or list of URL strings."

    if not url_list:
        return "Error: No URLs provided to open."

    successful_urls = []
    failed_urls = []

    for raw_url in url_list:
        # Prepend https:// if protocol is missing
        formatted_url = raw_url
        if not formatted_url.startswith(("http://", "https://")):
            formatted_url = f"https://{formatted_url}"

        # Validate URL format
        if not URL_PATTERN.match(formatted_url):
            failed_urls.append(f"{raw_url} (Invalid URL format)")
            continue

        try:
            # Execute browser open command
            if new_window:
                opened = webbrowser.open_new(formatted_url)
            else:
                opened = webbrowser.open_new_tab(formatted_url)

            if opened:
                successful_urls.append(formatted_url)
            else:
                failed_urls.append(f"{formatted_url} (Failed to launch browser)")

        except Exception as e:
            failed_urls.append(f"{formatted_url} (Error: {str(e)})")

    # Construct execution output
    output = []
    if successful_urls:
        output.append("Successfully opened in default browser:")
        output.extend([f"  - {url}" for url in successful_urls])
    
    if failed_urls:
        if output:
            output.append("\nFailed to open:")
        else:
            output.append("Failed to open the following links:")
        output.extend([f"  - {url}" for url in failed_urls])

    return "\n".join(output)


# Minimal-overhead JSON Schema for llama-cpp-python / OpenAI tool calling
BROWSER_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "open_browser_urls",
            "description": "Opens one or multiple web links in the user's default web browser (e.g., YouTube Music links, web search links).",
            "parameters": {
                "type": "object",
                "properties": {
                    "urls": {
                        "type": "array",
                        "items": {
                            "type": "string"
                        },
                        "description": "A list of valid URL strings (or a single URL string) to open in the default browser."
                    },
                    "new_window": {
                        "type": "boolean",
                        "default": False,
                        "description": "Set to True to force opening in a new browser window instead of a new tab."
                    }
                },
                "required": ["urls"]
            }
        }
    }
]

# Mapping dictionary for execution routing
BROWSER_TOOL_MAP = {
    "open_browser_urls": open_browser_urls
}