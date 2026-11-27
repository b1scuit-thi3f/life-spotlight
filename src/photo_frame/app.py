"""Application factory.

Routes are defined under ``photo_frame.api``. Processing lives in ``photo_frame.core``.
"""

from photo_frame.api.app import createApp

__all__ = ["createApp"]
