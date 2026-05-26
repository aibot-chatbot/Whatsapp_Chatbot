import re


def clean_ai_reply(reply: str) -> str:
    if not reply:
        return ""

    text = str(reply)

    # Remove markdown bold/italic markers
    text = text.replace("**", "")
    text = text.replace("__", "")

    # Remove markdown headings like #, ##, ###
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)

    # Convert markdown bullets to clean bullets
    text = re.sub(r"(?m)^\s*[-*]\s+", "• ", text)

    # Remove extra spaces before line breaks
    text = re.sub(r"[ \t]+\n", "\n", text)

    # Reduce too many blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()