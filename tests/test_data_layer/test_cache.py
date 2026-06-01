from __future__ import annotations

import pandas as pd

from src.data_layer.cache import DataCache


def test_cache_roundtrip_dataframe(tmp_path) -> None:
    cache = DataCache(cache_dir=tmp_path, ttl_hours=1)
    df = pd.DataFrame({"code": ["000001"], "close": [10.0]})

    cache.set("quotes:000001", df)
    loaded = cache.get("quotes:000001")

    assert loaded is not None
    assert loaded.equals(df)
    assert cache.is_fresh("quotes:000001")

