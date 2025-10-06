import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    """Configuration class for the Telegram bot."""
    
    # Telegram Bot Configuration
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    
    # OpenAI Configuration
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    OPENAI_ASSISTANT_ID = os.getenv('OPENAI_ASSISTANT_ID')
    
    # LightRAG Configuration
    LIGHTRAG_BASE_URL = os.getenv('LIGHTRAG_BASE_URL')
    LIGHTRAG_API_KEY = os.getenv('LIGHTRAG_API_KEY')
    
    # Bot Configuration
    TRIGGER_KEYWORD = os.getenv('TRIGGER_KEYWORD', 'Екатерина хелп').lower()

    # Admin Configuration
    ADMIN_BOT_TOKEN = os.getenv('ADMIN_BOT_TOKEN')
    ADMIN_CHAT_IDS = [admin_id.strip() for admin_id in os.getenv('ADMIN_CHAT_IDS', '').split(',') if admin_id.strip()]
    CORRECTION_ASSISTANT_ID = os.getenv('CORRECTION_ASSISTANT_ID')

    # Validation Configuration
    VALIDATION_ASSISTANT_ID = os.getenv('VALIDATION_ASSISTANT_ID')
    
    @classmethod
    def validate(cls, include_admin=False):
        """Validate that all required environment variables are set."""
        required_vars = [
            'TELEGRAM_BOT_TOKEN',
            'OPENAI_API_KEY',
            'OPENAI_ASSISTANT_ID',
            'LIGHTRAG_BASE_URL',
            'LIGHTRAG_API_KEY'
        ]

        # Add admin variables if admin features are required
        if include_admin:
            admin_vars = [
                'ADMIN_BOT_TOKEN',
                'ADMIN_CHAT_IDS',
                'CORRECTION_ASSISTANT_ID'
            ]
            required_vars.extend(admin_vars)

        missing_vars = []
        for var in required_vars:
            if not getattr(cls, var):
                missing_vars.append(var)

        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

        return True

    @classmethod
    def has_admin_config(cls):
        """Check if admin configuration is available."""
        return bool(cls.ADMIN_BOT_TOKEN and cls.ADMIN_CHAT_IDS)

    @classmethod
    def has_correction_assistant(cls):
        """Check if correction assistant is configured."""
        return bool(cls.CORRECTION_ASSISTANT_ID)

    @classmethod
    def has_validation_assistant(cls):
        """Check if validation assistant is configured."""
        return bool(cls.VALIDATION_ASSISTANT_ID)

    @classmethod
    def validate_admin_config(cls):
        """Validate admin configuration if admin features are being used."""
        if not cls.has_admin_config():
            raise ValueError("Admin features require ADMIN_BOT_TOKEN and ADMIN_CHAT_IDS to be configured")
        return True

    @classmethod
    def is_admin(cls, user_id: int) -> bool:
        """Check if user ID is in the admin list."""
        return str(user_id) in cls.ADMIN_CHAT_IDS