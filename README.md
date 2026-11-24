# TR-ChangeWatch

Ankara'daki seçili bölgelerde Sentinel-2 L2A ile yapılaşma ve arazi örtüsü değişimini kanıtıyla ve güven düzeyiyle haritalayan değişim izleme sistemi. Kapsam ve mimari: [PROJECT_SPEC.md](PROJECT_SPEC.md).

> Geliştirme sürüyor (Faz 0).

## Kurulum

```bash
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
changewatch --help
```

Ham veri önbelleği `config/settings.yaml` içindeki `paths.cache_dir` klasörüne yazılır.
