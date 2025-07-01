"""Test data cache system for faster testing cycles"""

import json
import shutil
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

from ..config import BASE_DIR, AUDIO_DIR, SUMMARY_DIR, TRANSCRIPT_DIR
from ..utils.logging import get_logger

logger = get_logger(__name__)


class TestDataCache:
    """Manage test datasets for rapid testing"""
    
    def __init__(self):
        self.datasets_dir = BASE_DIR / "test_datasets"
        self.datasets_dir.mkdir(exist_ok=True)
        
    def save_dataset(self, name: str, limit_episodes: int = 10) -> bool:
        """Save current cache state as a test dataset"""
        dataset_path = self.datasets_dir / name
        
        try:
            # Create dataset directory
            if dataset_path.exists():
                logger.warning(f"Dataset '{name}' already exists, overwriting...")
                shutil.rmtree(dataset_path)
            dataset_path.mkdir(parents=True)
            
            # Copy database with limited episodes
            db_path = BASE_DIR / "data" / "podcast_data.db"
            if db_path.exists():
                self._copy_limited_database(db_path, dataset_path / "podcast_data.db", limit_episodes)
            
            # Copy audio files (limit to most recent)
            audio_files = list(AUDIO_DIR.glob("*.mp3"))[:limit_episodes]
            if audio_files:
                (dataset_path / "audio").mkdir(exist_ok=True)
                for audio_file in audio_files:
                    shutil.copy2(audio_file, dataset_path / "audio" / audio_file.name)
                    logger.info(f"  Saved audio: {audio_file.name}")
            
            # Copy summaries
            summary_files = list(SUMMARY_DIR.glob("*.md"))[:limit_episodes]
            if summary_files:
                (dataset_path / "summaries").mkdir(exist_ok=True)
                for summary_file in summary_files:
                    shutil.copy2(summary_file, dataset_path / "summaries" / summary_file.name)
                    logger.info(f"  Saved summary: {summary_file.name}")
            
            # Save metadata
            metadata = {
                "name": name,
                "created": datetime.now().isoformat(),
                "episodes": limit_episodes,
                "audio_files": len(audio_files),
                "summary_files": len(summary_files)
            }
            
            with open(dataset_path / "metadata.json", 'w') as f:
                json.dump(metadata, f, indent=2)
            
            logger.info(f"✅ Saved test dataset '{name}' with {limit_episodes} episodes")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save dataset: {e}")
            return False
    
    def load_dataset(self, name: str) -> bool:
        """Load a test dataset into the cache"""
        dataset_path = self.datasets_dir / name
        
        if not dataset_path.exists():
            logger.error(f"Dataset '{name}' not found")
            return False
        
        try:
            # Load metadata
            with open(dataset_path / "metadata.json", 'r') as f:
                metadata = json.load(f)
            
            logger.info(f"Loading dataset '{name}' created on {metadata['created']}")
            
            # Copy database
            src_db = dataset_path / "podcast_data.db"
            if src_db.exists():
                dst_db = BASE_DIR / "data" / "podcast_data.db"
                dst_db.parent.mkdir(exist_ok=True)
                shutil.copy2(src_db, dst_db)
                logger.info("  ✅ Loaded database")
            
            # Copy audio files
            src_audio = dataset_path / "audio"
            if src_audio.exists():
                AUDIO_DIR.mkdir(exist_ok=True)
                for audio_file in src_audio.glob("*.mp3"):
                    shutil.copy2(audio_file, AUDIO_DIR / audio_file.name)
                logger.info(f"  ✅ Loaded {len(list(src_audio.glob('*.mp3')))} audio files")
            
            # Copy summaries
            src_summaries = dataset_path / "summaries"
            if src_summaries.exists():
                SUMMARY_DIR.mkdir(exist_ok=True)
                for summary_file in src_summaries.glob("*.md"):
                    shutil.copy2(summary_file, SUMMARY_DIR / summary_file.name)
                logger.info(f"  ✅ Loaded {len(list(src_summaries.glob('*.md')))} summaries")
            
            logger.info(f"✅ Dataset '{name}' loaded successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load dataset: {e}")
            return False
    
    def list_datasets(self) -> List[Dict]:
        """List available test datasets"""
        datasets = []
        
        for dataset_dir in self.datasets_dir.iterdir():
            if dataset_dir.is_dir() and (dataset_dir / "metadata.json").exists():
                with open(dataset_dir / "metadata.json", 'r') as f:
                    metadata = json.load(f)
                metadata['path'] = str(dataset_dir)
                datasets.append(metadata)
        
        return datasets
    
    def _copy_limited_database(self, src_db: Path, dst_db: Path, limit: int):
        """Copy database with limited number of episodes"""
        # Connect to source database
        src_conn = sqlite3.connect(src_db)
        src_conn.row_factory = sqlite3.Row
        
        # Create destination database
        dst_db.parent.mkdir(exist_ok=True)
        dst_conn = sqlite3.connect(dst_db)
        
        try:
            # Copy schema
            schema = src_conn.execute("SELECT sql FROM sqlite_master WHERE type='table'").fetchall()
            for table in schema:
                if table['sql']:
                    dst_conn.execute(table['sql'])
            
            # Copy limited episodes (most recent)
            episodes = src_conn.execute("""
                SELECT * FROM episodes 
                WHERE transcript IS NOT NULL 
                ORDER BY published DESC 
                LIMIT ?
            """, (limit,)).fetchall()
            
            if episodes:
                columns = list(episodes[0].keys())
                placeholders = ','.join(['?' for _ in columns])
                
                for episode in episodes:
                    values = [episode[col] for col in columns]
                    dst_conn.execute(f"INSERT INTO episodes ({','.join(columns)}) VALUES ({placeholders})", values)
            
            dst_conn.commit()
            logger.info(f"  Copied {len(episodes)} episodes to test database")
            
        finally:
            src_conn.close()
            dst_conn.close()