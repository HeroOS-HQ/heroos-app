"""Test-run configuration, applied before any application module is imported.

HEROOS_ENV is required with no default. The suite runs against an explicit
development configuration, independent of the developer's shell.
"""

import os

for _name in [name for name in os.environ if name.startswith("HEROOS_")]:
    del os.environ[_name]
os.environ["HEROOS_ENV"] = "development"
