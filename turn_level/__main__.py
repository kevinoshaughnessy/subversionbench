"""`python3 -m turn_level`, so the CLI is never run twice."""

import sys

from .cli import main

sys.exit(main())
