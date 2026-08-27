from pathlib import Path
from common.publish_vault import VaultPublisher

publisher = VaultPublisher(Path('/home/ubuntu/webdav/steven_vault'))
publisher.generate_daily_index('0826')
