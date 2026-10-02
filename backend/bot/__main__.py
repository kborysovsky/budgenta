"""Run one Telegram worker: python -m backend.bot."""
import asyncio
from pathlib import Path
from dotenv import load_dotenv

# Compose supplies environment variables; local development can use root .env.
# Load configuration before importing modules that construct database engines.
load_dotenv(Path(__file__).resolve().parents[2] / '.env')

from backend.bot.worker import main

if __name__ == '__main__':
    asyncio.run(main())
