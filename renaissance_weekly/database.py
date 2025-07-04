"""Database module for Renaissance Weekly"""

import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Any

from .models import Episode, TranscriptSource
from .config import DB_PATH
from .utils.logging import get_logger

logger = get_logger(__name__)


class PodcastDatabase:
    """Handle all database operations for podcast episodes and transcripts"""
    
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Initialize database tables with migration support"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Check if episodes table exists
                cursor.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='episodes'
                """)
                table_exists = cursor.fetchone() is not None
                
                if table_exists:
                    # Check if we need to migrate the schema
                    cursor.execute("PRAGMA table_info(episodes)")
                    columns = {row[1] for row in cursor.fetchall()}
                    
                    required_columns = {
                        'podcast', 'title', 'published', 'audio_url', 
                        'transcript_url', 'description', 'link', 'duration', 
                        'guid', 'transcript', 'transcript_source', 'summary'
                    }
                    
                    if not required_columns.issubset(columns):
                        logger.warning("Database schema outdated, migrating...")
                        self._migrate_database(conn, columns)
                else:
                    # Create new table
                    self._create_episodes_table(conn)
                
                # Create or update indexes
                self._create_indexes(conn)
                
                conn.commit()
                
        except sqlite3.Error as e:
            logger.error(f"Database initialization error: {e}")
            # If all else fails, backup and recreate
            self._backup_and_recreate()
    
    def _create_episodes_table(self, conn: sqlite3.Connection):
        """Create the episodes table"""
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS episodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                podcast TEXT NOT NULL,
                title TEXT NOT NULL,
                published DATETIME NOT NULL,
                audio_url TEXT,
                transcript_url TEXT,
                description TEXT,
                link TEXT,
                duration TEXT,
                guid TEXT,
                transcript TEXT,
                transcript_source TEXT,
                summary TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(podcast, title, published)
            )
        """)
    
    def _create_indexes(self, conn: sqlite3.Connection):
        """Create database indexes"""
        cursor = conn.cursor()
        
        # Drop existing indexes if they exist (to avoid conflicts)
        cursor.execute("DROP INDEX IF EXISTS idx_episodes_podcast_published")
        cursor.execute("DROP INDEX IF EXISTS idx_episodes_guid")
        
        # Create new indexes
        cursor.execute("""
            CREATE INDEX idx_episodes_podcast_published 
            ON episodes(podcast, published DESC)
        """)
        
        cursor.execute("""
            CREATE INDEX idx_episodes_guid 
            ON episodes(guid)
        """)
    
    def _migrate_database(self, conn: sqlite3.Connection, existing_columns: set):
        """Migrate database to new schema"""
        cursor = conn.cursor()
        
        try:
            # Create a temporary table with the new schema
            cursor.execute("""
                CREATE TABLE episodes_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    podcast TEXT NOT NULL,
                    title TEXT NOT NULL,
                    published DATETIME NOT NULL,
                    audio_url TEXT,
                    transcript_url TEXT,
                    description TEXT,
                    link TEXT,
                    duration TEXT,
                    guid TEXT,
                    transcript TEXT,
                    transcript_source TEXT,
                    summary TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(podcast, title, published)
                )
            """)
            
            # Copy data from old table to new table
            # Only copy columns that exist in both tables
            common_columns = existing_columns.intersection({
                'id', 'podcast', 'title', 'published', 'audio_url', 
                'transcript_url', 'description', 'link', 'duration', 
                'guid', 'transcript', 'transcript_source', 'summary',
                'created_at', 'updated_at'
            })
            
            if common_columns:
                columns_str = ', '.join(common_columns)
                cursor.execute(f"""
                    INSERT INTO episodes_new ({columns_str})
                    SELECT {columns_str} FROM episodes
                """)
            
            # Drop old table and rename new table
            cursor.execute("DROP TABLE episodes")
            cursor.execute("ALTER TABLE episodes_new RENAME TO episodes")
            
            logger.info("✅ Database migration completed successfully")
            
        except sqlite3.Error as e:
            logger.error(f"Migration failed: {e}")
            # Rollback by dropping the temporary table if it exists
            cursor.execute("DROP TABLE IF EXISTS episodes_new")
            raise
    
    def _backup_and_recreate(self):
        """Backup existing database and create a new one"""
        if self.db_path.exists():
            # Create backup
            backup_path = self.db_path.with_suffix('.backup')
            logger.warning(f"Backing up existing database to {backup_path}")
            
            import shutil
            shutil.move(str(self.db_path), str(backup_path))
        
        # Create fresh database
        with sqlite3.connect(self.db_path) as conn:
            self._create_episodes_table(conn)
            self._create_indexes(conn)
            conn.commit()
        
        logger.info("✅ Created fresh database")
    
    def save_episode(self, episode: Episode, transcript: Optional[str] = None, 
                     transcript_source: Optional[TranscriptSource] = None,
                     summary: Optional[str] = None) -> int:
        """Save or update an episode in the database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Convert episode to dict for storage
                episode_data = {
                    'podcast': episode.podcast,
                    'title': episode.title,
                    'published': episode.published.isoformat(),
                    'audio_url': episode.audio_url,
                    'transcript_url': episode.transcript_url,
                    'description': episode.description,
                    'link': episode.link,
                    'duration': episode.duration,
                    'guid': episode.guid,
                    'transcript': transcript,
                    'transcript_source': transcript_source.value if transcript_source else None,
                    'summary': summary,
                    'updated_at': datetime.now().isoformat()
                }
                
                # Try to update existing record first
                cursor.execute("""
                    UPDATE episodes 
                    SET audio_url = ?, transcript_url = ?, description = ?, 
                        link = ?, duration = ?, guid = ?, transcript = ?, 
                        transcript_source = ?, summary = ?, updated_at = ?
                    WHERE podcast = ? AND title = ? AND published = ?
                """, (
                    episode_data['audio_url'], episode_data['transcript_url'],
                    episode_data['description'], episode_data['link'],
                    episode_data['duration'], episode_data['guid'],
                    episode_data['transcript'], episode_data['transcript_source'],
                    episode_data['summary'], episode_data['updated_at'],
                    episode_data['podcast'], episode_data['title'], episode_data['published']
                ))
                
                if cursor.rowcount == 0:
                    # Insert new record
                    cursor.execute("""
                        INSERT INTO episodes (
                            podcast, title, published, audio_url, transcript_url,
                            description, link, duration, guid, transcript,
                            transcript_source, summary
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        episode_data['podcast'], episode_data['title'], episode_data['published'],
                        episode_data['audio_url'], episode_data['transcript_url'],
                        episode_data['description'], episode_data['link'],
                        episode_data['duration'], episode_data['guid'],
                        episode_data['transcript'], episode_data['transcript_source'],
                        episode_data['summary']
                    ))
                
                conn.commit()
                return cursor.lastrowid
                
        except sqlite3.Error as e:
            logger.error(f"Database error saving episode: {e}")
            return -1
    
    def get_transcript(self, episode: Episode) -> Tuple[Optional[str], Optional[TranscriptSource]]:
        """Get cached transcript for an episode"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Try to find by guid first (most reliable)
                if episode.guid:
                    cursor.execute("""
                        SELECT transcript, transcript_source 
                        FROM episodes 
                        WHERE guid = ? AND transcript IS NOT NULL
                    """, (episode.guid,))
                    result = cursor.fetchone()
                    if result:
                        transcript, source_str = result
                        source = TranscriptSource(source_str) if source_str else None
                        return transcript, source
                
                # Fall back to matching by podcast, title, and date
                cursor.execute("""
                    SELECT transcript, transcript_source 
                    FROM episodes 
                    WHERE podcast = ? AND title = ? AND date(published) = date(?)
                    AND transcript IS NOT NULL
                """, (episode.podcast, episode.title, episode.published.isoformat()))
                
                result = cursor.fetchone()
                if result:
                    transcript, source_str = result
                    source = TranscriptSource(source_str) if source_str else None
                    return transcript, source
                
                return None, None
                
        except sqlite3.Error as e:
            logger.error(f"Database error getting transcript: {e}")
            return None, None
    
    def get_episode(self, podcast: str, title: str, published: datetime) -> Optional[Dict]:
        """Get a specific episode from the database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM episodes 
                    WHERE podcast = ? AND title = ? AND date(published) = date(?)
                """, (podcast, title, published.isoformat()))
                
                result = cursor.fetchone()
                if result:
                    columns = [desc[0] for desc in cursor.description]
                    return dict(zip(columns, result))
                
                return None
                
        except sqlite3.Error as e:
            logger.error(f"Database error getting episode: {e}")
            return None
    
    def get_recent_episodes(self, days_back: int = 7) -> List[Dict]:
        """Get recent episodes from the database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM episodes 
                    WHERE published >= datetime('now', '-' || ? || ' days')
                    ORDER BY published DESC
                """, (days_back,))
                
                results = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description]
                
                return [dict(zip(columns, row)) for row in results]
                
        except sqlite3.Error as e:
            logger.error(f"Database error getting recent episodes: {e}")
            return []
    
    def get_episodes_with_summaries(self, days_back: int = 7) -> List[Dict]:
        """Get episodes that have summaries"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM episodes 
                    WHERE published >= datetime('now', '-' || ? || ' days')
                    AND summary IS NOT NULL AND summary != ''
                    ORDER BY published DESC
                """, (days_back,))
                
                results = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description]
                
                return [dict(zip(columns, row)) for row in results]
                
        except sqlite3.Error as e:
            logger.error(f"Database error getting episodes with summaries: {e}")
            return []
    
    def get_episodes_without_transcripts(self, days_back: int = 7) -> List[Dict]:
        """Get episodes that don't have transcripts yet"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM episodes 
                    WHERE published >= datetime('now', '-' || ? || ' days')
                    AND (transcript IS NULL OR transcript = '')
                    ORDER BY published DESC
                """, (days_back,))
                
                results = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description]
                
                return [dict(zip(columns, row)) for row in results]
                
        except sqlite3.Error as e:
            logger.error(f"Database error getting episodes without transcripts: {e}")
            return []
    
    def get_last_episode_dates(self, podcast_names: List[str]) -> Dict[str, Optional[datetime]]:
        """Get the most recent episode date for each podcast"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Create placeholders for IN clause
                placeholders = ','.join(['?' for _ in podcast_names])
                
                cursor.execute(f"""
                    SELECT podcast, MAX(published) as last_published
                    FROM episodes
                    WHERE podcast IN ({placeholders})
                    GROUP BY podcast
                """, podcast_names)
                
                results = cursor.fetchall()
                
                # Convert to dictionary with datetime objects
                last_dates = {}
                for podcast, date_str in results:
                    if date_str:
                        # Parse the ISO format date string
                        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                        # Ensure timezone awareness
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        last_dates[podcast] = dt
                    else:
                        last_dates[podcast] = None
                
                # Add None for podcasts not found in results
                for podcast_name in podcast_names:
                    if podcast_name not in last_dates:
                        last_dates[podcast_name] = None
                
                return last_dates
                
        except sqlite3.Error as e:
            logger.error(f"Database error getting last episode dates: {e}")
            return {name: None for name in podcast_names}
    
    def get_last_episode_info(self, podcast_names: List[str]) -> Dict[str, Optional[Dict[str, Any]]]:
        """Get the most recent episode info (date and title) for each podcast"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Create placeholders for IN clause
                placeholders = ','.join(['?' for _ in podcast_names])
                
                # Use a subquery to get the most recent episode for each podcast
                cursor.execute(f"""
                    SELECT e.podcast, e.published, e.title
                    FROM episodes e
                    INNER JOIN (
                        SELECT podcast, MAX(published) as max_published
                        FROM episodes
                        WHERE podcast IN ({placeholders})
                        GROUP BY podcast
                    ) latest ON e.podcast = latest.podcast AND e.published = latest.max_published
                """, podcast_names)
                
                results = cursor.fetchall()
                
                # Convert to dictionary with episode info
                last_episodes = {}
                for podcast, date_str, title in results:
                    if date_str:
                        # Parse the ISO format date string
                        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                        # Ensure timezone awareness
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        last_episodes[podcast] = {
                            'date': dt,
                            'title': title
                        }
                    else:
                        last_episodes[podcast] = None
                
                # Add None for podcasts not found in results
                for podcast_name in podcast_names:
                    if podcast_name not in last_episodes:
                        last_episodes[podcast_name] = None
                
                return last_episodes
                
        except sqlite3.Error as e:
            logger.error(f"Database error getting last episode info: {e}")
            return {name: None for name in podcast_names}
    
    def clear_old_episodes(self, days_to_keep: int = 30):
        """Clear episodes older than specified days"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    DELETE FROM episodes 
                    WHERE published < datetime('now', '-' || ? || ' days')
                """, (days_to_keep,))
                
                deleted_count = cursor.rowcount
                conn.commit()
                
                if deleted_count > 0:
                    logger.info(f"Cleared {deleted_count} old episodes from database")
                    
        except sqlite3.Error as e:
            logger.error(f"Database error clearing old episodes: {e}")