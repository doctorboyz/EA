#!/usr/bin/env python3
"""
Initialize pairs table from pairs.yaml.

Usage:
    python scripts/init_pairs_db.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.database import load_pairs_into_db


async def main():
    print("Loading pairs from config/pairs.yaml into database...")
    try:
        await load_pairs_into_db()
        print("✓ Pairs loaded successfully")
    except Exception as e:
        print(f"✗ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
