# Substance Bridge

Двосторонній міст 3ds Max ↔ Substance Painter для автоматизованого PBR-текстурування.
Одна кнопка в Max перевіряє UV, пакує текстури, експортує FBX і відкриває Painter.
Одна кнопка в Painter повертає готові 4K-текстури назад у Max і сама призначає їх матеріалам.

Технічний огляд проєкту (архітектура, повний цикл, система ефектів, стан):
**[awark10.github.io/substance-bridge](https://awark10.github.io/substance-bridge/)**
(також опубліковано як [Claude Artifact](https://claude.ai/artifact/KtDqsejqcHcCQA7Gb3EnyR))

## Структура

| Файл | Роль |
|---|---|
| `Substance_Bridge_Injector.mcr` | MAXScript-плагін для 3ds Max — UI, перевірка UV, запікання, FBX-експорт, автоімпорт |
| `SP_To_Max_Bridge.py` | Python-плагін для Substance Painter — ефекти, автозавантаження, експорт 4K |
| `SB_Weathering.spmsk` | Smart Mask для ефекту ADD WEATHERING |
| `aerial_grass_rock_diff.png` | Текстура трави/каменю для ефекту ADD GROUND DIRT |
| `Run_Substance_Bridge_Installer.ms` | MZP-інсталятор — розкладає файли по потрібних теках 3ds Max / Painter |
| `SubstanceBridge_*i.bmp` / `*a.bmp` | Іконки кнопки на панелі інструментів (legacy формат, колір + альфа-маска) |
| `docs/` | Інструкції з встановлення (UA/EN/RU) і копія overview-сторінки (EN) |

## Встановлення

Див. [`docs/Substance_Bridge_Installation_ENG.txt`](docs/Substance_Bridge_Installation_ENG.txt) або відповідну мовну версію.
Коротко: усі файли з кореня репозиторію запаковуються в один `.mzp`-архів (перейменований `.zip`), який перетягується у вьюпорт 3ds Max.

## Версія

Поточна: v2.7.0 (синхронізовано між `.mcr` та `.py`).
