import logging
from queue import Queue
from tempfile import NamedTemporaryFile
import io
import threading
import time
import re
from typing import List
import wave
import asyncio

from discord.sinks.core import Filters, Sink, default_filters
from faster_whisper import WhisperModel
import speech_recognition as sr

audio_model = WhisperModel("medium.en", device="cpu", compute_type="float32")

logger = logging.getLogger(__name__)


class Speaker:
    """
    A class to store the audio data and transcription for each user.
    """

    def __init__(self, user, data):
        self.user = user
        self.data = [data]

        current_time = time.time()
        self.last_word = current_time
        self.last_phrase = current_time

        self.word_timeout = 0

        self.phrase = ""

        self.empty_bytes_counter = 0
        self.new_bytes = 1


class WhisperSink(Sink):
    """A sink for discord that takes audio in a voice channel and transcribes it for each user.

    Uses faster whisper for transcription. can be swapped out for other audio transcription libraries pretty easily.

    :param transcript_queue: The queue to send the transcription output to
    :param filters: Some discord thing I'm not sure about
    :param data_length: The amount of data to save when user is silent but their mic is still active
    :param quiet_phrase_timeout: A larger timeout for when the transcription has detected the user is in mid sentence
    :param mid_sentence_multiplier: A smaller timout when the transcription has detected the user has finished a sentence
    :param no_data_multiplier: If the user has stopped talking on discord completely (Their icon is no longer green), reduce both timeouts by a percantage to improve inference time
    :param max_phrase_timeout: Send out the current transcription after x seconds if the user continues to talk for a long period
    :param min_phrase_length: Minimum length of transcription to reduce noise
    :param max_speakers: The amount of users to transcribe when all speakers are talking at once.
    """

    def __init__(
        self,
        transcript_queue: asyncio.Queue,
        loop: asyncio.AbstractEventLoop,
        *,
        filters=None,
        data_length=50000,
        quiet_phrase_timeout=1,
        mid_sentence_multiplier=1.8,
        no_data_multiplier=0.75,
        max_phrase_timeout=30,
        min_phrase_length=3,
        max_speakers=-1
    ):
        self.queue = transcript_queue
        self.loop = loop

        if filters is None:
            filters = default_filters
        self.filters = filters
        Filters.__init__(self, **self.filters)

        self.data_length = data_length
        self.quiet_phrase_timeout = quiet_phrase_timeout
        self.mid_sentence_multiplier = mid_sentence_multiplier
        self.no_data_multiplier = no_data_multiplier
        self.max_phrase_timeout = max_phrase_timeout
        self.min_phrase_length = min_phrase_length
        self.max_speakers = max_speakers

        self.vc = None
        self.audio_data = {}
        self.running = True
        self.speakers: List[Speaker] = []
        self.temp_file = NamedTemporaryFile().name
        self.voice_queue = Queue()

    def start_voice_thread(self):
        def thread_exception_hook(args):
            logger.debug(
                f"""Exception in voice thread: {args}
Likely disconnected while listening.""")

        logger.debug(
            f"Starting whisper sink thread for guild {self.vc.channel.guild.id}.")
        self.voice_thread = threading.Thread(
            target=self.insert_voice, args=(), daemon=True)
        threading.excepthook = thread_exception_hook
        self.voice_thread.start()

    def stop_voice_thread(self):
        self.running = False
        try:
            self.voice_thread.join()
        except Exception as e:
            logger.error(f"Unexpected error during thread join: {e}")
        finally:
            logger.debug(
                f"A sink thread was stopped for guild {self.vc.channel.guild.id}.")

    def is_valid_phrase(self, speaker_phrase, result):
        logger.debug(
            f"Waiting for final phrase: {speaker_phrase} != {result}")
        return speaker_phrase != result

    def transcribe_audio(self, temp_file):
        try:
            # The whisper model
            segments, info = audio_model.transcribe(
                temp_file,
                beam_size=10,
                best_of=3,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=250),
                no_speech_threshold=0.6,

            )
            segments = list(segments)
            result = ""
            for segment in segments:
                result += segment.text

            return result
        except Exception as e:
            logger.error(f"Error transcribing audio: {e}")
            return ""

    def transcribe(self, speaker: Speaker):
        audio_data = sr.AudioData(
            bytes().join(speaker.data),
            self.vc.decoder.SAMPLING_RATE,
            self.vc.decoder.SAMPLE_SIZE // self.vc.decoder.CHANNELS,
        )

        wav_data = io.BytesIO(audio_data.get_wav_data())

        with open(self.temp_file, "wb") as file:
            wave_writer = wave.open(file, "wb")
            wave_writer.setnchannels(self.vc.decoder.CHANNELS)
            wave_writer.setsampwidth(
                self.vc.decoder.SAMPLE_SIZE // self.vc.decoder.CHANNELS)
            wave_writer.setframerate(self.vc.decoder.SAMPLING_RATE)
            wave_writer.writeframes(wav_data.getvalue())
            wave_writer.close()

        transcription = self.transcribe_audio(self.temp_file)
        if self.is_valid_phrase(speaker.phrase, transcription):
            speaker.empty_bytes_counter = 0
            speaker.word_timeout = self.quiet_phrase_timeout
            if re.search(r"\s*\.{2,}$", transcription) or not re.search(r"[.!?]$", transcription):
                speaker.word_timeout *= self.mid_sentence_multiplier
            speaker.phrase = transcription
            speaker.last_word = time.time()
        elif speaker.empty_bytes_counter > 5:
            speaker.data = speaker.data[:-speaker.new_bytes]
        else:
            speaker.empty_bytes_counter += 1

    def insert_voice(self):
        while self.running:
            try:
                # Process the voice_queue
                while not self.voice_queue.empty():
                    item = self.voice_queue.get()

                    # Find or create a speaker
                    speaker = next(
                        (s for s in self.speakers if s.user == item[0]), None)
                    if speaker:
                        speaker.data.append(item[1])
                        speaker.new_bytes += 1
                    elif self.max_speakers < 0 or len(self.speakers) <= self.max_speakers:
                        self.speakers.append(Speaker(item[0], item[1]))

                # Transcribe audio for each speaker
                for speaker in self.speakers:
                    if speaker.new_bytes > 0:
                        self.transcribe(speaker)
                        speaker.new_bytes = 0
                        word_timeout = speaker.word_timeout
                    else:
                        # No data coming in from discord, reduces word_timeout for faster inference
                        word_timeout = speaker.word_timeout * self.no_data_multiplier

                    current_time = time.time()

                    if len(speaker.phrase) >= self.min_phrase_length:
                        # If the user stops saying anything new or has been speaking too long.
                        logger.debug(
                            f"[time, word timeout]: [{time.time()}, {word_timeout}]")
                        if (
                            current_time - speaker.last_word > word_timeout
                            or current_time - speaker.last_phrase > self.max_phrase_timeout
                        ):
                            self.loop.call_soon_threadsafe(self.queue.put_nowait, {
                                                           "user": speaker.user, "result": speaker.phrase})

                            self.speakers.remove(speaker)
                    elif current_time > self.quiet_phrase_timeout * 2:
                        # Reset Remove the speaker if no valid phrase detected after set period of time
                        self.speakers.remove(speaker)

                # Loops with no wait time is bad
                time.sleep(0.45)
            except Exception as e:
                logger.error(f"Error in insert_voice: {e}")

    @Filters.container
    def write(self, data, user):
        """Gets audio data from discord for each user talking"""
        # Discord will send empty bytes from when the user stopped talking to when the user starts to talk again.
        # Its only the first the first data that grows massive and its only silent audio, so its trimmed.

        data_len = len(data)
        if data_len > self.data_length:
            data = data[-self.data_length:]

        # Send bytes to be transcribed
        self.voice_queue.put_nowait([user, data])

    def close(self):
        logger.debug("Closing whisper sink.")
        self.running = False
        self.queue.put_nowait(None)
        super().cleanup()