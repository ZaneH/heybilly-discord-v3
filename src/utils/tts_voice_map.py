TTS_VOICE_MAP = {
    "google.en-AU-Neural2-B": "F • AU Banjo",
    "google.en-AU-Neural2-D": "M • AU Charlie",
    "google.en-GB-Neural2-B": "M • UK Teddy",
    "google.en-GB-Wavenet-C": "F • UK Samantha",
    "google.en-IN-Neural2-A": "F • IN Amara",
    "google.en-IN-Neural2-B": "M • IN Sajan",
    "google.en-US-Journey-F": "F • US Olivia",
    "google.en-US-Neural2-H": "F • US Alex",
    "google.en-US-Standard-I": "M • US Billy",
}


def get_voice_name(voice):
    return TTS_VOICE_MAP.get(voice, f"Unrecognized identifier: {voice})")
