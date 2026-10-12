"""Import eligible multi-label professionals from profissionais_revisar.csv."""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.domain.db.person_model import PersonModel  # noqa: E402
from app.domain.db.professional_model import ProfessionalModel  # noqa: E402
from app.domain.enum.channels import Channel  # noqa: E402
from app.domain.enum.chat_mode import ChatMode  # noqa: E402
from app.domain.matching.profile import key, professional_profile  # noqa: E402

SOURCE = Path(__file__).with_name("profissionais_revisar.csv")
SINGLE_AREA_REVIEW = Path(__file__).with_name("profissionais_revisar2.csv")
CLEANED = Path(__file__).with_name("profissionais_limpos.csv")


@dataclass(frozen=True)
class ImportRow:
    name: str
    phone: str
    email: str
    area: str
    matching_profile: dict


def phone_number(value: str) -> str | None:
    if not re.fullmatch(r"(?:https?://)?(?:www\.)?wa\.me/\d{8,15}", value.strip(), re.I):
        return None
    digits = re.sub(r"\D", "", value)
    return digits if 8 <= len(digits) <= 15 and not digits.startswith("0") else None


def parse_labels(raw: str) -> dict | None:
    labels = [part.strip() for part in raw.split(",") if part.strip()]
    areas: list[str] = []
    approaches: list[str] = []
    gender: str | None = None
    race: str | None = None
    lgbtqiapn_plus: bool | None = None
    for label in labels:
        normalized = key(label)
        if normalized in ("psicoterapia", "psicoterapia tcc", "psicanalise", "psicoterapia com mulher",
                          "psicoterapia com homem negro", "psicoterapia com mulher negra", "psicoterapia lgbtqiapn+"):
            if "Psicoterapia" not in areas:
                areas.append("Psicoterapia")
            if normalized == "psicoterapia tcc":
                approaches.append("TCC")
            elif normalized == "psicanalise":
                approaches.append("Psicanálise")
            elif normalized in ("psicoterapia com mulher", "psicoterapia com mulher negra"):
                if gender not in (None, "Mulher"):
                    return None
                gender = "Mulher"
            elif normalized == "psicoterapia com homem negro":
                if gender not in (None, "Homem"):
                    return None
                gender = "Homem"
            if normalized in ("psicoterapia com homem negro", "psicoterapia com mulher negra"):
                race = "Negra"
            if normalized == "psicoterapia lgbtqiapn+":
                lgbtqiapn_plus = True
        elif normalized in ("clinico geral", "psiquiatria", "terapia holistica", "nutricao"):
            canonical = {"clinico geral": "Clínico geral", "psiquiatria": "Psiquiatria",
                         "terapia holistica": "Terapia holística", "nutricao": "Nutrição"}[normalized]
            if canonical not in areas:
                areas.append(canonical)
        else:
            return None
    if not areas:
        return None
    return professional_profile(areas=areas, approaches=approaches, gender=gender,
                                race=race, lgbtqiapn_plus=lgbtqiapn_plus)


def load() -> tuple[list[ImportRow], list[dict[str, str]], Counter[str]]:
    with SOURCE.open(encoding="utf-8-sig", newline="") as file:
        source = list(csv.DictReader(file))
    with CLEANED.open(encoding="utf-8-sig", newline="") as file:
        cleaned_phones = {phone for row in csv.DictReader(file)
                          if (phone := phone_number(row.get("Zap", ""))) is not None}
    numbers = [phone_number(row.get("Zap", "")) for row in source]
    frequency = Counter(number for number in numbers if number)
    eligible: list[ImportRow] = []
    single_area: list[dict[str, str]] = []
    reasons: Counter[str] = Counter()
    for row, phone in zip(source, numbers, strict=True):
        labels = [part.strip() for part in row["Área"].split(",") if part.strip()]
        if len(labels) <= 1:
            single_area.append(row)
            reasons["uma_area_para_revisar"] += 1
            continue
        if row["motivo"].strip() != "múltiplas áreas":
            reasons["outro_problema"] += 1
            continue
        if phone is None or phone in cleaned_phones or frequency[phone] > 1:
            reasons["telefone_invalido_ou_duplicado"] += 1
            continue
        name = row["PROFISSIONAIS"].strip()
        if not name:
            reasons["nome_ausente"] += 1
            continue
        email = row["email"].strip()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or email.casefold() == "org.metamorfose@gmail.com":
            reasons["email_invalido"] += 1
            continue
        profile = parse_labels(row["Área"])
        if profile is None:
            reasons["rotulo_ambiguo"] += 1
            continue
        eligible.append(ImportRow(name, phone, email,
                                  profile["areas"][0], profile))
    return eligible, single_area, reasons


def write_single_area(rows: list[dict[str, str]]) -> None:
    if SINGLE_AREA_REVIEW.exists():
        with SINGLE_AREA_REVIEW.open(encoding="utf-8-sig", newline="") as file:
            existing = list(csv.DictReader(file))
        if existing == rows:
            return
        raise FileExistsError(f"{SINGLE_AREA_REVIEW} já existe com conteúdo diferente")
    with SINGLE_AREA_REVIEW.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["PROFISSIONAIS", "Área", "Zap", "email",
                                                  "ativo 1 inativo 0", "linha_origem", "motivo"])
        writer.writeheader()
        writer.writerows(rows)


def import_rows(rows: list[ImportRow], database_url: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with Session(engine) as session, session.begin():
            for row in rows:
                existing = session.scalar(select(PersonModel.id).where(
                    PersonModel.phone_number == row.phone, PersonModel.channel == Channel.WHATSAPP))
                if existing is not None:
                    counts["ja_existe_no_banco"] += 1
                    continue
                person = PersonModel(phone_number=row.phone, channel=Channel.WHATSAPP, name=row.name,
                                     chat_mode=ChatMode.AUTOMATIC, created_at=datetime.now(UTC))
                session.add(person)
                session.flush()
                session.add(ProfessionalModel(person_id=person.id, area=row.area,
                    matching_profile=row.matching_profile, professional_register=f"CSV-REVIEW-{person.id}",
                    register_type="CSV_IMPORT_REVIEW", approach=", ".join(row.matching_profile["psychotherapy"]["approaches"]) or None,
                    gender=row.matching_profile["profile"]["gender"],
                    minority_group=None, email=row.email, created_at=datetime.now(UTC)))
                counts["importados"] += 1
    finally:
        engine.dispose()
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="classifica CSV sem conectar ao banco")
    parser.add_argument("--yes", action="store_true", help="confirma importação no banco")
    args = parser.parse_args()
    rows, single_area, reasons = load()
    write_single_area(single_area)
    print(f"Elegíveis: {len(rows)}; uma área em revisar2: {len(single_area)}; ignorados: {dict(reasons)}")
    if args.dry_run:
        return
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise ValueError("Defina DATABASE_URL antes de importar")
    if not args.yes and input("Digite IMPORTAR para confirmar: ") != "IMPORTAR":
        print("Importação cancelada")
        return
    print(dict(import_rows(rows, database_url)))


if __name__ == "__main__":
    main()
