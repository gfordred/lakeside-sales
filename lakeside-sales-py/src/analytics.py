"""
Analytics tracking for user interactions
"""
import streamlit as st
from datetime import datetime
from pathlib import Path
import json


class Analytics:
    """Simple analytics tracker for property views and interactions"""
    
    def __init__(self, log_file: str = "data/cache/analytics.json"):
        self.log_file = Path(log_file)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        
    def track_event(self, event_type: str, data: dict = None):
        """
        Track an analytics event
        
        Args:
            event_type: Type of event (view, search, filter, contact)
            data: Additional event data
        """
        event = {
            "timestamp": datetime.now().isoformat(),
            "type": event_type,
            "data": data or {},
            "session_id": self._get_session_id()
        }
        
        # Append to log file
        try:
            events = self._load_events()
            events.append(event)
            
            # Keep only last 1000 events
            if len(events) > 1000:
                events = events[-1000:]
            
            with open(self.log_file, 'w') as f:
                json.dump(events, f, indent=2)
        except Exception as e:
            # Fail silently - analytics shouldn't break the app
            pass
    
    def _get_session_id(self) -> str:
        """Get or create session ID"""
        if 'session_id' not in st.session_state:
            import uuid
            st.session_state['session_id'] = str(uuid.uuid4())
        return st.session_state['session_id']
    
    def _load_events(self) -> list:
        """Load existing events"""
        if self.log_file.exists():
            try:
                with open(self.log_file, 'r') as f:
                    return json.load(f)
            except:
                return []
        return []
    
    def get_stats(self) -> dict:
        """Get analytics statistics"""
        events = self._load_events()
        
        if not events:
            return {
                "total_views": 0,
                "total_searches": 0,
                "total_contacts": 0,
                "popular_properties": []
            }
        
        # Count event types
        views = [e for e in events if e['type'] == 'property_view']
        searches = [e for e in events if e['type'] == 'search']
        contacts = [e for e in events if e['type'] == 'contact']
        
        # Find popular properties
        property_counts = {}
        for view in views:
            prop_id = view.get('data', {}).get('property_id')
            if prop_id:
                property_counts[prop_id] = property_counts.get(prop_id, 0) + 1
        
        popular = sorted(property_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        
        return {
            "total_views": len(views),
            "total_searches": len(searches),
            "total_contacts": len(contacts),
            "popular_properties": popular
        }
