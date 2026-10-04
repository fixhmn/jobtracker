import csv
from io import StringIO

COLUMNS = (
    "id",
    "company",
    "position",
    "url",
    "location",
    "status",
    "applied_at",
    "salary_min",
    "salary_max",
    "currency",
    "salary_period",
    "notes",
)


def safe_cell(value):
    if value is None:
        return ""
    text = str(value)
    # Quoting alone doesn't stop Excel from treating a cell as a formula.
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text


def applications_csv(rows):
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(COLUMNS)
    for row in rows:
        writer.writerow([safe_cell(row.get(column)) for column in COLUMNS])
    return output.getvalue()
