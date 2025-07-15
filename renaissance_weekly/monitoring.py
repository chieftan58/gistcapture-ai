"""
Monitoring and alerting system for Renaissance Weekly.
Tracks failures, success rates, and sends alerts when thresholds are breached.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from collections import defaultdict
import json
import os
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class FailureRecord:
    """Record of a failure event"""
    timestamp: datetime
    component: str  # e.g., "audio_download", "transcript_fetch", "summarization"
    podcast: str
    episode_title: str
    error_type: str
    error_message: str
    retry_count: int = 0
    resolved: bool = False
    mode: str = 'test'  # 'test' or 'full' - tracks which mode the failure occurred in


@dataclass
class ComponentStats:
    """Statistics for a component"""
    total_attempts: int = 0
    successful: int = 0
    failed: int = 0
    last_failure: Optional[datetime] = None
    consecutive_failures: int = 0
    
    @property
    def success_rate(self) -> float:
        if self.total_attempts == 0:
            return 1.0
        return self.successful / self.total_attempts


class SystemMonitor:
    """Monitor system health and track failures"""
    
    def __init__(self, data_dir: str = "monitoring_data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        
        # In-memory tracking - NOW MODE-AWARE
        self.failures: List[FailureRecord] = []
        # Stats separated by mode: {mode: {component: ComponentStats}}
        self.mode_component_stats: Dict[str, Dict[str, ComponentStats]] = {
            'test': defaultdict(ComponentStats),
            'full': defaultdict(ComponentStats)
        }
        # Podcast stats by mode: {mode: {podcast: {component: ComponentStats}}}
        self.mode_podcast_stats: Dict[str, Dict[str, Dict[str, ComponentStats]]] = {
            'test': defaultdict(lambda: defaultdict(ComponentStats)),
            'full': defaultdict(lambda: defaultdict(ComponentStats))
        }
        
        # Legacy stats for backward compatibility (will be removed in migration)
        self.component_stats: Dict[str, ComponentStats] = defaultdict(ComponentStats)
        self.podcast_stats: Dict[str, Dict[str, ComponentStats]] = defaultdict(lambda: defaultdict(ComponentStats))
        
        # Load persisted data
        self._load_state()
        
        # Alert thresholds
        self.thresholds = {
            'consecutive_failures': 3,  # Alert after 3 consecutive failures
            'success_rate': 0.8,        # Alert if success rate drops below 80%
            'total_failures_24h': 10,   # Alert if more than 10 failures in 24 hours
        }
    
    def record_success(self, component: str, podcast: str = "system", mode: str = 'test'):
        """Record a successful operation"""
        # Update mode-specific stats
        mode_stats = self.mode_component_stats[mode][component]
        mode_stats.total_attempts += 1
        mode_stats.successful += 1
        mode_stats.consecutive_failures = 0
        
        mode_podcast_stats = self.mode_podcast_stats[mode][podcast][component]
        mode_podcast_stats.total_attempts += 1
        mode_podcast_stats.successful += 1
        mode_podcast_stats.consecutive_failures = 0
        
        # Also update legacy stats for backward compatibility
        stats = self.component_stats[component]
        stats.total_attempts += 1
        stats.successful += 1
        stats.consecutive_failures = 0
        
        podcast_stats = self.podcast_stats[podcast][component]
        podcast_stats.total_attempts += 1
        podcast_stats.successful += 1
        podcast_stats.consecutive_failures = 0
        
        self._save_state()
    
    def record_failure(self, component: str, podcast: str, episode_title: str, 
                      error_type: str, error_message: str, retry_count: int = 0, mode: str = 'test'):
        """Record a failure event"""
        failure = FailureRecord(
            timestamp=datetime.now(),
            component=component,
            podcast=podcast,
            episode_title=episode_title,
            error_type=error_type,
            error_message=error_message,
            retry_count=retry_count,
            mode=mode
        )
        
        self.failures.append(failure)
        
        # Update mode-specific stats
        mode_stats = self.mode_component_stats[mode][component]
        mode_stats.total_attempts += 1
        mode_stats.failed += 1
        mode_stats.consecutive_failures += 1
        mode_stats.last_failure = datetime.now()
        
        mode_podcast_stats = self.mode_podcast_stats[mode][podcast][component]
        mode_podcast_stats.total_attempts += 1
        mode_podcast_stats.failed += 1
        mode_podcast_stats.consecutive_failures += 1
        mode_podcast_stats.last_failure = datetime.now()
        
        # Also update legacy stats for backward compatibility
        stats = self.component_stats[component]
        stats.total_attempts += 1
        stats.failed += 1
        stats.consecutive_failures += 1
        stats.last_failure = datetime.now()
        
        podcast_stats = self.podcast_stats[podcast][component]
        podcast_stats.total_attempts += 1
        podcast_stats.failed += 1
        podcast_stats.consecutive_failures += 1
        podcast_stats.last_failure = datetime.now()
        
        # Check if we should alert (using mode-specific stats)
        self._check_alerts(component, podcast, mode)
        
        self._save_state()
        
        logger.error(f"FAILURE RECORDED - Component: {component}, Podcast: {podcast}, "
                    f"Episode: {episode_title}, Error: {error_type} - {error_message}")
    
    def get_recent_failures(self, hours: int = 24) -> List[FailureRecord]:
        """Get failures from the last N hours"""
        cutoff = datetime.now() - timedelta(hours=hours)
        return [f for f in self.failures if f.timestamp > cutoff]
    
    def get_failure_summary(self, mode: Optional[str] = None) -> Dict:
        """Get a summary of system health, optionally filtered by mode"""
        recent_failures = self.get_recent_failures(24)
        if mode:
            recent_failures = [f for f in recent_failures if f.mode == mode]
        
        summary = {
            'overall_health': self._calculate_health_score(mode),
            'total_failures_24h': len(recent_failures),
            'mode': mode or 'all',
            'component_stats': {},
            'component_stats_by_mode': {'test': {}, 'full': {}},
            'problematic_podcasts': [],
            'recent_errors': []
        }
        
        # Mode-specific component statistics
        for mode_name in ['test', 'full']:
            for component, stats in self.mode_component_stats[mode_name].items():
                if stats.total_attempts > 0:  # Only include components with attempts
                    summary['component_stats_by_mode'][mode_name][component] = {
                        'success_rate': f"{stats.success_rate:.1%}",
                        'total_attempts': stats.total_attempts,
                        'consecutive_failures': stats.consecutive_failures,
                        'last_failure': stats.last_failure.isoformat() if stats.last_failure else None
                    }
        
        # Legacy combined stats (for backward compatibility)
        stats_to_show = self.mode_component_stats[mode] if mode else self.component_stats
        for component, stats in stats_to_show.items():
            if stats.total_attempts > 0:
                summary['component_stats'][component] = {
                    'success_rate': f"{stats.success_rate:.1%}",
                    'total_attempts': stats.total_attempts,
                    'consecutive_failures': stats.consecutive_failures,
                    'last_failure': stats.last_failure.isoformat() if stats.last_failure else None
                }
        
        # Find problematic podcasts
        for podcast, components in self.podcast_stats.items():
            total_failures = sum(s.failed for s in components.values())
            if total_failures > 5:  # Arbitrary threshold
                summary['problematic_podcasts'].append({
                    'podcast': podcast,
                    'total_failures': total_failures,
                    'components': list(components.keys())
                })
        
        # Recent errors (last 5)
        for failure in sorted(recent_failures, key=lambda f: f.timestamp, reverse=True)[:5]:
            summary['recent_errors'].append({
                'timestamp': failure.timestamp.isoformat(),
                'component': failure.component,
                'podcast': failure.podcast,
                'error': f"{failure.error_type}: {failure.error_message[:100]}..."
            })
        
        return summary
    
    def _calculate_health_score(self, mode: Optional[str] = None) -> str:
        """Calculate overall system health score"""
        # Simple scoring based on recent failures and success rates
        recent_failures = self.get_recent_failures(24)
        if mode:
            recent_failures = [f for f in recent_failures if f.mode == mode]
        
        stats_to_check = self.mode_component_stats[mode] if mode else self.component_stats
        if not stats_to_check:
            return "⚪ No Data"
        
        recent_failure_count = len(recent_failures)
        avg_success_rate = sum(s.success_rate for s in stats_to_check.values() if s.total_attempts > 0) / max(len([s for s in stats_to_check.values() if s.total_attempts > 0]), 1)
        
        if recent_failure_count < 5 and avg_success_rate > 0.9:
            return "🟢 Healthy"
        elif recent_failure_count < 10 and avg_success_rate > 0.7:
            return "🟡 Warning"
        else:
            return "🔴 Critical"
    
    def _check_alerts(self, component: str, podcast: str, mode: str = 'test'):
        """Check if we should send alerts based on thresholds"""
        # Skip alerts for transcript_fetch - it's expected to fail often since many sources don't have transcripts
        if component == 'transcript_fetch':
            return
            
        stats = self.mode_component_stats[mode][component]
        
        alerts = []
        
        # Check consecutive failures
        if stats.consecutive_failures >= self.thresholds['consecutive_failures']:
            alerts.append(f"Component '{component}' has failed {stats.consecutive_failures} times in a row")
        
        # Check success rate
        if stats.total_attempts > 10 and stats.success_rate < self.thresholds['success_rate']:
            alerts.append(f"Component '{component}' success rate is {stats.success_rate:.1%}")
        
        # Check total failures in 24h
        recent_failures = len(self.get_recent_failures(24))
        if recent_failures > self.thresholds['total_failures_24h']:
            alerts.append(f"System has {recent_failures} failures in the last 24 hours")
        
        # Log alerts (in production, these would be sent via email/slack/etc)
        for alert in alerts:
            logger.critical(f"🚨 ALERT: {alert}")
    
    def _save_state(self):
        """Persist monitoring data to disk"""
        try:
            # Save failures
            failures_data = [
                {
                    'timestamp': f.timestamp.isoformat(),
                    'component': f.component,
                    'podcast': f.podcast,
                    'episode_title': f.episode_title,
                    'error_type': f.error_type,
                    'error_message': f.error_message,
                    'retry_count': f.retry_count,
                    'resolved': f.resolved,
                    'mode': getattr(f, 'mode', 'test')  # Default to 'test' for backward compatibility
                }
                for f in self.failures[-1000:]  # Keep last 1000 failures
            ]
            
            with open(self.data_dir / 'failures.json', 'w') as f:
                json.dump(failures_data, f, indent=2)
            
            # Save stats with mode separation
            stats_data = {
                'component_stats': {
                    comp: {
                        'total_attempts': stats.total_attempts,
                        'successful': stats.successful,
                        'failed': stats.failed,
                        'last_failure': stats.last_failure.isoformat() if stats.last_failure else None,
                        'consecutive_failures': stats.consecutive_failures
                    }
                    for comp, stats in self.component_stats.items()
                },
                'mode_component_stats': {
                    mode: {
                        comp: {
                            'total_attempts': stats.total_attempts,
                            'successful': stats.successful,
                            'failed': stats.failed,
                            'last_failure': stats.last_failure.isoformat() if stats.last_failure else None,
                            'consecutive_failures': stats.consecutive_failures
                        }
                        for comp, stats in mode_stats.items()
                    }
                    for mode, mode_stats in self.mode_component_stats.items()
                }
            }
            
            with open(self.data_dir / 'stats.json', 'w') as f:
                json.dump(stats_data, f, indent=2)
                
        except Exception as e:
            logger.error(f"Failed to save monitoring state: {e}")
    
    def _load_state(self):
        """Load persisted monitoring data"""
        try:
            # Load failures
            failures_file = self.data_dir / 'failures.json'
            if failures_file.exists():
                with open(failures_file) as f:
                    failures_data = json.load(f)
                    
                for f_data in failures_data:
                    self.failures.append(FailureRecord(
                        timestamp=datetime.fromisoformat(f_data['timestamp']),
                        component=f_data['component'],
                        podcast=f_data['podcast'],
                        episode_title=f_data['episode_title'],
                        error_type=f_data['error_type'],
                        error_message=f_data['error_message'],
                        retry_count=f_data.get('retry_count', 0),
                        resolved=f_data.get('resolved', False),
                        mode=f_data.get('mode', 'test')  # Default to 'test' for backward compatibility
                    ))
            
            # Load stats
            stats_file = self.data_dir / 'stats.json'
            if stats_file.exists():
                with open(stats_file) as f:
                    stats_data = json.load(f)
                    
                # Load legacy stats
                for comp, stats in stats_data.get('component_stats', {}).items():
                    self.component_stats[comp] = ComponentStats(
                        total_attempts=stats['total_attempts'],
                        successful=stats['successful'],
                        failed=stats['failed'],
                        last_failure=datetime.fromisoformat(stats['last_failure']) if stats['last_failure'] else None,
                        consecutive_failures=stats['consecutive_failures']
                    )
                
                # Load mode-specific stats
                for mode, mode_stats in stats_data.get('mode_component_stats', {}).items():
                    if mode in self.mode_component_stats:
                        for comp, stats in mode_stats.items():
                            self.mode_component_stats[mode][comp] = ComponentStats(
                                total_attempts=stats['total_attempts'],
                                successful=stats['successful'],
                                failed=stats['failed'],
                                last_failure=datetime.fromisoformat(stats['last_failure']) if stats['last_failure'] else None,
                                consecutive_failures=stats['consecutive_failures']
                            )
                    
        except Exception as e:
            logger.error(f"Failed to load monitoring state: {e}")


# Global monitor instance
monitor = SystemMonitor()