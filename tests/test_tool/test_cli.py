import sys

import pytest

from piimask.config import DEV_HMAC_SECRET
from tool import export as export_module


@pytest.mark.parametrize("secret", ["", DEV_HMAC_SECRET])
def test_cli_refuses_missing_or_dev_secret(monkeypatch, secret):
    monkeypatch.setenv("HMAC_SECRET", secret)
    export_module.get_settings.cache_clear()
    monkeypatch.setattr(sys, "argv", ["tool.export"])
    with pytest.raises(SystemExit) as failure:
        export_module.main()
    export_module.get_settings.cache_clear()
    assert "HMAC_SECRET" in str(failure.value)
