"""STAC arama ve odc-stac ile AOI kutusunun pencereli yüklenmesi."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Sequence

import pystac


@dataclass(frozen=True)
class SceneInfo:
    """Bir STAC öğesinin analiz için gereken özeti."""

    item_id: str
    acquired: datetime
    cloud_cover: float | None
    processing_baseline: str | None
    mgrs_tile: str | None


def season_dates(year: int, settings: dict[str, Any], season: str | None = None) -> tuple[date, date]:
    """settings.yaml'daki mevsim penceresinin verilen yıl için başlangıç/bitiş tarihleri."""
    comp = settings["composite"]
    win = comp["windows"][season or comp["season"]]
    start_m, start_d = (int(x) for x in win["start"].split("-"))
    end_m, end_d = (int(x) for x in win["end"].split("-"))
    return date(year, start_m, start_d), date(year, end_m, end_d)


def search_items(
    bbox: Sequence[float],
    start: date,
    end: date,
    settings: dict[str, Any],
    max_cloud: float | None = None,
    client: Any | None = None,
) -> list[pystac.Item]:
    """AOI kutusu (WGS84) ve tarih aralığı için Sentinel-2 L2A öğelerini arar; veri indirmez.

    max_cloud verilirse sahne düzeyinde eo:cloud_cover filtresi uygulanır.
    """
    cfg = settings["stac"]
    if client is None:
        from pystac_client import Client

        client = Client.open(cfg["url"])
    kwargs: dict[str, Any] = {
        "collections": [cfg["collection"]],
        "bbox": list(bbox),
        "datetime": f"{start.isoformat()}/{end.isoformat()}",
    }
    if max_cloud is not None:
        kwargs["query"] = {"eo:cloud_cover": {"lt": max_cloud}}
    return list(client.search(**kwargs).items())


def baseline_key(baseline: str | None) -> tuple[int, ...]:
    """'05.10' → (5, 10); eksik/bozuk değer en düşük sayılır."""
    try:
        return tuple(int(x) for x in str(baseline).split("."))
    except ValueError:
        return (-1,)


def dedupe_items(items: Sequence[pystac.Item]) -> list[pystac.Item]:
    """Aynı çekim (uydu + zaman) ve MGRS karesi için yalnızca en yüksek baseline'lı öğeyi tutar."""
    best: dict[tuple, pystac.Item] = {}
    for it in items:
        p = it.properties
        key = (p.get("platform"), it.datetime, p.get("s2:mgrs_tile"))
        cur = best.get(key)
        if cur is None or baseline_key(p.get("s2:processing_baseline")) > baseline_key(
            cur.properties.get("s2:processing_baseline")
        ):
            best[key] = it
    return sorted(best.values(), key=lambda i: (i.datetime, i.id))


def aoi_geobox(geometry_wgs84: Any, settings: dict[str, Any]):
    """AOI için proje CRS'inde, çözünürlüğe hizalı sabit ızgara (yıllar arasında aynı kalır)."""
    import geopandas as gpd
    from odc.geo.geobox import GeoBox

    g = settings["grid"]
    bounds = gpd.GeoSeries([geometry_wgs84], crs="EPSG:4326").to_crs(g["crs"]).total_bounds
    return GeoBox.from_bbox(tuple(bounds), crs=g["crs"], resolution=g["resolution_m"])


def fine_geobox(geobox: Any, resolution_m: float):
    """Çalışma ızgarasıyla aynı kapsamda, tam bölen çözünürlükte (ör. 20 → 10 m) iç içe ızgara."""
    from affine import Affine
    from odc.geo.geobox import GeoBox

    res = abs(geobox.transform.a)
    factor = res / resolution_m
    if factor < 1 or abs(factor - round(factor)) > 1e-9:
        raise ValueError(f"{resolution_m} m, {res} m ızgaranın tam böleni değil.")
    k = int(round(factor))
    h, w = geobox.shape
    return GeoBox((h * k, w * k), geobox.transform @ Affine.scale(1 / k), geobox.crs)


def load_item(
    item: pystac.Item,
    geobox: Any,
    settings: dict[str, Any],
    bands: Sequence[str] | None = None,
    resampling: dict[str, str] | None = None,
):
    """Tek bir öğenin yalnızca AOI penceresini okur (COG pencereli okuma); (y, x) Dataset döndürür."""
    import odc.stac
    import planetary_computer

    cfg = settings["stac"]
    ds = odc.stac.load(
        [item],
        bands=list(bands or cfg["bands"]),
        geobox=geobox,
        resampling=dict(resampling or cfg["resampling"]),
        groupby="id",
        patch_url=planetary_computer.sign,
    )
    ds = ds.isel(time=0, drop=True)
    info = scene_info(item)
    ds.attrs.update(
        item_id=info.item_id,
        acquired=info.acquired.isoformat(),
        processing_baseline=info.processing_baseline or "",
        mgrs_tile=info.mgrs_tile or "",
        cloud_cover=info.cloud_cover if info.cloud_cover is not None else -1.0,
    )
    return ds


def scene_info(item: pystac.Item) -> SceneInfo:
    """STAC öğesinden tarih, bulut oranı, processing baseline ve MGRS karesini çıkarır."""
    p = item.properties
    return SceneInfo(
        item_id=item.id,
        acquired=item.datetime,
        cloud_cover=p.get("eo:cloud_cover"),
        processing_baseline=p.get("s2:processing_baseline"),
        mgrs_tile=p.get("s2:mgrs_tile"),
    )
