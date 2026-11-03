import re, shutil, zipfile, openpyxl

src = '123_123.xlsx'
dst = '123_123_no_rashod.xlsx'
sheet_name = 'xl/worksheets/sheet1.xml'

wb = openpyxl.load_workbook(src, data_only=True)
ws = wb['Лист_1']

products = [r for r in range(1, ws.max_row + 1)
            if ws.cell(r, 1).value is None and ws.cell(r, 3).value is not None]
products = [r for r in products if r >= 10]  # data section starts after the group header
deleted = set()
for i, p in enumerate(products):
    end = products[i + 1] - 1 if i + 1 < len(products) else 7679
    if any(str(ws.cell(r, 1).value or '').startswith('Расходный ордер')
           for r in range(p, end + 1)):
        deleted.update(range(p, end + 1))

z = zipfile.ZipFile(src)
xml = z.read(sheet_name).decode('utf-8')
row_re = re.compile(r'<row\b[^>]*/>|<row\b[^>]*>.*?</row>', re.S)

def shift(old):
    return old - sum(1 for d in deleted if d < old)

def renumber_row(m):
    tag = m.group(0)
    old = int(re.search(r'\br="(\d+)"', tag).group(1))
    if old in deleted:
        return ''
    new = shift(old)
    tag = re.sub(r'\br="\d+"', f'r="{new}"', tag, count=1)
    tag = re.sub(r'\br="([A-Z]+)\d+"', lambda x: f'r="{x.group(1)}{new}"', tag)
    return tag

xml = row_re.sub(renumber_row, xml)

def renumber_merge(m):
    ref = m.group(1)
    a, b = ref.split(':')
    def rc(s):
        return re.match(r'([A-Z]+)(\d+)', s).groups()
    c1, r1 = rc(a); c2, r2 = rc(b)
    r1, r2 = int(r1), int(r2)
    if r1 in deleted:
        return ''
    if any(r in deleted for r in range(r1, r2 + 1)):
        raise SystemExit(f'merge spans deleted rows: {ref}')
    return f'<mergeCell ref="{c1}{shift(r1)}:{c2}{shift(r2)}"/>'

xml = re.sub(r'<mergeCell ref="([^"]+)"/>', renumber_merge, xml)
n_merges = len(re.findall(r'<mergeCell ref=', xml))
xml = re.sub(r'<mergeCells count="\d+"', f'<mergeCells count="{n_merges}"', xml)
last = ws.max_row - len(deleted)
xml = re.sub(r'<dimension ref="[^"]+"', f'<dimension ref="A1:P{last}"', xml)

with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as out:
    for item in z.infolist():
        data = xml.encode('utf-8') if item.filename == sheet_name else z.read(item.filename)
        out.writestr(item, data)
z.close()

wb2 = openpyxl.load_workbook(dst, data_only=True)
ws2 = wb2['Лист_1']
prods2 = [r for r in range(1, ws2.max_row + 1)
          if ws2.cell(r, 1).value is None and ws2.cell(r, 3).value is not None and r >= 10]
bad = 0
for i, p in enumerate(prods2):
    end = prods2[i + 1] - 1 if i + 1 < len(prods2) else 7679 - len(deleted)
    if any(str(ws2.cell(r, 1).value or '').startswith('Расходный ордер') for r in range(p, end + 1)):
        bad += 1
print('products before:', len(products), '| deleted products:', len(products) - len(prods2))
print('products after:', len(prods2), '| remaining blocks with Расходный ордер:', bad)
print('rows before/after:', ws.max_row, ws2.max_row)
print('deleted rows:', len(deleted), '| merges:', n_merges)
