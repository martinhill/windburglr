# Windscraper package

import logging

logger = logging.getLogger(__name__)
formatter = logging.Formatter('%(asctime)s - %(levelname)-6s - %(name)s - %(message)s')
handler = logging.StreamHandler()
handler.setFormatter(formatter)
logger.addHandler(handler)
