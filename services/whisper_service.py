"""
OpenAI Whisper service for voice message transcription.
Handles Telegram voice file download and OpenAI Whisper API integration.
"""

import logging
import os
import tempfile
import aiofiles
from pathlib import Path
from typing import Optional, Union
from openai import AsyncOpenAI
from telegram import Voice, Audio, VideoNote, Document

from config import Config

logger = logging.getLogger(__name__)

class WhisperService:
    """Service for voice transcription using OpenAI Whisper API."""

    def __init__(self):
        """Initialize the Whisper service."""
        if not Config.OPENAI_API_KEY:
            logger.warning("⚠️ OpenAI API key not configured - Whisper service will not function")
            self.client = None
        else:
            self.client = AsyncOpenAI(api_key=Config.OPENAI_API_KEY)
            logger.info("🎤 WhisperService initialized successfully")

        # Supported audio formats for Whisper
        self.supported_formats = {
            'mp3', 'mp4', 'mpeg', 'mpga', 'm4a', 'wav', 'webm', 'ogg', 'flac'
        }

        # Maximum file size for Whisper API (25MB)
        self.max_file_size = 25 * 1024 * 1024  # 25MB

    async def transcribe_voice(self, voice_file: Union[Voice, Audio, VideoNote, Document],
                              bot_context, language: str = "ru") -> Optional[str]:
        """
        Transcribe voice message using OpenAI Whisper API.

        Args:
            voice_file: Telegram voice/audio file object
            bot_context: Telegram bot context for file download
            language: Language code for transcription (default: "ru" for Russian)

        Returns:
            Transcribed text if successful, None otherwise
        """
        if not self.client:
            logger.error("❌ WhisperService not initialized - missing OpenAI API key")
            return None

        temp_file_path = None
        try:
            logger.info("🎤 Starting voice transcription...")
            logger.info(f"   📄 File type: {type(voice_file).__name__}")

            # Get file information
            file_info = await self._get_file_info(voice_file, bot_context)
            if not file_info:
                logger.error("❌ Failed to get file information")
                return None

            file_id, file_size, file_extension = file_info

            # Validate file size
            if file_size and file_size > self.max_file_size:
                logger.error(f"❌ File too large: {file_size} bytes (max: {self.max_file_size})")
                return None

            # Download file to temporary location
            logger.info("📥 Downloading voice file...")
            temp_file_path = await self._download_voice_file(file_id, bot_context, file_extension)

            if not temp_file_path:
                logger.error("❌ Failed to download voice file")
                return None

            # Verify downloaded file
            actual_size = os.path.getsize(temp_file_path)
            logger.info(f"   📊 Downloaded file size: {actual_size} bytes")

            # Transcribe using Whisper API
            logger.info("🔤 Sending to Whisper API for transcription...")
            transcribed_text = await self._transcribe_with_whisper(temp_file_path, language)

            if transcribed_text:
                logger.info("✅ Voice transcription completed successfully")
                logger.info(f"   📝 Transcribed text length: {len(transcribed_text)} chars")
                logger.info(f"   📄 Preview: {transcribed_text[:100]}{'...' if len(transcribed_text) > 100 else ''}")
                return transcribed_text
            else:
                logger.error("❌ Whisper API returned no transcription")
                return None

        except Exception as e:
            logger.error(f"❌ Error during voice transcription: {e}")
            return None

        finally:
            # Clean up temporary file
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.unlink(temp_file_path)
                    logger.debug(f"🗑️ Cleaned up temporary file: {temp_file_path}")
                except Exception as cleanup_error:
                    logger.warning(f"⚠️ Failed to clean up temporary file: {cleanup_error}")

    async def _get_file_info(self, voice_file: Union[Voice, Audio, VideoNote, Document],
                           bot_context) -> Optional[tuple]:
        """
        Extract file information from Telegram file object.

        Args:
            voice_file: Telegram file object
            bot_context: Telegram bot context

        Returns:
            Tuple of (file_id, file_size, file_extension) or None if failed
        """
        try:
            if isinstance(voice_file, Voice):
                file_id = voice_file.file_id
                file_size = getattr(voice_file, 'file_size', None)
                file_extension = 'ogg'  # Telegram voice messages are usually OGG

            elif isinstance(voice_file, Audio):
                file_id = voice_file.file_id
                file_size = getattr(voice_file, 'file_size', None)
                # Try to get extension from mime_type or file_name
                if hasattr(voice_file, 'mime_type') and voice_file.mime_type:
                    ext_map = {
                        'audio/mpeg': 'mp3',
                        'audio/mp4': 'm4a',
                        'audio/wav': 'wav',
                        'audio/ogg': 'ogg',
                        'audio/flac': 'flac'
                    }
                    file_extension = ext_map.get(voice_file.mime_type, 'mp3')
                else:
                    file_extension = 'mp3'

            elif isinstance(voice_file, VideoNote):
                file_id = voice_file.file_id
                file_size = getattr(voice_file, 'file_size', None)
                file_extension = 'mp4'  # Video notes are usually MP4

            elif isinstance(voice_file, Document):
                file_id = voice_file.file_id
                file_size = getattr(voice_file, 'file_size', None)
                # Try to get extension from file name
                if hasattr(voice_file, 'file_name') and voice_file.file_name:
                    file_extension = Path(voice_file.file_name).suffix.lstrip('.').lower()
                    if file_extension not in self.supported_formats:
                        logger.warning(f"⚠️ Unsupported file format: {file_extension}")
                        file_extension = 'mp3'  # Default fallback
                else:
                    file_extension = 'mp3'
            else:
                logger.error(f"❌ Unsupported file type: {type(voice_file)}")
                return None

            logger.debug(f"📋 File info: ID={file_id[:10]}..., size={file_size}, ext={file_extension}")
            return file_id, file_size, file_extension

        except Exception as e:
            logger.error(f"❌ Error extracting file info: {e}")
            return None

    async def _download_voice_file(self, file_id: str, bot_context, file_extension: str) -> Optional[str]:
        """
        Download voice file from Telegram to temporary location.

        Args:
            file_id: Telegram file ID
            bot_context: Telegram bot context
            file_extension: File extension for the temporary file

        Returns:
            Path to downloaded temporary file or None if failed
        """
        try:
            # Get file object from Telegram
            telegram_file = await bot_context.bot.get_file(file_id)

            if not telegram_file.file_path:
                logger.error("❌ No file path available from Telegram")
                return None

            # Create temporary file
            with tempfile.NamedTemporaryFile(suffix=f".{file_extension}", delete=False) as temp_file:
                temp_file_path = temp_file.name

            logger.debug(f"📁 Created temporary file: {temp_file_path}")

            # Download file to temporary location
            await telegram_file.download_to_drive(temp_file_path)

            # Verify file was downloaded
            if not os.path.exists(temp_file_path):
                logger.error("❌ File was not downloaded successfully")
                return None

            file_size = os.path.getsize(temp_file_path)
            if file_size == 0:
                logger.error("❌ Downloaded file is empty")
                os.unlink(temp_file_path)
                return None

            logger.debug(f"✅ Voice file downloaded successfully: {file_size} bytes")
            return temp_file_path

        except Exception as e:
            logger.error(f"❌ Error downloading voice file: {e}")
            return None

    async def _transcribe_with_whisper(self, file_path: str, language: str) -> Optional[str]:
        """
        Transcribe audio file using OpenAI Whisper API.

        Args:
            file_path: Path to the audio file
            language: Language code for transcription

        Returns:
            Transcribed text or None if failed
        """
        try:
            logger.debug(f"🔤 Transcribing file: {file_path}")
            logger.debug(f"🌐 Language: {language}")

            # Open and transcribe file
            async with aiofiles.open(file_path, 'rb') as audio_file:
                file_content = await audio_file.read()

            # Create a file-like object for the API
            import io
            audio_buffer = io.BytesIO(file_content)
            audio_buffer.name = os.path.basename(file_path)

            # Call Whisper API
            transcript_response = await self.client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_buffer,
                language=language,
                response_format="text"
            )

            # Extract transcribed text
            if hasattr(transcript_response, 'text'):
                transcribed_text = transcript_response.text.strip()
            elif isinstance(transcript_response, str):
                transcribed_text = transcript_response.strip()
            else:
                logger.error(f"❌ Unexpected response format: {type(transcript_response)}")
                return None

            if not transcribed_text:
                logger.warning("⚠️ Whisper API returned empty transcription")
                return None

            logger.debug(f"✅ Transcription successful: {len(transcribed_text)} chars")
            return transcribed_text

        except Exception as e:
            logger.error(f"❌ Error calling Whisper API: {e}")
            # Log additional details for debugging
            if hasattr(e, 'response'):
                logger.error(f"   📄 API Response: {e.response}")
            return None

    def is_supported_format(self, file_extension: str) -> bool:
        """
        Check if file format is supported by Whisper.

        Args:
            file_extension: File extension (without dot)

        Returns:
            True if supported, False otherwise
        """
        return file_extension.lower() in self.supported_formats

    def get_supported_formats(self) -> set:
        """
        Get set of supported audio formats.

        Returns:
            Set of supported file extensions
        """
        return self.supported_formats.copy()

    async def transcribe_file_path(self, file_path: str, language: str = "ru") -> Optional[str]:
        """
        Transcribe audio file directly from file path (for testing/utility).

        Args:
            file_path: Path to audio file
            language: Language code for transcription

        Returns:
            Transcribed text or None if failed
        """
        if not self.client:
            logger.error("❌ WhisperService not initialized - missing OpenAI API key")
            return None

        if not os.path.exists(file_path):
            logger.error(f"❌ File not found: {file_path}")
            return None

        file_size = os.path.getsize(file_path)
        if file_size > self.max_file_size:
            logger.error(f"❌ File too large: {file_size} bytes (max: {self.max_file_size})")
            return None

        logger.info(f"🎤 Transcribing file: {file_path}")
        return await self._transcribe_with_whisper(file_path, language)

# Global shared instance
_whisper_service = None

def get_whisper_service() -> WhisperService:
    """Get the global whisper service instance."""
    global _whisper_service
    if _whisper_service is None:
        _whisper_service = WhisperService()
    return _whisper_service