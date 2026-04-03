"""Tests pour publish.py — vérification post-copie."""

import os
import tempfile
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))


def test_publish_copies_correctly():
    """Copie normale : source == destination apres publish."""
    import publish as _pub

    # Setup temp dirs
    tmp_src = tempfile.mktemp(suffix=".js")
    tmp_docs = tempfile.mkdtemp()
    try:
        with open(tmp_src, "w") as f:
            f.write("const X = 1;")

        original_here = _pub.HERE
        original_docs = _pub.DOCS
        original_files = _pub.FILES
        _pub.HERE = os.path.dirname(tmp_src)
        _pub.DOCS = tmp_docs
        _pub.FILES = {os.path.basename(tmp_src): "out.js"}

        _pub.publish()

        dst = os.path.join(tmp_docs, "out.js")
        assert os.path.isfile(dst), "Destination file should exist"
        with open(tmp_src) as a, open(dst) as b:
            assert a.read() == b.read(), "Files should be identical"

    finally:
        _pub.HERE = original_here
        _pub.DOCS = original_docs
        _pub.FILES = original_files
        os.unlink(tmp_src)
        shutil.rmtree(tmp_docs, ignore_errors=True)


def test_publish_detects_corruption():
    """Si la copie est corrompue, publish doit echouer."""
    import filecmp
    import publish as _pub

    tmp_src = tempfile.mktemp(suffix=".js")
    tmp_docs = tempfile.mkdtemp()
    try:
        with open(tmp_src, "w") as f:
            f.write("const GOOD = 1;")

        # Pre-create a different file at destination
        dst = os.path.join(tmp_docs, "out.js")
        with open(dst, "w") as f:
            f.write("const BAD = 999;")

        # Monkey-patch shutil.copy2 to NOT actually copy (simulate failure)
        original_copy = shutil.copy2
        shutil.copy2 = lambda src, dst: None  # no-op

        original_here = _pub.HERE
        original_docs = _pub.DOCS
        original_files = _pub.FILES
        _pub.HERE = os.path.dirname(tmp_src)
        _pub.DOCS = tmp_docs
        _pub.FILES = {os.path.basename(tmp_src): "out.js"}

        try:
            _pub.publish()
            assert False, "Should have called sys.exit(1)"
        except SystemExit as e:
            assert e.code == 1, f"Should exit with code 1, got {e.code}"

    finally:
        shutil.copy2 = original_copy
        _pub.HERE = original_here
        _pub.DOCS = original_docs
        _pub.FILES = original_files
        os.unlink(tmp_src)
        shutil.rmtree(tmp_docs, ignore_errors=True)


if __name__ == "__main__":
    tests = [f for f in dir() if f.startswith("test_")]
    passed = 0
    failed = 0
    for name in sorted(tests):
        try:
            globals()[name]()
            passed += 1
            print(f"  OK  {name}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {name}: {e}")
    print(f"\n{passed} passed, {failed} failed")
