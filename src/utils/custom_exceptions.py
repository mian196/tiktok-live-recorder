class TikTokRecorderError(Exception):
    """Base exception for all TikTok Recorder errors."""

    def __init__(self, message):
        super().__init__(message)


class UserLiveError(TikTokRecorderError):
    """Error related to user live status."""

    def __init__(self, message):
        super().__init__(message)


class IPBlockedByWAF(TikTokRecorderError):
    """Raised when IP is blocked by WAF."""

    def __init__(self, message="IP blocked by WAF"):
        super().__init__(message)


class LiveNotFound(TikTokRecorderError):
    """Raised when a live stream is not found."""


class ArgsParseError(TikTokRecorderError):
    """Raised for argument parsing errors."""


class NetworkError(TikTokRecorderError):
    """Raised for network-related errors."""


class TikRecUnavailableError(TikTokRecorderError):
    """Raised when the tikrec signing service is unreachable or returns an unexpected response."""
