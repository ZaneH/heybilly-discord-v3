import re


def find_wake_word_start(wake_words, line):
    normalized_line = line.lower()
    normalized_line = re.sub(r'[^a-zA-Z ]', '', normalized_line)

    wake_word_positions = [normalized_line.find(
        wake_word) for wake_word in wake_words if wake_word in normalized_line]
    if not wake_word_positions:
        return -1

    return min(pos for pos in wake_word_positions if pos >= 0)
