# -*- coding: utf-8 -*-

from logger import Logger

ACCOUNTS = \
	[
		{"name": u"Fotos Aurora", "config_file": "/usr/local/onenasdrive-d/.lcrc.maurora", "local_path": "/DataVolume/shares/Public/Shared Pictures/OneDrive/maurora", "remote_path": u"Imágenes/Álbum de cámara"},
		{"name": u"Fotos Miguel", "config_file": "/usr/local/onenasdrive-d/.lcrc.masantiago", "local_path": "/DataVolume/shares/Public/Shared Pictures/OneDrive/masantiago", "remote_path": u"Fotos/Álbum de cámara"}
	]

EXCLUDE = [".*[<>?\*:\"\|]+.*"]
EXCLUDE += "\.DS_Store|Icon.|\.AppleDouble|\.LSOverride|\._.*|\.Spotlight-V100|\.Trashes".split("|")
EXCLUDE += ".*~|\.lock".split("|")
EXCLUDE += [".wdmc"]
EXCLUDE = "^(" + "|".join(EXCLUDE) + ")$"

NUM_OF_WORKERS = 2
NUM_OF_SCANNERS = 4
WORKER_SLEEP_INTERVAL = 3 # seconds
PULL_INTERVAL = 3600 # seconds
MAX_WORKER_DURATION = 1800 # seconds

LOG_PATH = "/var/log/onenasdrive-d.log"
log = Logger(LOG_PATH, Logger.INFO)
