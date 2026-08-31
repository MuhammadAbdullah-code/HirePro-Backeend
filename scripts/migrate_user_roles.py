from app.db import get_database, migrate_database


def main() -> None:
    result = migrate_database(get_database())
    print(f"Defaulted to customer: {result['defaulted_to_customer']}")
    print(f"Renamed provider to business: {result['provider_to_business']}")


if __name__ == "__main__":
    main()
