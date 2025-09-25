import logging

from .main import main as main_main

logger = logging.getLogger(__name__)

def main():
    main_main()

if __name__ == "__main__":
    main()
