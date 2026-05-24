import csv
import json
from pathlib import Path

def write_csv(data: list[dict], filename: str) -> None:
    """Writes a list of dictionaries to a UTF-8 encoded CSV file."""
    if not data:
        print("Keine Daten zum Schreiben in CSV vorhanden.")
        return
    fieldnames = list(data[0].keys())
    with open(filename, "w", encoding="utf-8", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)
    print(f"Erfolgreich {len(data)} Zeilen in CSV '{filename}' geschrieben.")

def read_csv(filename: str) -> list[dict]:
    """Reads a UTF-8 encoded CSV file and returns a list of dictionaries."""
    res = []
    with open(filename, "r", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            res.append(dict(row))
    return res

def write_excel(data: list[dict], filename: str) -> None:
    """Writes a list of dictionaries to an Excel file using pandas."""
    import pandas as pd
    df = pd.DataFrame(data)
    df.to_excel(filename, index=False)
    print(f"Erfolgreich {len(data)} Zeilen in Excel '{filename}' geschrieben.")

def read_excel(filename: str) -> list[dict]:
    """Reads an Excel file using pandas and returns a list of dictionaries."""
    import pandas as pd
    df = pd.read_excel(filename)
    df = df.where(pd.notnull(df), None)
    return df.to_dict(orient="records")
