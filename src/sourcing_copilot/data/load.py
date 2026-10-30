"""Read the three source files from a folder.

candidates.json  - an export shaped like a LinkedIn/CoreSignal dump
roles.json       - roles with requirements and a shortlist, shaped like an ATS export
do_not_contact.csv - people we must not message, keyed by LinkedIn URL

A malformed file raises DataLoadError with the file name and the first problem, so the
app fails loudly at startup rather than screening against half-loaded data.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from .models import Candidate, DoNotContactEntry, Role, SampleData


class DataLoadError(Exception):
    pass


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError as err:
        raise DataLoadError(f"{path.name}: file not found") from err
    except json.JSONDecodeError as err:
        raise DataLoadError(
            f"{path.name}: not valid JSON ({err.msg} at line {err.lineno})"
        ) from err


def _first_error(err: ValidationError) -> str:
    first = err.errors()[0]
    where = ".".join(str(p) for p in first["loc"])
    return f"{where}: {first['msg']}"


def load_sample_data(folder: Path) -> SampleData:
    folder = Path(folder)
    try:
        candidates = TypeAdapter(list[Candidate]).validate_python(
            _read_json(folder / "candidates.json")
        )
    except ValidationError as err:
        raise DataLoadError(f"candidates.json: {_first_error(err)}") from err

    try:
        roles = TypeAdapter(list[Role]).validate_python(_read_json(folder / "roles.json"))
    except ValidationError as err:
        raise DataLoadError(f"roles.json: {_first_error(err)}") from err

    csv_path = folder / "do_not_contact.csv"
    try:
        with csv_path.open(newline="") as handle:
            rows = list(csv.DictReader(handle))
    except FileNotFoundError as err:
        raise DataLoadError("do_not_contact.csv: file not found") from err
    try:
        do_not_contact = TypeAdapter(list[DoNotContactEntry]).validate_python(rows)
    except ValidationError as err:
        raise DataLoadError(f"do_not_contact.csv: {_first_error(err)}") from err

    return SampleData(candidates=candidates, roles=roles, do_not_contact=do_not_contact)
