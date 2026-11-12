"""Known issues found while testing (see docs/TESTING.md, section "Hallazgos").

Each test describes the DESIRED behavior and is marked xfail(strict=True):
- today it fails, which is expected and keeps the suite green;
- once the issue is fixed it will pass, and strict mode turns that into a
  failure so whoever fixes it removes the marker.
"""
