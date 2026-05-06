import os
import json
import locale
from pathlib import Path

class SymbioConfig:
    def __init__(self, cwd: str = "."):
        self.config_file = Path(cwd) / ".symbio" / "config.json"
        
        self.defaults = {
            "model": "gpt-3.5-turbo",
            "api_base": None,
            "temperature": 0.2,
            "language": "en"
        }
        self.settings = self.defaults.copy()
        self.load()

    def load(self):
        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self.settings.update(data)
            except (json.JSONDecodeError, IOError) as e:
                print(f"⚠️ [Config] Failed to load config: {e}")

    def save(self):
        try:
            self.config_file.parent.mkdir(exist_ok=True)
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=2)
        except IOError as e:
            print(f"❌ [Config] Failed to save config: {e}")

    def set(self, key, value):
        self.settings[key] = value
        self.save()

    def get(self, key):
        return self.settings.get(key, self.defaults.get(key))
