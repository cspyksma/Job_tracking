APPLICATION_COLUMNS = [
    "RecordID",
    "Company",
    "Role",
    "Location",
    "ReqID / JobID",
    "JobURL",
    "Source",
    "DateFirstSeen",
    "DateApplied",
    "Status",
    "StatusDate",
    "LastEmailDate",
    "RecruiterName",
    "RecruiterEmail",
    "NextStep",
    "FollowUpDue",
    "Notes",
    "EmailThreadLink",
    "LastMessageID",
    "Confidence",
    "MatchedBy",
    "LastDetectedType",
    "TrackingCategory",
    "UserLockStatus",
    "UserLockNotes",
    "UserLockNextStep",
]

EMAIL_LOG_COLUMNS = [
    "MessageID",
    "ThreadID",
    "ReceivedDate",
    "From",
    "Subject",
    "DetectedType",
    "LinkedRecordID",
    "ExtractorNotes",
    "RawSnippet",
]

NEEDS_REVIEW_COLUMNS = [
    "RecordID",
    "Company",
    "Role",
    "Status",
    "Confidence",
    "MatchedBy",
    "LastEmailDate",
    "Notes",
    "LastMessageID",
    "EmailThreadLink",
]

OPPORTUNITY_COLUMNS = [
    "RecordID",
    "Company",
    "Role",
    "LastEmailDate",
    "Status",
    "Confidence",
]

CONFIRMATION_COLUMNS = [
    "RecordID",
    "Company",
    "Role",
    "DateApplied",
    "LastMessageID",
    "LastEmailDate",
]

UPDATE_COLUMNS = [
    "RecordID",
    "Company",
    "Role",
    "LastDetectedType",
    "Status",
    "LastEmailDate",
    "Notes",
]
