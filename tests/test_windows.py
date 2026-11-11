import sys

import pytest

from compass.windows import decrypt_keys, encrypt_keys, set_capture_protection


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DPAPI requires a Windows account")
def test_windows_dpapi_roundtrip():
    plain = '{"google":"test-key-秘密","deepgram":"other-test-key"}'
    encrypted = encrypt_keys(plain)
    assert "test-key" not in encrypted
    assert decrypt_keys(encrypted) == plain


@pytest.mark.skipif(sys.platform == "win32", reason="Non-Windows behavior")
def test_non_windows_does_not_claim_capture_protection():
    ok, reason = set_capture_protection(0, True)
    assert not ok
    assert "Windows" in reason
    with pytest.raises(RuntimeError, match="DPAPI"):
        encrypt_keys("example")
