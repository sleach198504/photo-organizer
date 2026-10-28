"""Test suite. Run from the project folder:

    venv\\Scripts\\python.exe -m unittest discover -s tests -t . -v

Importing this package first points PHOTO_ORGANIZER_HOME at a throwaway folder, so no
test can ever read or change a real library, config or database.
"""
import atexit
import os
import shutil
import tempfile

_home = tempfile.mkdtemp(prefix="photo-organizer-test-home-")
os.environ["PHOTO_ORGANIZER_HOME"] = _home
atexit.register(shutil.rmtree, _home, ignore_errors=True)
