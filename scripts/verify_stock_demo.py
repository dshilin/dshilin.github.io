"""Read-only, independent checks for the supplied public demonstration files."""

from collections import defaultdict
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET
from zipfile import ZipFile

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "scripts"))
from prepare_stock_demo import SAFE_TEXT

N = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
SOURCE = ROOT / "content/docs/python/123_123.xlsx"
BASE = ROOT / "static/examples/excel-stock"
EXPECTED_PARTS = {"[Content_Types].xml", "_rels/.rels", "xl/workbook.xml",
                  "xl/_rels/workbook.xml.rels", "xl/worksheets/sheet1.xml",
                  "xl/sharedStrings.xml", "xl/styles.xml"}


def inspect(path):
    with ZipFile(path) as archive:
        assert archive.testzip() is None
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        row_elements = list(sheet.find(N + "sheetData"))
        merges = [node.get("ref") for node in sheet.find(N + "mergeCells")]
        styles = sha256(archive.read("xl/styles.xml")).hexdigest()
        texts = []
        for name in archive.namelist():
            node = ET.fromstring(archive.read(name))
            texts.extend(node.itertext())
            texts.extend(v for element in node.iter() for v in element.attrib.values())
        if path != SOURCE:
            assert set(archive.namelist()) == EXPECTED_PARTS
            assert not archive.comment
            assert all(not x.comment and not x.extra and x.date_time == (2024, 1, 1, 0, 0, 0)
                       for x in archive.infolist())
            assert all('TargetMode="External"' not in archive.read(name).decode("utf-8")
                       for name in archive.namelist())
            assert sheet.find(".//" + N + "f") is None
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=False)
    assert workbook.sheetnames == ["Лист_1"]
    values = list(workbook.active.iter_rows(values_only=True))
    workbook.close()
    return values, row_elements, merges, styles, "\n".join(texts)


def product_ranges(rows):
    end = next(i for i, row in enumerate(rows) if i >= 9 and row[0] == "Итого")
    starts = [i for i, row in enumerate(rows[:end]) if i >= 9 and not row[0] and row[2]]
    return list(zip(starts, starts[1:] + [end])), end


def verify_balances(rows):
    ranges, end = product_ranges(rows)
    totals = defaultdict(lambda: [Decimal(0)] * 4)
    for start, stop in ranges:
        header = [Decimal(str(v or 0)) for v in rows[start][12:16]]
        assert header[0] + header[1] - header[2] == header[3]
        running = header[0]
        received = issued = Decimal(0)
        for row in rows[start + 1:stop]:
            if not row[0]:
                continue
            figures = [Decimal(str(v or 0)) for v in row[12:16]]
            assert figures[0] == running
            running += figures[1] - figures[2]
            assert running == figures[3] and running >= 0
            received += figures[1]
            issued += figures[2]
        assert header == [header[0], received, issued, running]
        unit = rows[start][11]
        totals[unit] = [a + b for a, b in zip(totals[unit], header)]
    checked = set()
    for row in rows[end + 1:]:
        if row[0] in totals:
            assert row[0] not in checked
            checked.add(row[0])
            figures = [Decimal(str(row[i] or 0)) for i in (1, 4, 5, 6)]
            assert figures == totals[row[0]]
    assert checked == set(totals)


def main():
    original_hash = sha256(SOURCE.read_bytes()).hexdigest()
    source = inspect(SOURCE)
    demo = inspect(BASE / "inventory_demo.xlsx")
    filtered = inspect(BASE / "inventory_filtered.xlsx")
    with ZipFile(SOURCE) as archive:
        originals = ["".join(t.text or "" for t in item.iter(N + "t"))
                     for item in ET.fromstring(archive.read("xl/sharedStrings.xml"))]
    specific = {text for text in originals if text and text not in SAFE_TEXT}
    assert all(text not in demo[4] and text not in filtered[4] for text in specific)
    assert len(source[0]) == len(demo[0]) == 7697
    assert source[2] == demo[2]
    assert source[3] == demo[3] == filtered[3]
    assert [r.attrib for r in source[1]] == [r.attrib for r in demo[1]]
    assert [[(c.get("r"), c.get("s")) for c in r] for r in source[1]] == [
        [(c.get("r"), c.get("s")) for c in r] for r in demo[1]]
    ranges, end = product_ranges(demo[0])
    deleted = set()
    kept_products = []
    for start, stop in ranges:
        if any(str(row[0] or "").startswith("Расходный ордер") for row in demo[0][start:stop]):
            deleted.update(range(start, stop))
        else:
            kept_products.append(demo[0][start][2])
    after_ranges, _ = product_ranges(filtered[0])
    assert [filtered[0][start][2] for start, _ in after_ranges] == kept_products
    assert not any(str(row[0] or "").startswith("Расходный ордер") for row in filtered[0])
    expected_rows = [row for i, row in enumerate(demo[0]) if i not in deleted]
    # Product and movement values are unchanged; only footer aggregates are recalculated.
    assert filtered[0][:end - len(deleted)] == expected_rows[:end - len(deleted)]
    assert len(filtered[0]) == len(expected_rows) == 600
    expected_elements = [r for i, r in enumerate(demo[1]) if i not in deleted]
    assert [{k: v for k, v in r.attrib.items() if k != "r"} for r in expected_elements] == [
        {k: v for k, v in r.attrib.items() if k != "r"} for r in filtered[1]]
    assert [int(r.get("r")) for r in filtered[1]] == list(range(1, 601))
    kept_mapping = {int(old.get("r")): int(new.get("r")) for old, new in zip(expected_elements, filtered[1])}
    expected_merges = []
    for ref in demo[2]:
        c1, r1, c2, r2 = re.fullmatch(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", ref).groups()
        r1, r2 = int(r1), int(r2)
        if r1 in kept_mapping:
            assert r2 in kept_mapping
            expected_merges.append(f"{c1}{kept_mapping[r1]}:{c2}{kept_mapping[r2]}")
    assert expected_merges == filtered[2]
    verify_balances(demo[0])
    verify_balances(filtered[0])
    assert original_hash == sha256(SOURCE.read_bytes()).hexdigest()
    print(json.dumps({"source_unchanged": True, "source_specific_strings_checked": len(specific),
                      "source_specific_strings_remaining": 0, "package_parts_each": 7,
                      "properties_comments_drawings_external_links": "absent",
                      "input_rows": len(demo[0]), "output_rows": len(filtered[0]),
                      "input_products": len(ranges), "output_products": len(after_ranges),
                      "removed_products": len(ranges) - len(after_ranges), "removed_rows": len(deleted),
                      "remaining_expense_orders": 0, "input_merges": len(demo[2]), "output_merges": len(filtered[2]),
                      "styles_row_heights_grouping_and_merges": "verified",
                      "product_and_unit_balances": "verified", "reader": "openpyxl " + openpyxl.__version__},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
