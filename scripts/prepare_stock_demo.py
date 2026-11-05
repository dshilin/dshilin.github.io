"""Create a synthetic report using only the source report's layout and document types."""

import argparse
from collections import Counter
from datetime import datetime, timedelta
from hashlib import sha256
from itertools import product
import json
from pathlib import Path
import random
import re
import sys
import xml.etree.ElementTree as ET
from zipfile import ZipFile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "static/examples/excel-stock"))
from stock_report import blocks, cells, read_report, refresh_totals, set_number, tag, value, write_report

SAFE_TEXT = {
    "", "Ведомость по товарам на складах", "Параметры:", "Отбор:", "Склад", "Количество",
    "Артикул", "Номенклатура, Характеристика, Серия", "Ед. изм.", "Начальный остаток",
    "Приход", "Расход", "Конечный остаток", "Регистратор", "Итого",
    "Итого товаров в единицах хранения", "шт", "упак", "м", "кг", "компл", "м2", "г", "рул", "л (дм3)"
}
DOCUMENT_TYPES = (
    "Расходный ордер на товары", "Приходный ордер на товары",
    "Ордер на отражение недостач товаров", "Ордер на отражение излишков товаров"
)


def catalogue(unit):
    finishes = ("цинк", "без покрытия", "сталь A2")
    if unit == "шт":
        families = ("Болт DIN 933", "Болт DIN 6921", "Винт DIN 965", "Винт DIN 912",
                    "Винт DIN 7985", "Шпилька DIN 975", "Винт DIN 913", "Болт DIN 603")
        return [f"{kind} М{diameter}×{length}, {finish}"
                for kind, diameter, length, finish in product(
                    families, (3, 4, 5, 6, 8, 10, 12, 16),
                    (12, 16, 20, 25, 30, 35, 40, 45, 50, 60, 70, 80, 90, 100, 120, 140, 160), finishes
                ) if length >= 2 * diameter]
    if unit == "упак":
        return [f"Саморезы {d}×{length}, {finish}, {count} шт./уп."
                for d, length, finish, count in product(
                    ("3,5", "4,0", "4,5", "5,0"), (25, 30, 40, 50, 60, 70),
                    ("жёлтый цинк", "белый цинк"), (50, 100, 200))]
    if unit == "м":
        return [f"Кабель монтажный {cores}×{section} мм², {color}"
                for cores, section, color in product((2, 3, 4, 5), ("0,5", "0,75", "1,0", "1,5", "2,5", "4,0"),
                                                     ("белый", "серый", "чёрный", "синий"))]
    if unit == "кг":
        return [f"Гранулы полипропилена {grade}, {color}"
                for grade, color in product(("PP-H", "PP-B", "PP-R", "PP-GF30"),
                                           ("натуральные", "белые", "серые", "чёрные", "синие", "зелёные"))]
    special = {"компл": ["Набор торцевых головок 1/4, 46 предметов", "Набор ключей комбинированных 6–22 мм", "Набор свёрл по металлу 1–10 мм"],
               "м2": ["Лист поликарбоната прозрачный 4 мм", "Лист поликарбоната бронзовый 6 мм", "Лист поликарбоната молочный 8 мм"],
               "г": ["Краситель для полимеров синий"], "рул": ["Плёнка упаковочная прозрачная 500 мм, 20 мкм"],
               "л (дм3)": ["Масло для пневмоинструмента ISO VG 32"]}
    return special[unit]


def prepare(source, destination):
    if source.resolve() == destination.resolve():
        raise ValueError("Choose a separate demonstration file")
    source_hash = sha256(source.read_bytes()).hexdigest()
    sheet, strings, styles = read_report(source)
    # Only standard style names and numeric format codes are copied from this template.
    style_tree = ET.fromstring(styles)
    if any(s.get("name") != "Обычный" for s in style_tree.iter(tag("cellStyle"))):
        raise ValueError("Review custom style names before copying")
    if any(f.get("formatCode") not in ("", "0.000", "#,##0.000") for f in style_tree.iter(tag("numFmt"))):
        raise ValueError("Review custom number formats before copying")
    rows = {int(row.get("r")): row for row in sheet.find(tag("sheetData"))}
    products, end = blocks(sheet, strings)
    rng = random.Random(73419)
    new_strings = list(strings)
    original_cells = {(r, col): value(c, strings) for r, row in rows.items() for col, c in cells(row).items()}
    candidates = {}
    units = {}
    product_names = {}
    for start, _ in products:
        unit = original_cells.get((start, "L")) or "шт"
        units[start] = unit
        if unit not in candidates:
            candidates[unit] = [name for name in catalogue(unit) if name not in strings]
            rng.shuffle(candidates[unit])
        old = original_cells[start, "C"]
        if old not in product_names:
            product_names[old] = candidates[unit].pop()
    documents = sorted({text for text in strings if any(text.startswith(t + " ") for t in DOCUMENT_TYPES)},
                       key=lambda s: datetime.strptime(s.rsplit(" от ", 1)[1], "%d.%m.%Y %H:%M:%S"))
    replacements = {}
    for i, text in enumerate(documents):
        kind = next(t for t in DOCUMENT_TYPES if text.startswith(t + " "))
        date = datetime(2024, 1, 3, 8) + timedelta(seconds=i * 14500)
        replacements[text] = f"{kind} КР-{150001 + i:06d} от {date:%d.%m.%Y %H:%M:%S}"

    def put_text(row, col, text):
        cell = cells(row).get(col)
        if cell is None:
            cell = ET.SubElement(row, tag("c"), r=col + row.get("r"))
        for child in list(cell):
            cell.remove(child)
        cell.set("t", "s")
        new_strings.append(text)
        ET.SubElement(cell, tag("v")).text = str(len(new_strings) - 1)

    for number, row in rows.items():
        for col, cell in list(cells(row).items()):
            old = original_cells[number, col]
            if cell.get("t") == "s" and cell.find(tag("v")) is not None:
                if number in units and col == "C":
                    new = product_names[old]
                elif old in replacements:
                    new = replacements[old]
                elif number == 4 and col == "D":
                    new = "Период: 01.01.2024 - 31.12.2024"
                elif number == 5 and col == "D":
                    new = 'Склад Равно "Склад комплектующих"'
                elif number == 10 and col == "A":
                    new = "Склад комплектующих"
                elif old in SAFE_TEXT:
                    new = old
                else:
                    raise ValueError(f"Unclassified source text at {cell.get('r')}")
                put_text(row, col, new)
            elif cell.find(tag("v")) is not None:
                set_number(row, col, 0)
    for start, stop in products:
        put_text(rows[start], "L", units[start])
        movements = []
        for number in range(start + 1, stop):
            name = original_cells.get((number, "A"), "")
            if not name:
                continue
            incoming = name.startswith(("Приходный ордер", "Ордер на отражение излишков"))
            outgoing = name.startswith(("Расходный ордер", "Ордер на отражение недостач"))
            if not (incoming or outgoing):
                raise ValueError(f"Unknown movement at row {number}")
            quantity = rng.randint(2, 80)
            movements.append((number, quantity if incoming else 0, quantity if outgoing else 0))
        opening = sum(out for _, _, out in movements) + rng.randint(5, 60)
        balance = opening
        for number, received, issued in movements:
            for col, amount in zip("MNOP", (balance, received, issued, balance + received - issued)):
                set_number(rows[number], col, amount)
            balance += received - issued
        for col, amount in zip("MNOP", (opening, sum(x[1] for x in movements), sum(x[2] for x in movements), balance)):
            set_number(rows[start], col, amount)
    summary_units = sorted(set(units.values()))
    for index, number in enumerate(range(end + 6, max(rows))):
        put_text(rows[number], "A", summary_units[index] if index < len(summary_units) else "")
    sheet.find(tag("dimension")).set("ref", f"A1:P{max(rows)}")
    refresh_totals(sheet, new_strings)
    write_report(destination, sheet, new_strings, styles)
    with ZipFile(destination) as archive:
        output_text = "\n".join(" ".join(ET.fromstring(archive.read(name)).itertext()) for name in archive.namelist())
        sensitive = {s for s in strings if s and s not in SAFE_TEXT}
        if any(s in output_text for s in sensitive):
            raise ValueError("A source-specific text survived the transformation")
        assert len(archive.namelist()) == 7
        assert not archive.comment
    if source_hash != sha256(source.read_bytes()).hexdigest():
        raise AssertionError("Source file changed")
    return {"rows": len(rows), "products": len(products), "merges": len(sheet.find(tag("mergeCells"))),
            "document_types": dict(Counter(next(t for t in DOCUMENT_TYPES if d.startswith(t + " ")) for d in replacements)),
            "source_specific_strings_checked": len(sensitive), "source_specific_strings_remaining": 0,
            "source_unchanged": True, "package_parts": 7}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.source, args.destination), ensure_ascii=False, indent=2))
