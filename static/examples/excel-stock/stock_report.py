"""Filter the supplied single-sheet stock-report format. Python 3.10+."""

import argparse
from bisect import bisect_left
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
import re
from uuid import uuid4
import xml.etree.ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
RNS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
ET.register_namespace("", NS)
ET.register_namespace("r", RNS)


def tag(name):
    return f"{{{NS}}}{name}"


def read_report(path):
    with ZipFile(path) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        if len(workbook.find(tag("sheets"))) != 1:
            raise ValueError("This example supports one worksheet only")
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        strings = ["".join(t.text or "" for t in item.iter(tag("t")))
                   for item in ET.fromstring(archive.read("xl/sharedStrings.xml"))]
        styles = archive.read("xl/styles.xml")
    if sheet.find(".//" + tag("f")) is not None:
        raise ValueError("Formula references require a separate update strategy")
    return sheet, strings, styles


def cells(row):
    return {re.match(r"[A-Z]+", cell.get("r"))[0]: cell for cell in row}


def value(cell, strings):
    if cell is None or cell.find(tag("v")) is None:
        return ""
    raw = cell.find(tag("v")).text
    return strings[int(raw)] if cell.get("t") == "s" else raw


def set_number(row, column, number):
    cell = cells(row).get(column)
    if cell is None:
        cell = ET.SubElement(row, tag("c"), r=column + row.get("r"))
    for child in list(cell):
        cell.remove(child)
    cell.set("t", "n")
    if number:
        ET.SubElement(cell, tag("v")).text = str(number)


def blocks(sheet, strings):
    rows = list(sheet.find(tag("sheetData")))
    totals = [int(row.get("r")) for row in rows
              if value(cells(row).get("A"), strings) == "Итого"]
    if not totals:
        raise ValueError("The report must have a total row after the product section")
    end = totals[0]
    starts = [int(row.get("r")) for row in rows if 10 <= int(row.get("r")) < end
              and not value(cells(row).get("A"), strings)
              and value(cells(row).get("C"), strings)]
    return list(zip(starts, starts[1:] + [end])), end


def refresh_totals(sheet, strings):
    """Product header figures are authoritative in this report format."""
    rows = {int(row.get("r")): row for row in sheet.find(tag("sheetData"))}
    products, end = blocks(sheet, strings)
    by_unit = defaultdict(lambda: [Decimal(0)] * 4)
    for start, _ in products:
        row_cells = cells(rows[start])
        unit = value(row_cells.get("L"), strings)
        figures = [Decimal(value(row_cells.get(col), strings) or 0) for col in "MNOP"]
        by_unit[unit] = [a + b for a, b in zip(by_unit[unit], figures)]
    for row_number in (10, end):
        for col in "MNOP":
            set_number(rows[row_number], col, 0)
    seen = set()
    for number, row in rows.items():
        if number <= end:
            continue
        label = value(cells(row).get("A"), strings)
        if label in by_unit and label not in seen:
            figures = by_unit[label]
            seen.add(label)
        else:
            figures = [0] * 4
        for col, amount in zip("BEFG", figures):
            # Summary unit lines already have numeric cells; keep blank spacer rows blank.
            if label in by_unit or label == "Итого" or any(
                cells(row).get(c) is not None and cells(row)[c].get("t") == "n"
                and cells(row)[c].find(tag("v")) is not None for c in "BEFG"
            ):
                set_number(row, col, amount)


def xml_bytes(element):
    return ET.tostring(element, encoding="utf-8", xml_declaration=True)


def write_report(path, sheet, strings, styles):
    """Rebuild a small, explicit OOXML package without source metadata or attachments."""
    allowed = {tag(name) for name in (
        "sheetPr", "dimension", "sheetViews", "sheetFormatPr", "cols", "sheetData",
        "mergeCells", "pageMargins", "pageSetup"
    )}
    for child in list(sheet):
        if child.tag not in allowed:
            sheet.remove(child)
    table = ET.Element(tag("sst"))
    indexes = {}
    count = 0
    for cell in sheet.iter(tag("c")):
        if cell.get("t") == "s" and cell.find(tag("v")) is not None:
            text = value(cell, strings)
            if text not in indexes:
                indexes[text] = len(indexes)
                item = ET.SubElement(table, tag("si"))
                ET.SubElement(item, tag("t")).text = text
            cell.find(tag("v")).text = str(indexes[text])
            count += 1
    table.set("count", str(count))
    table.set("uniqueCount", str(len(indexes)))
    workbook = ET.Element(tag("workbook"))
    sheets = ET.SubElement(workbook, tag("sheets"))
    ET.SubElement(sheets, tag("sheet"), {"name": "Лист_1", "sheetId": "1", f"{{{RNS}}}id": "rId1"})
    types = b'''<?xml version="1.0" encoding="utf-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>'''
    root_rels = f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{RNS}/officeDocument" Target="xl/workbook.xml"/></Relationships>'
    workbook_rels = f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{RNS}/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="{RNS}/styles" Target="styles.xml"/><Relationship Id="rId3" Type="{RNS}/sharedStrings" Target="sharedStrings.xml"/></Relationships>'
    parts = {"[Content_Types].xml": types, "_rels/.rels": root_rels.encode(),
             "xl/workbook.xml": xml_bytes(workbook), "xl/_rels/workbook.xml.rels": workbook_rels.encode(),
             "xl/worksheets/sheet1.xml": xml_bytes(sheet), "xl/sharedStrings.xml": xml_bytes(table),
             "xl/styles.xml": styles}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_name(f".{path.stem}-{uuid4().hex}.tmp")
    try:
        with ZipFile(staged, "x", ZIP_DEFLATED) as archive:
            for name, data in parts.items():
                info = ZipInfo(name, date_time=(2024, 1, 1, 0, 0, 0))
                info.compress_type = ZIP_DEFLATED
                archive.writestr(info, data)
        staged.replace(path)
    finally:
        staged.unlink(missing_ok=True)


def filter_report(source, destination):
    if Path(source).resolve() == Path(destination).resolve():
        raise ValueError("Choose a separate output file")
    sheet, strings, styles = read_report(source)
    data = sheet.find(tag("sheetData"))
    rows = {int(row.get("r")): row for row in data}
    products, _ = blocks(sheet, strings)
    removed = set()
    removed_products = 0
    for start, end in products:
        if any(value(cells(rows[r]).get("A"), strings).startswith("Расходный ордер")
               for r in range(start, end)):
            removed.update(range(start, end))
            removed_products += 1
    ordered = sorted(removed)

    def shifted(number):
        return number - bisect_left(ordered, number)

    merges = sheet.find(tag("mergeCells"))
    for merge in list(merges):
        col1, row1, col2, row2 = re.fullmatch(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", merge.get("ref")).groups()
        row1, row2 = int(row1), int(row2)
        overlap = bisect_left(ordered, row2 + 1) - bisect_left(ordered, row1)
        if overlap == row2 - row1 + 1:
            merges.remove(merge)
        elif overlap:
            raise ValueError(f"Merged range crosses a deletion boundary: {merge.get('ref')}")
        else:
            merge.set("ref", f"{col1}{shifted(row1)}:{col2}{shifted(row2)}")
    merges.set("count", str(len(merges)))
    for number, row in rows.items():
        if number in removed:
            data.remove(row)
            continue
        row.set("r", str(shifted(number)))
        for col, cell in cells(row).items():
            cell.set("r", f"{col}{shifted(number)}")
    sheet.find(tag("dimension")).set("ref", f"A1:P{max(int(r.get('r')) for r in data)}")
    refresh_totals(sheet, strings)
    write_report(destination, sheet, strings, styles)
    return {"products_before": len(products), "products_removed": removed_products,
            "products_after": len(products) - removed_products,
            "rows_before": len(rows), "rows_after": len(data), "rows_removed": len(removed),
            "merges_after": len(merges)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(filter_report(args.source, args.destination))
