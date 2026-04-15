import sys
import os
from unittest.mock import MagicMock

# Add backend to path so imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Mock web3 so tests run without it installed
web3_mock = MagicMock()
web3_mock.Web3.HTTPProvider = MagicMock()
web3_mock.Web3.to_checksum_address = lambda x: x
web3_mock.middleware = MagicMock()
web3_mock.middleware.ExtraDataToPOAMiddleware = MagicMock()
sys.modules.setdefault("web3", web3_mock)
sys.modules.setdefault("web3.middleware", web3_mock.middleware)
