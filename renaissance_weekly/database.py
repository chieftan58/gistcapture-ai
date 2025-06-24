"""Database operations for Renaissance Weekly"""

import sqlite3
import json
from pathlib import Path
from typing import Optional, List, Dict
from datetime import datetime

from .models import Episode, TranscriptSource
from .config import DB_PATH


class PodcastDatabase:
    """SQLite database for tracking podcasts and episodes"""
    
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """Initialize database schema"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Podcast feeds table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS podcast_feeds (
                podcast_name TEXT PRIMARY KEY,
                working_feeds TEXT,  -- JSON array of working feed URLs
                transcript_sources TEXT,  -- JSON object of transcript sources
                last_checked TIMESTAMP,
                last_success TIMESTAMP
            )
        """)
        
        # Episodes table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS episodes (
                guid TEXT PRIMARY KEY,
                podcast_name TEXT,
                title TEXT,
                published TIMESTAMP,
                audio_url TEXT,
                transcript_url TEXT,
                transcript_source TEXT,
                transcript_text TEXT,
                summary TEXT,
                processed BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (podcast_name) REFERENCES podcast_feeds(podcast_name)
            )
        """)
        
        # Feed health monitoring
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS feed_health (
                url TEXT PRIMARY KEY,
                podcast_name TEXT,
                status TEXT,  -- 'working', 'failing', 'dead'
                last_success TIMESTAMP,
                last_failure TIMESTAMP,
                failure_count INTEGER DEFAULT 0,
                error_message TEXT
            )
        """)
        
        conn.commit()
        conn.close()
    
    def get_cached_transcript(self, episode: Episode) -> Optional[str]:
        """Get cached transcript if available"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT transcript_text FROM episodes WHERE guid = ?",
            (episode.guid,)
        )
        result = cursor.fetchone()
        conn.close()
        
        return result[0] if result and result[0] else None
    
    def save_episode(self, episode: Episode, transcript: Optional[str] = None):
        """Save episode to database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO episodes 
            (guid, podcast_name, title, published, audio_url, transcript_url, 
             transcript_source, transcript_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            episode.guid,
            episode.podcast,
            episode.title,
            episode.published,
            episode.audio_url,
            episode.transcript_url,
            episode.transcript_source.value if episode.transcript_source else None,
            transcript
        ))
        
        conn.commit()
        conn.close()