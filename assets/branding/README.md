# Логотип сайта

`logo-source.jpg` — копия предоставленного исходного рисунка. Оригинальный файл вне проекта не изменяется.

Готовые файлы находятся в `static/`: логотип PNG/WebP в `images/`, favicon ICO (16, 32, 48 px), PNG (16, 32, 48 px), Apple Touch Icon (180 px), Android (192 и 512 px) и `site.webmanifest`.

Для повторного создания файлов нужен Python с Pillow:

```shell
python -m pip install Pillow
python scripts/generate_branding.py
```

Скрипт обрезает только широкие внешние поля; сохраняет белый фон, пропорции и сам рисунок. Логотип в шапке задаётся через `params.navbar.logo` в `hugo.yaml` и одинаков для светлой и тёмной темы. Локальный `layouts/_partials/favicons.html` заменяет ссылки на стандартные значки Hextra. SVG не создаётся: исходник растровый, и преобразование в SVG не добавит детализации.
