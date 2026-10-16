"""Add private import tables without rewriting the legacy catalog. Explicit apply only."""
import argparse


def create_import_tables(bind):
    from app.models.dataset_import import ImportedDataset, DatasetImport
    for model in (ImportedDataset, DatasetImport):
        model.__table__.create(bind, checkfirst=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Create the two additive tables in the configured database")
    args = parser.parse_args()
    if not args.apply:
        parser.exit(0, "Dry run: imported_dataset and dataset_import would be created; existing rows are unchanged.\n")
    from app.database import engine
    create_import_tables(engine)


if __name__ == "__main__":
    main()
