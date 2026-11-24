"""stac.py arama testleri (ağa çıkmaz; sahte istemci kullanır)."""

from datetime import date, datetime, timezone

import pystac

from changewatch.config import load_settings
from changewatch.stac import scene_info, search_items, season_dates


def _item(item_id: str, props: dict) -> pystac.Item:
    return pystac.Item(
        id=item_id,
        geometry=None,
        bbox=None,
        datetime=datetime(2022, 7, 10, 8, 30, tzinfo=timezone.utc),
        properties=props,
    )


class FakeSearch:
    def __init__(self, items):
        self._items = items

    def items(self):
        return iter(self._items)


class FakeClient:
    def __init__(self, items):
        self.items = items
        self.kwargs = None

    def search(self, **kwargs):
        self.kwargs = kwargs
        return FakeSearch(self.items)


def test_season_dates_default_summer():
    assert season_dates(2021, load_settings()) == (date(2021, 7, 1), date(2021, 9, 15))


def test_season_dates_spring():
    assert season_dates(2021, load_settings(), "spring") == (date(2021, 5, 1), date(2021, 6, 30))


def test_search_items_builds_query():
    c = FakeClient([_item("a", {})])
    out = search_items((32.6, 39.7, 32.8, 39.9), date(2022, 7, 1), date(2022, 9, 15),
                       load_settings(), max_cloud=30, client=c)
    assert [i.id for i in out] == ["a"]
    assert c.kwargs["collections"] == ["sentinel-2-l2a"]
    assert c.kwargs["datetime"] == "2022-07-01/2022-09-15"
    assert c.kwargs["query"] == {"eo:cloud_cover": {"lt": 30}}


def test_search_items_without_cloud_filter():
    c = FakeClient([])
    search_items((0, 0, 1, 1), date(2020, 1, 1), date(2020, 1, 2), load_settings(), client=c)
    assert "query" not in c.kwargs


def test_scene_info_reads_properties():
    info = scene_info(_item("x", {"eo:cloud_cover": 12.5, "s2:processing_baseline": "04.00",
                                  "s2:mgrs_tile": "36SVK"}))
    assert (info.cloud_cover, info.processing_baseline, info.mgrs_tile) == (12.5, "04.00", "36SVK")


def test_scene_info_missing_baseline_is_none():
    assert scene_info(_item("y", {})).processing_baseline is None


# ---- kopya ayıklama ve ızgara

from changewatch.stac import aoi_geobox, baseline_key, dedupe_items  # noqa: E402


def _dup(item_id, pb, platform="Sentinel-2B", tile="36TVK", day=5):
    it = _item(item_id, {"s2:processing_baseline": pb, "platform": platform, "s2:mgrs_tile": tile})
    it.datetime = datetime(2022, 7, day, 8, 36, 9, tzinfo=timezone.utc)
    return it


def test_baseline_key_numeric_order():
    assert baseline_key("05.10") > baseline_key("05.09") > baseline_key("04.00") > baseline_key("02.12")
    assert baseline_key("10.00") > baseline_key("05.12")  # metin sıralaması değil
    assert baseline_key(None) < baseline_key("00.01")


def test_dedupe_keeps_highest_baseline():
    out = dedupe_items([_dup("eski", "04.00"), _dup("yeni", "05.10"), _dup("baska_gun", "04.00", day=10)])
    assert [i.id for i in out] == ["yeni", "baska_gun"]


def test_dedupe_keeps_different_tiles_and_platforms():
    out = dedupe_items([_dup("a", "05.10", tile="36TVK"), _dup("b", "05.10", tile="36SVJ"),
                        _dup("c", "05.10", platform="Sentinel-2A")])
    assert len(out) == 3


def test_aoi_geobox_grid_aligned():
    from shapely.geometry import box

    gb = aoi_geobox(box(32.68, 39.79, 32.77, 39.86), load_settings())
    t = gb.transform
    assert (t.a, -t.e) == (20, 20)
    assert t.c % 20 == 0 and t.f % 20 == 0  # yıllar arasında aynı piksel ızgarası
    assert 350 < gb.shape[0] < 450 and 350 < gb.shape[1] < 450  # ~7.8 km / 20 m
