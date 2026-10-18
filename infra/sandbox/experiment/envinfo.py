"""Record the image's interpreter and package versions (copied into every run's environment manifest)."""
import importlib.metadata as m
import json
import platform
import sys

json.dump({"python": sys.version, "platform": platform.platform(),
           "packages": sorted(f"{d.metadata['Name']}=={d.version}" for d in m.distributions())},
          open("/opt/rp/environment.json", "w"), indent=1)
