from enum import Enum

class Role(str, Enum):
    ADMIN = "admin"
    ANALYST = "analyst"
    VIEWER = "viewer"

class RunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

class ReviewStatus(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"

# Canonical display order; shared-pool tie-breaks favour the earlier venue.
VENUE_ORDER = ("大剧场", "黑匣子", "实验厅")
