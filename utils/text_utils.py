"""
Text utilities for processing responses.
"""

import re


def strip_markdown(text: str) -> str:
    """
    Remove markdown formatting from text to ensure clean Telegram messages.

    Args:
        text: Input text that may contain markdown formatting

    Returns:
        Clean text without markdown formatting
    """
    if not text:
        return text

    # Remove bold formatting: **text** or __text__ → text
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'__(.*?)__', r'\1', text)

    # Remove italic formatting: *text* or _text_ → text
    text = re.sub(r'\*(.*?)\*', r'\1', text)
    text = re.sub(r'_(.*?)_', r'\1', text)

    # Remove inline code: `code` → code
    text = re.sub(r'`(.*?)`', r'\1', text)

    # Remove code blocks: ```code``` → code
    text = re.sub(r'```.*?\n(.*?)\n```', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'```(.*?)```', r'\1', text, flags=re.DOTALL)

    # Remove headers: # Header → Header, ## Header → Header, etc.
    text = re.sub(r'^#{1,6}\s*(.*?)$', r'\1', text, flags=re.MULTILINE)

    # Remove links: [text](url) → text
    text = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', text)

    # Remove horizontal rules: --- or *** → (empty)
    text = re.sub(r'^[-*]{3,}\s*$', '', text, flags=re.MULTILINE)

    # Remove strikethrough: ~~text~~ → text
    text = re.sub(r'~~(.*?)~~', r'\1', text)

    # Remove blockquotes: > text → text
    text = re.sub(r'^>\s*(.*?)$', r'\1', text, flags=re.MULTILINE)

    # Clean up multiple newlines
    text = re.sub(r'\n{3,}', '\n\n', text)

    # Clean up extra whitespace
    text = re.sub(r'[ \t]+', ' ', text)
    text = text.strip()

    return text