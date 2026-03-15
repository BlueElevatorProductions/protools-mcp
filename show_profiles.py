"""Show profile loader — reads per-show JSON config files."""

import json
import os
from typing import Optional, Dict


class ShowProfileLoader:
    """Loads and matches show profiles from the show_profiles/ directory."""

    def __init__(self, profiles_dir: Optional[str] = None):
        if profiles_dir is None:
            profiles_dir = os.path.join(os.path.dirname(__file__), "show_profiles")
        self._profiles_dir = profiles_dir
        self._profiles: Dict[str, dict] = {}
        self._loaded = False

    def _load_profiles(self):
        """Scan the profiles directory and load all JSON files."""
        if self._loaded:
            return
        if os.path.exists(self._profiles_dir):
            for filename in os.listdir(self._profiles_dir):
                if filename.endswith(".json"):
                    filepath = os.path.join(self._profiles_dir, filename)
                    try:
                        with open(filepath, "r") as f:
                            profile = json.load(f)
                            if "show_id" in profile:
                                self._profiles[profile["show_id"]] = profile
                    except (json.JSONDecodeError, IOError):
                        pass
        self._loaded = True

    def get_profile(self, show_id: Optional[str] = None) -> Optional[dict]:
        """Get a profile by show_id. Returns None if not found."""
        self._load_profiles()
        if show_id:
            return self._profiles.get(show_id)
        return None

    def match_session(self, session_name: str) -> Optional[dict]:
        """Find a profile whose session_name_prefix matches the session name."""
        self._load_profiles()
        for profile in self._profiles.values():
            prefix = profile.get("session_name_prefix", "")
            if prefix and session_name.startswith(prefix):
                return profile
        return None

    def list_profiles(self) -> list:
        """Return all loaded profiles."""
        self._load_profiles()
        return list(self._profiles.values())
