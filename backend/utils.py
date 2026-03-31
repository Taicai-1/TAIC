import os
import logging
from datetime import datetime

class Logger:
    """Centralized logging configuration"""
    
    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)
        
        # Create formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)
        
        # File handler for production
        if os.getenv("ENVIRONMENT") == "production":
            file_handler = logging.FileHandler('app.log')
            file_handler.setLevel(logging.INFO)
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)
    
    def info(self, message: str):
        self.logger.info(message)
    
    def error(self, message: str):
        self.logger.error(message)
    
    def warning(self, message: str):
        self.logger.warning(message)
    
    def debug(self, message: str):
        self.logger.debug(message)

# Event tracking for analytics
class EventTracker:
    """Track user events for analytics"""
    
    def __init__(self):
        self.logger = Logger("events")
    
    def track_user_action(self, user_id: int, action: str, metadata: dict = None):
        """Track user action"""
        event = {
            "timestamp": datetime.utcnow().isoformat(),
            "user_id": user_id,
            "action": action,
            "metadata": metadata or {}
        }
        self.logger.info(f"USER_ACTION: {event}")
    
    def track_document_upload(self, user_id: int, filename: str, file_size: int):
        """Track document upload"""
        self.track_user_action(user_id, "document_upload", {
            "filename": filename,
            "file_size": file_size
        })
    
    def track_question_asked(self, user_id: int, question: str, response_time: float):
        """Track question asked"""
        self.track_user_action(user_id, "question_asked", {
            "question_length": len(question),
            "response_time": response_time
        })

# Global instances
logger = Logger("app")
event_tracker = EventTracker()
