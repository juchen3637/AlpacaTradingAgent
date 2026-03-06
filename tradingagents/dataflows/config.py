# -------------------------------- config.py -----------------------
import tradingagents.default_config as default_config
from typing import Dict, Optional
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Use default config but allow it to be overridden
_config: Optional[Dict] = None
DATA_DIR: Optional[str] = None


def initialize_config():
    """Initialize the configuration with default values."""
    global _config, DATA_DIR
    if _config is None:
        _config = default_config.DEFAULT_CONFIG.copy()
        DATA_DIR = _config["data_dir"]


def set_config(config: Dict):
    """Update the configuration with custom values."""
    global _config, DATA_DIR
    if _config is None:
        _config = default_config.DEFAULT_CONFIG.copy()
    _config.update(config)
    DATA_DIR = _config["data_dir"]


def get_config() -> Dict:
    """Get the current configuration."""
    if _config is None:
        initialize_config()
    return _config.copy()


def get_api_key(key_name: str, env_var_name: str) -> str:
    """Get API key from environment variables or config."""
    # First check environment variables
    api_key = os.getenv(env_var_name)
    
    # If not found, check config
    if api_key is None and _config is not None and key_name in _config:
        api_key = _config[key_name]
    
    return api_key


def get_openai_api_key() -> str:
    """Get OpenAI API key from environment variables or config."""
    return get_api_key("openai_api_key", "OPENAI_API_KEY")


def get_anthropic_api_key() -> str:
    """Get Anthropic API key from environment variables or config."""
    return get_api_key("anthropic_api_key", "ANTHROPIC_API_KEY")


def get_finnhub_api_key() -> str:
    """Get Finnhub API key from environment variables or config."""
    return get_api_key("finnhub_api_key", "FINNHUB_API_KEY")


def get_alpaca_api_key() -> str:
    """Get Alpaca API key from environment variables or config."""
    return get_api_key("alpaca_api_key", "ALPACA_API_KEY")


def get_alpaca_secret_key() -> str:
    """Get Alpaca secret key from environment variables or config."""
    return get_api_key("alpaca_secret_key", "ALPACA_SECRET_KEY")


def get_alpaca_use_paper() -> str:
    """Get Alpaca paper trading flag from environment variables or config."""
    return get_api_key("alpaca_use_paper", "ALPACA_USE_PAPER")


def get_fred_api_key() -> str:
    """Get FRED API key from environment variables or config."""
    return get_api_key("fred_api_key", "FRED_API_KEY")


# Initialize with default config
initialize_config()
