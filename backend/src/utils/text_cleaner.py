"""Text preprocessing and sanitization utilities for TTS audio pipeline."""

import re

# Update 2: Complete TTSTextCleaner implementation
class TTSTextCleaner:
    """Rigorous text cleaner to transform structured LLM Markdown output into plain readable text

    suitable for Text-to-Speech engines.
    """

    # Pre-compiled regular expressions for speed
    _URL_PATTERN = re.compile(r"https?://\S+|www\.\S+")
    _CODE_BLOCK_PATTERN = re.compile(r"```[\s\S]*?```")
    _INLINE_CODE_PATTERN = re.compile(r"`([^`]+)`")
    _MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\([^)]+\)")
    _TABLE_PATTERN = re.compile(r"\|.*\|")
    _TABLE_HEADER_SEP = re.compile(r"\|?\s*[-:]+[-|\s:]*")

    # Strip headers, markdown symbols, and remaining stray hash tags
    _HEADER_PATTERN = re.compile(r"#+")
    _LIST_BULLET_PATTERN = re.compile(r"^\s*[-*+]\s+|\s*\d+\.\s+", re.MULTILINE)
    _EMPHASIS_PATTERN = re.compile(r"(\*\*|__|\*|_|~~)(.*?)\1")

    # Brackets, parentheses, and structural formatting marks
    _BRACKET_PATTERN = re.compile(r"[\(\)\[\]\{\}<>]")

    # Colons and semicolons
    _COLON_SEMICOLON_PATTERN = re.compile(r"[:;]")

    # Filter special characters while preserving speech punctuation (. , ! ? ' " -)
    _SPECIAL_CHARS_PATTERN = re.compile(r"[^\w\s.,!?'\-\"\n]")

    _MULTIPLE_SPACES = re.compile(r"[ \t]+")
    _MULTIPLE_NEWLINES = re.compile(r"\n{2,}")

    # Standard replacements for common symbols to natural spoken language
    _SYMBOL_MAP = {
        "&": " and ",
        "@": " at ",
        "%": " percent ",
        "$": " dollars ",
        "€": " euros ",
        "£": " pounds ",
        "=": " equals ",
        "+": " plus ",
        "/": " or ",
    }

    @classmethod
    def clean_for_tts(cls, text: str) -> str:
        """Sanitizes LLM raw response into plain text for speech synthesis.

        :param text: Raw output text from LLM.
        :return: Cleaned plain text without Markdown structures or unreadable symbols.
        """
        if not text:
            return ""

        # 1. Remove code blocks entirely or strip fence markers
        text = cls._CODE_BLOCK_PATTERN.sub("", text)
        text = cls._INLINE_CODE_PATTERN.sub(r"\1", text)

        # 2. Strip Markdown tables completely
        text = cls._TABLE_HEADER_SEP.sub("", text)
        lines = [
            line
            for line in text.splitlines()
            if not cls._TABLE_PATTERN.match(line)
        ]
        text = "\n".join(lines)

        # 3. Handle Markdown links (keep link label, discard URL)
        text = cls._MARKDOWN_LINK_PATTERN.sub(r"\1", text)

        # 4. Strip bare URLs
        text = cls._URL_PATTERN.sub("", text)

        # 5. Strip all '#' header markers and bullet list indicators
        text = cls._HEADER_PATTERN.sub("", text)
        text = cls._LIST_BULLET_PATTERN.sub("", text)

        # 6. Strip bold, italic, underline, and strikethrough styling
        text = cls._EMPHASIS_PATTERN.sub(r"\2", text)

        # 7. Strip brackets and parentheses entirely
        text = cls._BRACKET_PATTERN.sub("", text)

        # 8. Replace all ':' and ';' with ','
        text = cls._COLON_SEMICOLON_PATTERN.sub(",", text)

        # 9. Convert math/common symbols to spoken equivalents
        for symbol, word in cls._SYMBOL_MAP.items():
            text = text.replace(symbol, word)

        # 10. Remove obscure special characters
        text = cls._SPECIAL_CHARS_PATTERN.sub("", text)

        # 11. Normalize whitespace and replace line breaks with soft pauses
        text = cls._MULTIPLE_SPACES.sub(" ", text)
        text = cls._MULTIPLE_NEWLINES.sub(". ", text)

        return text.strip()